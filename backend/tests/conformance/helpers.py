"""Locator helpers and the harness error of the conformance suite (design D3).

Two rules live here:

* **Harness failures are never assertions.** :class:`ConformanceSetupError` is
  the only way the suite's fixtures and helpers signal a setup, precondition,
  usage or teardown failure (``pytest.UsageError`` is used for a misconfigured
  invocation). ``xfail(strict=True, raises=AssertionError)`` also applies to the
  setup and teardown phases, so an ``AssertionError`` raised by a fixture in a
  planted-bug variant would be reported as XFAIL - a misconfigured target
  counted as a passing criterion. ``AssertionError`` is reserved for check
  bodies.
* **Quoted UI text is visible text** (index interpretation rules). ``phrase()``
  turns a quoted phrase into the pattern checks pass to ``has_text`` and
  ``get_by_text``; it is never passed as the ``name=`` of ``get_by_role``.
  Lookups are scoped to the container a criterion names, located from its
  heading, and never use ids, classes or ``data-test`` hooks, which the workshop
  changes on purpose.

Nothing here imports the application.
"""
from __future__ import annotations

import re
from typing import Any


class ConformanceSetupError(Exception):
    """A setup, precondition, usage or teardown failure of the harness.

    Deliberately not an ``AssertionError``: a check that ends with this error is
    a pytest ERROR in every variant, including the xfail-marked ones.
    """


def phrase(text: str) -> re.Pattern[str]:
    """The case-insensitive pattern of a quoted UI phrase.

    The phrase is trimmed; every run of whitespace in it matches one or more
    whitespace characters of the element text (so a label split across lines
    in markup still matches), whitespace is never optional (``"Logout"`` does
    not match ``"Log out"``), and the phrase may be contained in a longer text
    (``"Tax"`` matches ``"Estimated tax"``).
    """
    words = text.split()
    if not words:
        raise ValueError("phrase() needs a non-blank text")
    return re.compile(r"\s+".join(re.escape(word) for word in words), re.IGNORECASE)


def control(scope: Any, role: str, text: str) -> Any:
    """The controls of ``role`` inside ``scope`` whose visible text holds ``text``.

    ``scope`` is a Playwright ``Page`` or ``Locator`` - the container the
    criterion names, not the whole page, wherever the page repeats the control.
    """
    return scope.get_by_role(role).filter(has_text=phrase(text))


def section(page: Any, heading: str) -> Any:
    """The section that holds the heading whose visible text is ``heading``.

    Located from the heading itself: the nearest enclosing ``<section>`` of the
    heading with exactly that accessible name. The catalogue sections carry no
    accessible name of their own, so ``get_by_role("region", ...)`` would find
    nothing; the nearest-ancestor step keeps the enclosing layout section out of
    the match.
    """
    return page.get_by_role("heading", name=heading, exact=True).locator(
        "xpath=ancestor::section[1]"
    )
