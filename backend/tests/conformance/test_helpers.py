"""Offline tests of the locator helpers (task 4.3).

``phrase()`` is checked against plain strings; ``control()`` and ``section()``
against a recorder that stands in for a Playwright page, so no browser is needed.
"""
from __future__ import annotations

import re
from typing import Any

import pytest

from .helpers import ConformanceSetupError, control, phrase, section


@pytest.mark.parametrize(
    ("quoted", "text"),
    [
        ("Add to Cart", "Add to cart"),
        ("Tax", "Estimated tax"),
        ("Log out", "Log\n                out"),
        ("  Add   to Cart ", "Add to cart"),
        ("Order total", "Order\ttotal: $10.00"),
    ],
)
def test_phrase_matches_visible_text(quoted: str, text: str) -> None:
    assert phrase(quoted).search(text)


@pytest.mark.parametrize(
    ("quoted", "text"),
    [
        ("Logout", "Log\n                out"),
        ("Add to Cart", "Add Aurora Neural Headphones to cart"),
        ("Log out", "Logout"),
        ("Tax", "Ta x"),
    ],
)
def test_phrase_does_not_match(quoted: str, text: str) -> None:
    assert phrase(quoted).search(text) is None


def test_phrase_is_a_case_insensitive_whitespace_pattern() -> None:
    pattern = phrase(" Add to  Cart ")

    assert pattern.pattern == r"Add\s+to\s+Cart"
    assert pattern.flags & re.IGNORECASE


def test_phrase_escapes_regex_characters() -> None:
    assert phrase("Total ($)").search("Order total ($) 12")
    assert phrase("a.b").search("axb") is None


def test_phrase_needs_text() -> None:
    with pytest.raises(ValueError):
        phrase("   ")


class Recorder:
    """Records the locator calls made on it, like a Playwright page would receive them."""

    def __init__(self, calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] | None = None) -> None:
        self.calls = calls if calls is not None else []

    def _record(self, method: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Recorder:
        self.calls.append((method, args, kwargs))
        return Recorder(self.calls)

    def get_by_role(self, *args: Any, **kwargs: Any) -> Recorder:
        return self._record("get_by_role", args, kwargs)

    def locator(self, *args: Any, **kwargs: Any) -> Recorder:
        return self._record("locator", args, kwargs)

    def filter(self, *args: Any, **kwargs: Any) -> Recorder:
        return self._record("filter", args, kwargs)


def test_section_is_located_from_its_heading_only() -> None:
    page = Recorder()

    section(page, "All products")

    assert page.calls == [
        ("get_by_role", ("heading",), {"name": "All products", "exact": True}),
        ("locator", ("xpath=ancestor::section[1]",), {}),
    ]
    selectors = [str(arg) for method, args, _ in page.calls if method == "locator" for arg in args]
    for selector in selectors:
        assert not re.search(r"#|\.[a-zA-Z_-]|data-test|@id|@class|\[id|\[class", selector), selector


def test_control_filters_the_role_by_visible_text() -> None:
    scope = Recorder()

    control(scope, "button", "Add to Cart")

    (role_call, filter_call) = scope.calls
    assert role_call == ("get_by_role", ("button",), {})
    assert filter_call[0] == "filter"
    assert filter_call[2]["has_text"].pattern == phrase("Add to Cart").pattern


def test_setup_error_is_not_an_assertion_error() -> None:
    assert not issubclass(ConformanceSetupError, AssertionError)
