"""The space identifier format and the cart keys (tasks 3.1 and 7.1, design D2/D3).

``normalize_space`` is the single place that decides what a valid space looks
like, and ``cart_session_id``/``cart_storage_key`` are the single place that
decides how a cart is addressed, so these tests are plain function calls: no
application, no database and no client is involved.
"""
from __future__ import annotations

import pytest

from backend.app.core.spaces import (
    DEFAULT_SPACE,
    SPACE_FORMAT_MESSAGE,
    cart_session_id,
    cart_storage_key,
    normalize_space,
)

#: The longest identifier GitHub allows, and the shortest one that is too long.
VALID_39_CHARS = "a" * 39
INVALID_40_CHARS = "a" * 40


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("octocat", "octocat"),
        ("OctoCat", "octocat"),
        ("  octocat  ", "octocat"),
        ("default", "default"),
        ("a", "a"),
        ("a-b", "a-b"),
        ("a1-b2-c3", "a1-b2-c3"),
        (VALID_39_CHARS, VALID_39_CHARS),
    ],
)
def test_valid_identifiers_are_lowercased(raw: str, expected: str) -> None:
    assert normalize_space(raw) == expected


def test_default_space_is_a_valid_identifier() -> None:
    assert normalize_space(DEFAULT_SPACE) == DEFAULT_SPACE


@pytest.mark.parametrize("raw", ["", "  ", "\t\n", None])
def test_empty_values_count_as_not_provided(raw: str | None) -> None:
    assert normalize_space(raw) is None


@pytest.mark.parametrize(
    "raw",
    [
        "-bad--name-",
        "a--b",
        "a-",
        "-a",
        INVALID_40_CHARS,
        "a:b",
        "a_b",
        "a%b",
        "a b",
        "a.b",
    ],
)
def test_invalid_identifiers_raise_with_the_format_message(raw: str) -> None:
    with pytest.raises(ValueError) as excinfo:
        normalize_space(raw)

    assert str(excinfo.value) == SPACE_FORMAT_MESSAGE
    assert "1-39" in SPACE_FORMAT_MESSAGE


# ---------------------------------------------------------------------------
# Task 7.1 - cart session id and cart storage key
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("session_id", "expected"),
    [(None, "workshop-demo"), ("demo", "demo")],
)
def test_cart_session_id_falls_back_to_the_shared_demo_session(
    session_id: str | None, expected: str
) -> None:
    """The reported session id is the caller's, or the shared fallback."""
    assert cart_session_id(session_id) == expected


@pytest.mark.parametrize(
    ("space", "session_id", "expected"),
    [
        (DEFAULT_SPACE, None, "workshop-demo"),
        (DEFAULT_SPACE, "demo", "demo"),
        ("octocat", None, "octocat:workshop-demo"),
        ("octocat", "demo", "octocat:demo"),
    ],
)
def test_cart_storage_key_prefixes_every_space_but_the_default(
    space: str, session_id: str | None, expected: str
) -> None:
    """``default`` keeps the legacy keys; every other space is prefixed."""
    assert cart_storage_key(space, session_id) == expected
