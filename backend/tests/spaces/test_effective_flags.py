"""Effective flag resolution per space (task 5.1, design D4).

The seam functions are coroutines that talk to the application's engine, so a
test runs them **in the event loop the app is running on** through the
``TestClient`` portal (:func:`in_app_loop`) instead of ``asyncio.run``, which
would build a second loop around connections that belong to the first one.

Precedence under test: environment override, then the space value (non-default
spaces), then the baseline (non-default spaces) or the global value
(``default``).
"""
from __future__ import annotations

import functools
from collections.abc import Callable, Mapping
from typing import Any

import pytest
from sqlalchemy import event

from backend.app.core.config import settings
from backend.app.core.db import get_engine, get_session_factory
from backend.app.core.feature_flags import (
    baseline_flags,
    clear_space_flags,
    resolve_effective_flags,
    set_flags,
)
from backend.app.core.spaces import DEFAULT_SPACE
from backend.tests.spaces.helpers import sqlite_rows

#: Two participant spaces; neither is ``default``.
OCTOCAT = "octocat"
HUBOT = "hubot"


def in_app_loop(client, func: Callable[..., Any], *args: Any) -> Any:
    """Await ``func(*args)`` in the loop that runs the application."""
    return client.portal.call(functools.partial(func, *args))


def effective(client, space: str) -> dict[str, bool]:
    """The effective flags of ``space``, resolved through the seam."""
    return in_app_loop(client, resolve_effective_flags, space)


def write_flags(client, space: str, updates: Mapping[str, bool]) -> None:
    """Apply ``updates`` to ``space`` through ``set_flags``, with its own session."""

    async def _write() -> None:
        session_factory = get_session_factory()
        async with session_factory() as session:
            await set_flags(session, space, updates)

    client.portal.call(_write)


def clear_flags(client, space: str) -> None:
    """Drop every flag value of ``space`` through ``clear_space_flags``."""

    async def _clear() -> None:
        session_factory = get_session_factory()
        async with session_factory() as session:
            await clear_space_flags(session, space)

    client.portal.call(_clear)


def test_default_space_returns_the_global_rows(app_client) -> None:
    """In ``default`` the effective flags are the ``feature_flags`` rows."""
    rows = {key: bool(enabled) for key, enabled in sqlite_rows("SELECT key, enabled FROM feature_flags")}

    assert rows, "the harness seeds the global flag rows"
    assert effective(app_client, DEFAULT_SPACE) == rows


def test_space_value_wins_over_the_baseline(app_client) -> None:
    """A row of the space overrides the baseline value of that flag."""
    assert baseline_flags()["LOCATOR_V2"] is False

    write_flags(app_client, OCTOCAT, {"LOCATOR_V2": True})

    assert effective(app_client, OCTOCAT)["LOCATOR_V2"] is True


def test_default_space_does_not_leak_into_another_space(app_client) -> None:
    """Global rows never reach a space that has set nothing (spec scenario)."""
    write_flags(
        app_client,
        DEFAULT_SPACE,
        {"LOCATOR_V2": True, "BUG_WRONG_PRICE": True, "NEW_CART_UI": True},
    )

    assert effective(app_client, OCTOCAT) == baseline_flags()


def test_key_that_exists_only_as_a_global_row_is_absent_for_a_space(app_client) -> None:
    """An admin PUT in ``default`` may create a key; other spaces never see it."""
    write_flags(app_client, DEFAULT_SPACE, {"ONLY_IN_DEFAULT": True})

    assert effective(app_client, DEFAULT_SPACE)["ONLY_IN_DEFAULT"] is True
    assert "ONLY_IN_DEFAULT" not in effective(app_client, OCTOCAT)


