"""The hand-written coverage oracle (drift-coverage Decision 7, assertion 3).

Every entry is a selector a participant could reasonably have written against
stage 1, together with the stages in which it must *stop* matching. The list is
hand-written and lives here rather than in ``backend/app/core/workshop``, so a
mapping entry that was forgotten cannot hide itself: the mapping is the thing
under test, and this file is the independent statement of what the workshop
promises to break.

The rule the ``breaks`` column follows (design Decision 7):

* a ``[data-test='…']`` entry breaks in stages 3 and 4 and still matches in
  stage 2, which is what makes stage 2 survivable for a test suite that used
  ``data-test`` everywhere;
* a class entry, or an id that is not a form field, breaks in stages 2 and 4;
* a form-field id breaks in stages 2, 3 and 4.

:func:`expected_breaks` derives that from the selector itself and
:func:`check_oracle_consistency` compares the derivation with what each entry
declares, so the two can never drift apart silently.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from backend.app.core.workshop import COVERED_IDS, FORM_FIELD_IDS, is_covered_class

from .hooks import matches

__all__ = [
    "COVERAGE_ORACLE",
    "SPEC_FLOWS",
    "CoverageEntry",
    "check_coverage",
    "check_oracle_consistency",
    "entries_for_page",
    "expected_breaks",
]

#: The flows of the spec's "Flow coverage" requirement, in its order. Each of
#: them must carry at least one ``data-test`` entry and at least one id or class
#: entry below.
SPEC_FLOWS: tuple[str, ...] = (
    "Navigation and cart badge",
    "Sign-in modal and account menu",
    "Home hero search and featured products",
    "Listing and cards",
    "Product detail",
    "Cart",
    "Checkout form, summary and result",
    "Chat widget",
)

#: A covered flow of design Decision 3 that the spec's requirement does not
#: list. It has no ``data-test`` hook of its own, so it is kept apart from
#: :data:`SPEC_FLOWS`, whose entries must have one.
CONFIRMATION_FLOW = "Add-to-cart confirmation"

#: Page keys of ``conftest.COVERED_PAGES``, grouped for readability.
#:
#: Every page that renders the whole layout, so the navigation, the sign-in
#: modal, the chat widget and the confirmation region are on it. The
#: ``search-results`` fragment is the one covered page that is not in here.
_FULL_PAGES: tuple[str, ...] = (
    "home",
    "listing",
    "detail",
    "detail-not-found",
    "cart-empty",
    "cart-items",
    "checkout-empty",
    "checkout-items",
    "checkout-post-empty",
    "checkout-post-invalid",
    "checkout-post-success",
)
_SEARCH_PAGES: tuple[str, ...] = ("home", "listing")
_CARD_PAGES: tuple[str, ...] = ("home", "listing", "detail", "search-results")
_GRID_PAGES: tuple[str, ...] = ("home", "listing", "detail")

#: The renders that show the checkout form and the summary. The confirmation
#: render (``checkout-post-success``) shows neither: the order is placed, so
#: ``checkout.html`` renders the result and the "cart cleared" panel instead.
_CHECKOUT_PAGES: tuple[str, ...] = (
    "checkout-empty",
    "checkout-items",
    "checkout-post-empty",
    "checkout-post-invalid",
)

#: The renders that carry a checkout result message: the empty-cart error, the
#: rejected submission and the order confirmation. The ``checkout-alert`` block
#: and the result hook exist on these and nowhere else (task 5.9).
_CHECKOUT_RESULT_PAGES: tuple[str, ...] = (
    "checkout-post-empty",
    "checkout-post-invalid",
    "checkout-post-success",
)

#: The rejected submission, the one render with per-field messages
#: (acceptance-conformance, WEB-006_AC-4 to AC-6 and AC-11).
_CHECKOUT_INVALID_PAGES: tuple[str, ...] = ("checkout-post-invalid",)


@dataclass(frozen=True)
class CoverageEntry:
    """One stage-1 selector and the stages that must break it."""

    flow: str
    selector: str
    breaks: tuple[int, ...]
    pages: tuple[str, ...] = field(default=_FULL_PAGES)

    def must_match(self, stage: int) -> bool:
        """Whether this selector must still find its element in ``stage``."""
        return stage not in self.breaks


#: The oracle. Every entry must match in stage 1 and in every stage it does not
#: name, and must match nothing in the stages it does name.
COVERAGE_ORACLE: tuple[CoverageEntry, ...] = (
    # --- Navigation and cart badge -----------------------------------------
    CoverageEntry("Navigation and cart badge", ".site-nav__link--cart .badge", (2, 4)),
    CoverageEntry("Navigation and cart badge", "#primary-nav-menu", (2, 4)),
    CoverageEntry("Navigation and cart badge", "[data-test='cart-count']", (3, 4)),
    # --- Sign-in modal and account menu ------------------------------------
    CoverageEntry("Sign-in modal and account menu", "#auth-modal", (2, 4)),
    CoverageEntry("Sign-in modal and account menu", "#auth-email", (2, 3, 4)),
    CoverageEntry("Sign-in modal and account menu", ".account-dropdown__trigger", (2, 4)),
    CoverageEntry("Sign-in modal and account menu", "[data-test='auth-submit']", (3, 4)),
    CoverageEntry("Sign-in modal and account menu", "[data-test='account-menu-trigger']", (3, 4)),
    # --- Home hero search and featured products ----------------------------
    CoverageEntry("Home hero search and featured products", ".hero__search", (2, 4), _SEARCH_PAGES),
    CoverageEntry("Home hero search and featured products", "#search-results", (2, 4), _SEARCH_PAGES),
    CoverageEntry("Home hero search and featured products", ".product-grid", (2, 4), _GRID_PAGES),
    CoverageEntry(
        "Home hero search and featured products", "[data-test='search-input']", (3, 4), _SEARCH_PAGES
    ),
    # --- Listing and cards --------------------------------------------------
    CoverageEntry("Listing and cards", "[data-test='product-card']", (3, 4), _CARD_PAGES),
    CoverageEntry("Listing and cards", "[data-test='add-to-cart-btn']", (3, 4), _CARD_PAGES),
    CoverageEntry("Listing and cards", ".product-card__add", (2, 4), _CARD_PAGES),
    CoverageEntry("Listing and cards", ".product-card .product-card__price", (2, 4), _CARD_PAGES),
    # --- Product detail -----------------------------------------------------
    CoverageEntry("Product detail", ".product-hero__actions", (2, 4), ("detail",)),
    CoverageEntry("Product detail", "[data-test='detail-add-to-cart']", (3, 4), ("detail",)),
    CoverageEntry("Product detail", "[data-test='product-not-found']", (3, 4), ("detail-not-found",)),
    # --- Cart ---------------------------------------------------------------
    CoverageEntry("Cart", ".cart-summary__total", (2, 4), ("cart-items",)),
    CoverageEntry("Cart", "[data-test='cart-item']", (3, 4), ("cart-items",)),
    CoverageEntry("Cart", "[data-test='cart-total']", (3, 4), ("cart-items",)),
    # --- Checkout form, summary and result ----------------------------------
    CoverageEntry("Checkout form, summary and result", ".checkout-form", (2, 4), _CHECKOUT_PAGES),
    CoverageEntry("Checkout form, summary and result", "#checkout-email", (2, 3, 4), _CHECKOUT_PAGES),
    CoverageEntry(
        "Checkout form, summary and result", ".checkout-summary__total", (2, 4), _CHECKOUT_PAGES
    ),
    CoverageEntry(
        "Checkout form, summary and result", "[data-test='checkout-submit']", (3, 4), _CHECKOUT_PAGES
    ),
    CoverageEntry(
        "Checkout form, summary and result",
        "[data-test='checkout-email-input']",
        (3, 4),
        _CHECKOUT_PAGES,
    ),
    # The summary total, by its class and by its hook (task 10.2). Both were
    # stated in `test_checkout_totals.py` while this file was off-limits to
    # that batch; the class entry above and this one are the whole set.
    CoverageEntry(
        "Checkout form, summary and result",
        "[data-test='checkout-total']",
        (3, 4),
        _CHECKOUT_PAGES,
    ),
    # The result message, on the two rendered `POST /checkout` results (task
    # 5.9). `checkout-alert` is a covered class *and* a covered id; this is the
    # class.
    CoverageEntry(
        "Checkout form, summary and result", ".checkout-alert", (2, 4), _CHECKOUT_RESULT_PAGES
    ),
    CoverageEntry(
        "Checkout form, summary and result",
        "[data-test='checkout-result']",
        (3, 4),
        _CHECKOUT_RESULT_PAGES,
    ),
    # The per-field messages of a rejected submission, by id (the target of the
    # field's aria-describedby), by class and by hook.
    CoverageEntry(
        "Checkout form, summary and result", "#checkout-email-error", (2, 4), _CHECKOUT_INVALID_PAGES
    ),
    CoverageEntry(
        "Checkout form, summary and result", "#checkout-name-error", (2, 4), _CHECKOUT_INVALID_PAGES
    ),
    CoverageEntry(
        "Checkout form, summary and result", "#checkout-address-error", (2, 4), _CHECKOUT_INVALID_PAGES
    ),
    CoverageEntry(
        "Checkout form, summary and result", ".checkout-form__error", (2, 4), _CHECKOUT_INVALID_PAGES
    ),
    CoverageEntry(
        "Checkout form, summary and result",
        "[data-test='checkout-email-error']",
        (3, 4),
        _CHECKOUT_INVALID_PAGES,
    ),
    CoverageEntry(
        "Checkout form, summary and result",
        "[data-test='checkout-name-error']",
        (3, 4),
        _CHECKOUT_INVALID_PAGES,
    ),
    CoverageEntry(
        "Checkout form, summary and result",
        "[data-test='checkout-address-error']",
        (3, 4),
        _CHECKOUT_INVALID_PAGES,
    ),
    # --- Chat widget ---------------------------------------------------------
    CoverageEntry("Chat widget", "#chat-widget", (2, 4)),
    CoverageEntry("Chat widget", "#chat-input", (2, 3, 4)),
    CoverageEntry("Chat widget", ".chat-launcher", (2, 4)),
    CoverageEntry("Chat widget", "[data-test='chat-launcher']", (3, 4)),
    # --- Add-to-cart confirmation --------------------------------------------
    CoverageEntry(CONFIRMATION_FLOW, "#flash-message", (2, 4)),
    CoverageEntry(CONFIRMATION_FLOW, ".flash", (2, 4)),
)

_DATA_TEST_IN_SELECTOR = re.compile(r"\[\s*data-test\s*[=~|^$*]?=")
_ID_IN_SELECTOR = re.compile(r"#([-_A-Za-z0-9]+)")
_CLASS_IN_SELECTOR = re.compile(r"\.([-_A-Za-z0-9]+)")


def expected_breaks(selector: str) -> tuple[int, ...]:
    """The stages that must break ``selector``, derived from the hooks in it.

    A selector with a descendant combinator breaks as soon as *any* of its parts
    breaks, so the stages are the union over the hooks the selector names.

    Raises:
        ValueError: when the selector names a hook the mapping does not cover;
            such an entry could never break and would only look like coverage.
    """
    stages: set[int] = set()

    if _DATA_TEST_IN_SELECTOR.search(selector):
        stages |= {3, 4}

    for element_id in _ID_IN_SELECTOR.findall(selector):
        if element_id in FORM_FIELD_IDS:
            stages |= {2, 3, 4}
        elif element_id in COVERED_IDS:
            stages |= {2, 4}
        else:
            raise ValueError(f"{selector!r} uses the id {element_id!r}, which never drifts")

    for token in _CLASS_IN_SELECTOR.findall(selector):
        if not is_covered_class(token):
            raise ValueError(f"{selector!r} uses the class {token!r}, which never drifts")
        stages |= {2, 4}

    if not stages:
        raise ValueError(f"{selector!r} names no covered hook at all")

    return tuple(sorted(stages))


def check_oracle_consistency(
    entries: Sequence[CoverageEntry] = COVERAGE_ORACLE,
    flows: Iterable[str] = SPEC_FLOWS,
) -> list[str]:
    """Problems with the oracle itself, before it is used on any render.

    Each entry's declared ``breaks`` must be the derivation of its selector, and
    every flow of the spec's "Flow coverage" requirement must have at least one
    ``data-test`` entry and at least one id or class entry.
    """
    problems: list[str] = []

    for entry in entries:
        try:
            derived = expected_breaks(entry.selector)
        except ValueError as exc:
            problems.append(str(exc))
            continue
        if tuple(entry.breaks) != derived:
            problems.append(
                f"{entry.selector!r} declares breaks {tuple(entry.breaks)} "
                f"but its hooks break in {derived}"
            )
        if not entry.pages:
            problems.append(f"{entry.selector!r} names no page")

    for flow in flows:
        selectors = [entry.selector for entry in entries if entry.flow == flow]
        if not selectors:
            problems.append(f"the flow {flow!r} has no coverage entry at all")
            continue
        if not any(_DATA_TEST_IN_SELECTOR.search(selector) for selector in selectors):
            problems.append(f"the flow {flow!r} has no data-test entry")
        if not any(
            _ID_IN_SELECTOR.search(selector) or _CLASS_IN_SELECTOR.search(selector)
            for selector in selectors
        ):
            problems.append(f"the flow {flow!r} has no id or class entry")

    return problems


def entries_for_page(
    page_key: str, entries: Sequence[CoverageEntry] = COVERAGE_ORACLE
) -> tuple[CoverageEntry, ...]:
    """The oracle entries that apply to ``page_key``."""
    return tuple(entry for entry in entries if page_key in entry.pages)


def check_coverage(
    page_key: str,
    stage: int,
    html: str,
    entries: Sequence[CoverageEntry] = COVERAGE_ORACLE,
) -> list[str]:
    """Every oracle entry that matched when it must not, or the other way round."""
    problems: list[str] = []
    for entry in entries_for_page(page_key, entries):
        found = len(matches(html, entry.selector))
        if entry.must_match(stage) and not found:
            problems.append(
                f"{entry.selector!r} ({entry.flow}) must still match in stage {stage} "
                f"on {page_key}, but matched nothing"
            )
        elif not entry.must_match(stage) and found:
            problems.append(
                f"{entry.selector!r} ({entry.flow}) must break in stage {stage} "
                f"on {page_key}, but matched {found} element(s)"
            )
    return problems
