"""The workshop and admin flag APIs act on the requesting space (tasks 6.1, 6.2).

Every test writes flags through the HTTP API only - no seam call and no direct
row insert - because what is under test is that the endpoints pick up the space
of their request and write it back into the right table.
"""
from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import event

from backend.app.api.workshop import PRESETS
from backend.app.core.db import get_engine
from backend.app.core.feature_flags import baseline_flags
from backend.app.core.spaces import SPACE_HEADER
from backend.tests.spaces.helpers import rendered_stage, sqlite_rows

#: Two participant spaces; neither is ``default``.
OCTOCAT = "octocat"
HUBOT = "hubot"


def space_headers(space: str | None) -> dict[str, str]:
    """Request headers that put a request into ``space`` (none for ``default``)."""
    return {SPACE_HEADER: space} if space else {}


def apply_preset(client, preset: str, space: str | None = None):
    """``POST /api/workshop/preset`` in ``space``."""
    return client.post(
        "/api/workshop/preset", json={"preset": preset}, headers=space_headers(space)
    )


def status(client, space: str | None = None) -> dict[str, Any]:
    """``GET /api/workshop/status`` in ``space``."""
    response = client.get("/api/workshop/status", headers=space_headers(space))
    assert response.status_code == 200, response.text
    return response.json()


def listing(client, space: str | None = None) -> str:
    """The rendered ``/products`` page of ``space``."""
    response = client.get("/products", headers=space_headers(space))
    assert response.status_code == 200, response.text
    return response.text


def global_flags() -> dict[str, bool]:
    """The ``feature_flags`` rows as a plain dict."""
    return {key: bool(enabled) for key, enabled in sqlite_rows("SELECT key, enabled FROM feature_flags")}


# ---------------------------------------------------------------------------
# Task 6.1 - the workshop API
# ---------------------------------------------------------------------------


def test_a_preset_does_not_leak_into_another_space(app_client) -> None:
    """*Preset does not leak*: each space keeps the stage it applied."""
    assert apply_preset(app_client, "stage2", OCTOCAT).status_code == 200
    assert apply_preset(app_client, "stage3", HUBOT).status_code == 200

    assert status(app_client, OCTOCAT)["locator_stage"] == "v2"
    assert status(app_client, HUBOT)["locator_stage"] == "v3"
    assert rendered_stage(listing(app_client, OCTOCAT)) == "v2"
    assert rendered_stage(listing(app_client, HUBOT)) == "v3"


def test_the_default_space_does_not_leak_into_a_fresh_space(app_client) -> None:
    """*Default space does not leak*: a space that set nothing sees the baseline."""
    assert apply_preset(app_client, "stage2").status_code == 200
    assert apply_preset(app_client, "buggy").status_code == 200

    assert status(app_client)["locator_stage"] == "v2"
    assert status(app_client)["active_bugs"]

    hubot = status(app_client, HUBOT)
    assert hubot["space"] == HUBOT
    assert hubot["locator_stage"] == "v1"
    assert hubot["active_bugs"] == []
    assert rendered_stage(listing(app_client, HUBOT)) == "v1"


def test_a_preset_is_effective_for_the_next_request(app_client) -> None:
    """*Immediate effect*: no cache stands between the write and the next render."""
    response = apply_preset(app_client, "stage3", OCTOCAT)

    assert response.status_code == 200
    assert response.json()["current_status"]["locator_stage"] == "v3"
    assert rendered_stage(listing(app_client, OCTOCAT)) == "v3"


@pytest.mark.parametrize("space", [None, OCTOCAT])
def test_a_preset_request_makes_exactly_one_commit(app_client, space: str | None) -> None:
    """A preset is one transaction, whatever the number of flags it sets."""
    engine = get_engine().sync_engine
    commits: list[Any] = []

    def record_commit(connection: Any) -> None:
        commits.append(connection)

    event.listen(engine, "commit", record_commit)
    try:
        response = apply_preset(app_client, "clean", space)
    finally:
        event.remove(engine, "commit", record_commit)

    assert response.status_code == 200
    assert len(commits) == 1