def test_environment_override_wins_over_space_baseline_and_global(
    app_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``WORKSHOP_FLAG_*`` has the last word in every space."""
    write_flags(app_client, OCTOCAT, {"LOCATOR_V2": True})
    write_flags(app_client, DEFAULT_SPACE, {"LOCATOR_V2": True})
    # SEARCH_V2 is set in no space, so it comes from the baseline in OCTOCAT.
    assert baseline_flags()["SEARCH_V2"] is False
    monkeypatch.setattr(
        settings, "feature_flag_overrides", {"LOCATOR_V2": False, "SEARCH_V2": True}
    )

    space_flags = effective(app_client, OCTOCAT)
    default_flags = effective(app_client, DEFAULT_SPACE)

    assert space_flags["LOCATOR_V2"] is False  # beats the space value
    assert default_flags["LOCATOR_V2"] is False  # beats the global value
    assert space_flags["SEARCH_V2"] is True  # beats the baseline value


def test_a_space_row_does_not_change_the_default_space(app_client) -> None:
    """Writing a space flag leaves the global table and ``default`` untouched."""
    before = effective(app_client, DEFAULT_SPACE)

    write_flags(app_client, OCTOCAT, {"LOCATOR_V2": True, "NEW_CART_UI": True})

    assert effective(app_client, DEFAULT_SPACE) == before
    assert sqlite_rows("SELECT COUNT(*) FROM feature_flags WHERE enabled = 1") == [(1,)]


@pytest.mark.parametrize("space", [DEFAULT_SPACE, OCTOCAT])
def test_mutating_the_returned_dict_does_not_affect_the_next_call(app_client, space: str) -> None:
    """Every resolve returns a fresh dict, so no caller can poison another."""
    first = effective(app_client, space)

    first["LOCATOR_V2"] = True
    first["ADDED_BY_A_CALLER"] = True

    second = effective(app_client, space)
    assert second["LOCATOR_V2"] is False
    assert "ADDED_BY_A_CALLER" not in second


@pytest.mark.parametrize("space", [DEFAULT_SPACE, OCTOCAT])
def test_a_change_is_visible_to_the_very_next_resolve(app_client, space: str) -> None:
    """No cache sits between a write and the next read (spec: immediate effect)."""
    assert effective(app_client, space)["LOCATOR_V3"] is False

    write_flags(app_client, space, {"LOCATOR_V3": True})

    assert effective(app_client, space)["LOCATOR_V3"] is True


@pytest.mark.parametrize("space", [DEFAULT_SPACE, OCTOCAT])
def test_a_multi_key_write_makes_exactly_one_commit(app_client, space: str) -> None:
    """``set_flags`` writes all its updates in one transaction."""
    engine = get_engine().sync_engine
    commits: list[Any] = []

    def record_commit(connection: Any) -> None:
        commits.append(connection)

    event.listen(engine, "commit", record_commit)
    try:
        write_flags(
            app_client,
            space,
            {"LOCATOR_V2": True, "BUG_WRONG_PRICE": True, "NEW_CART_UI": True},
        )
    finally:
        event.remove(engine, "commit", record_commit)

    assert len(commits) == 1
    assert effective(app_client, space)["BUG_WRONG_PRICE"] is True


def test_keys_are_upper_cased(app_client) -> None:
    """A lower-case key is stored and resolved as its upper-case name."""
    write_flags(app_client, OCTOCAT, {"locator_v2": True})
    write_flags(app_client, DEFAULT_SPACE, {"new_cart_ui": True})

    assert effective(app_client, OCTOCAT)["LOCATOR_V2"] is True
    assert effective(app_client, DEFAULT_SPACE)["NEW_CART_UI"] is True
    assert sqlite_rows("SELECT key FROM space_feature_flags WHERE space = ?", (OCTOCAT,)) == [
        ("LOCATOR_V2",)
    ]


def test_clearing_one_space_keeps_the_rows_of_another(app_client) -> None:
    """``clear_space_flags`` is scoped to its space (design D7)."""
    write_flags(app_client, OCTOCAT, {"LOCATOR_V2": True})
    write_flags(app_client, HUBOT, {"LOCATOR_V3": True})

    clear_flags(app_client, OCTOCAT)

    assert effective(app_client, OCTOCAT) == baseline_flags()
    assert effective(app_client, HUBOT)["LOCATOR_V3"] is True
    assert sqlite_rows("SELECT space, key FROM space_feature_flags") == [(HUBOT, "LOCATOR_V3")]