def test_bulk_flags_write_only_the_rows_of_their_space(app_client) -> None:
    """``POST /api/workshop/flags`` never touches the global table."""
    before = global_flags()

    response = app_client.post(
        "/api/workshop/flags",
        json={"flags": {"LOCATOR_V2": True, "BUG_WRONG_PRICE": True}},
        headers=space_headers(OCTOCAT),
    )

    assert response.status_code == 200
    assert response.json()["current_status"]["locator_stage"] == "v2"
    assert sorted(sqlite_rows("SELECT space, key, enabled FROM space_feature_flags")) == [
        (OCTOCAT, "BUG_WRONG_PRICE", 1),
        (OCTOCAT, "LOCATOR_V2", 1),
    ]
    assert global_flags() == before


def test_an_unknown_preset_answers_the_unchanged_body(app_client) -> None:
    """The error body of an unknown preset is the one it always was."""
    response = apply_preset(app_client, "no-such-preset", OCTOCAT)

    assert response.status_code == 200
    assert response.json() == {
        "status": "error",
        "message": "Unknown preset: no-such-preset",
        "available_presets": list(PRESETS.keys()),
    }
    assert sqlite_rows("SELECT space, key FROM space_feature_flags") == []


def test_status_reports_the_space_of_the_request(app_client) -> None:
    """``GET /api/workshop/status`` names the caller's space and no other."""
    assert status(app_client)["space"] == "default"
    assert status(app_client, OCTOCAT)["space"] == OCTOCAT


def test_presets_listing_is_unchanged(app_client) -> None:
    """``GET /api/workshop/presets`` is the same in every space."""
    plain = app_client.get("/api/workshop/presets")
    scoped = app_client.get("/api/workshop/presets", headers=space_headers(OCTOCAT))

    assert plain.status_code == 200
    assert scoped.json() == plain.json()
    assert set(plain.json()["presets"]) == set(PRESETS)


# ---------------------------------------------------------------------------
# Task 6.2 - the admin API
# ---------------------------------------------------------------------------


def test_admin_put_writes_a_space_row_and_leaves_the_global_table(app_client) -> None:
    """A PUT in a space creates a ``space_feature_flags`` row, nothing else."""
    before = global_flags()

    response = app_client.put(
        "/api/admin/flags/LOCATOR_V2", json={"enabled": True}, headers=space_headers(OCTOCAT)
    )

    assert response.status_code == 200
    assert response.json() == {"flag": "LOCATOR_V2", "enabled": True}
    assert sqlite_rows("SELECT space, key, enabled FROM space_feature_flags") == [
        (OCTOCAT, "LOCATOR_V2", 1)
    ]
    assert global_flags() == before


def test_admin_get_returns_the_flags_of_its_own_space(app_client) -> None:
    """A space sees the baseline plus its own rows; ``default`` sees the global rows."""
    assert app_client.put(
        "/api/admin/flags/LOCATOR_V2", json={"enabled": True}, headers=space_headers(OCTOCAT)
    ).status_code == 200

    expected = baseline_flags()
    expected["LOCATOR_V2"] = True

    scoped = app_client.get("/api/admin/flags", headers=space_headers(OCTOCAT))
    assert scoped.status_code == 200
    assert scoped.json() == expected

    plain = app_client.get("/api/admin/flags")
    assert plain.status_code == 200
    assert plain.json() == global_flags()


def test_an_environment_override_wins_over_a_space_write(app_client, monkeypatch) -> None:
    """*Environment override*: the operator's value beats every space value."""
    from backend.app.core.config import settings

    monkeypatch.setattr(settings, "feature_flag_overrides", {"LOCATOR_V2": False})

    response = app_client.put(
        "/api/admin/flags/LOCATOR_V2", json={"enabled": True}, headers=space_headers(OCTOCAT)
    )

    assert response.status_code == 200
    assert response.json() == {"flag": "LOCATOR_V2", "enabled": False}
    assert rendered_stage(listing(app_client, OCTOCAT)) == "v1"
    assert status(app_client, OCTOCAT)["all_flags"]["LOCATOR_V2"] is False


def test_admin_put_without_enabled_still_answers_400(app_client) -> None:
    """The payload check is unchanged by the scoping."""
    response = app_client.put(
        "/api/admin/flags/LOCATOR_V2", json={}, headers=space_headers(OCTOCAT)
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Missing 'enabled' boolean in payload"
