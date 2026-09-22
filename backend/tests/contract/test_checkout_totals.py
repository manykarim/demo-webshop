"""Consistent checkout totals and `BUG_CHECKOUT_TOTAL` (tasks 10.2 to 10.4).

The checkout summary is computed by `services/order_service.checkout_summary`
with the tax rate the order itself uses (design Decision 10), so the page and
the created order can never disagree. `BugView.checkout_total` then replaces the
*displayed* total, and only that, when the bug is enabled.

What is asserted here, in every stage:

* the displayed total is the displayed subtotal plus the displayed tax, and the
  old "Calculated after address" placeholder is gone (task 10.2);
* the summary a shopper reads before submitting equals the created order and the
  invoice document rendered from it (task 10.3, spec "Summary matches the
  order");
* with the bug enabled, the displayed total differs from subtotal plus tax while
  both of those stay correct, and the order and its invoice keep correct amounts
  (task 10.4, spec "Inconsistent summary" and "Order stays correct").

Every amount is read from the rendered HTML without a single locator hook: the
summary lines are found by their `<dt>` text and the total by its label, so the
same reader works in stage 1 and in stage 4. The created order is read straight
from the temporary database by its order number, because the shop publishes no
order-by-number endpoint; the invoice comes from the root `fake_weasyprint`
fixture, so no native PDF library is involved.
"""
from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable, Mapping, Sequence

import pytest
from bs4 import BeautifulSoup
from sqlalchemy.engine import make_url

from backend.app.core.workshop import STAGES

from .conftest import PAGES_BY_KEY, STAGE_FLAGS
from .coverage_oracle import (
    COVERAGE_ORACLE,
    CoverageEntry,
    check_coverage,
    check_oracle_consistency,
)
from .semantic import snapshot

#: The planted bug under test.
CHECKOUT_TOTAL_BUG = "BUG_CHECKOUT_TOTAL"

#: The tax rate `OrderService.create_order` and `checkout_summary` share.
TAX_RATE = 0.07

#: The label of the total line, which every stage renders unchanged.
TOTAL_LABEL = "Total due at payment"

#: The placeholder the summary replaced (task 10.2).
OLD_TAX_PLACEHOLDER = "Calculated after address"

#: The checkout pages of the matrix.
CHECKOUT_PAGES: tuple[str, ...] = ("checkout-empty", "checkout-items")

#: The coverage-oracle entries of the summary amounts (task 10.2): the total's
#: class breaks in stages 2 and 4, its `data-test` in stages 3 and 4. Both now
#: live in `coverage_oracle.COVERAGE_ORACLE` (task 14.1), where the whole matrix
#: checks them on every checkout render; they are picked out here by selector so
#: that the totals suite keeps asserting its own hooks and neither copy can
#: drift from the other.
SUMMARY_SELECTORS: frozenset[str] = frozenset(
    {".checkout-summary__total", "[data-test='checkout-total']"}
)
SUMMARY_COVERAGE: tuple[CoverageEntry, ...] = tuple(
    entry for entry in COVERAGE_ORACLE if entry.selector in SUMMARY_SELECTORS
)
assert len(SUMMARY_COVERAGE) == len(SUMMARY_SELECTORS), SUMMARY_COVERAGE

_MONEY = re.compile(r"^\$[\d,]+\.\d{2}$")
_ORDER_NUMBER = re.compile(r"ORD-[0-9A-F]{8}")


def money(text: str) -> float:
    """``"$1,234.56"`` as a float, refusing anything that is not an amount."""
    value = text.strip()
    assert _MONEY.match(value), f"not a currency amount: {value!r}"
    return float(value.replace("$", "").replace(",", ""))


def displayed_amounts(html: str) -> dict[str, float]:
    """Subtotal, tax and total as the checkout page shows them.

    Located by text only - the `<dt>` of each summary line and the total's own
    label - so the reader is identical in every stage.
    """
    soup = BeautifulSoup(html, "html.parser")

    amounts: dict[str, float] = {}
    for term in soup.find_all("dt"):
        label = term.get_text(strip=True).lower()
        if label in {"subtotal", "tax"}:
            definition = term.find_next("dd")
            assert definition is not None, f"the {label} line has no value"
            amounts[label] = money(definition.get_text(strip=True))

    label_node = soup.find(string=TOTAL_LABEL)
    assert label_node is not None, f"no {TOTAL_LABEL!r} label on the page"
    total = label_node.find_parent().find_next("strong")
    assert total is not None, "the total line shows no amount"
    amounts["total"] = money(total.get_text(strip=True))

    assert set(amounts) == {"subtotal", "tax", "total"}, amounts
    return amounts


def invoice_amounts(documents: Sequence[str], order_number: str) -> dict[str, float]:
    """The amounts of the recorded invoice HTML of ``order_number``."""
    for html in documents:
        soup = BeautifulSoup(html, "html.parser")
        title = soup.find("title")
        if title is not None and title.get_text(strip=True) == f"Invoice {order_number}":
            break
    else:  # pragma: no cover - only on a broken render
        raise AssertionError(f"no recorded invoice for {order_number}")

    amounts: dict[str, float] = {}
    for cell in soup.select("td.label"):
        label = cell.get_text(strip=True).lower()
        amount = cell.find_next("td")
        assert amount is not None
        if label.startswith("subtotal"):
            amounts["subtotal"] = money(amount.get_text(strip=True))
        elif label.startswith("tax"):
            amounts["tax"] = money(amount.get_text(strip=True))
        elif label.startswith("total"):
            amounts["total"] = money(amount.get_text(strip=True))

    assert set(amounts) == {"subtotal", "tax", "total"}, amounts
    return amounts


def order_amounts(order_number: str) -> dict[str, float]:
    """The stored order's own amounts, read by its order number.

    The shop publishes no order-by-number endpoint, so the row is read straight
    from the temporary database `contract_client` runs on - read-only, through
    the path `settings` holds while that client is active.
    """
    from backend.app.core.config import settings

    database = make_url(settings.database_url).database
    assert database, f"no database file in {settings.database_url!r}"
    connection = sqlite3.connect(database)
    try:
        row = connection.execute(
            "SELECT subtotal, tax, total FROM orders WHERE order_number = ?",
            (order_number,),
        ).fetchone()
    finally:
        connection.close()

    assert row is not None, f"no order {order_number} in the database"
    return {"subtotal": row[0], "tax": row[1], "total": row[2]}


def order_number_of(html: str) -> str:
    """The order number of a successful `POST /checkout` render."""
    numbers = set(_ORDER_NUMBER.findall(html))
    assert len(numbers) == 1, f"expected exactly one order number, found {numbers}"
    return numbers.pop()


def expected_tax(subtotal: float) -> float:
    return round(subtotal * TAX_RATE, 2)


@pytest.fixture(scope="package")
def cheapest_product(contract_client) -> Mapping[str, object]:
    """The seeded product with the lowest price (the bug's minimal cart)."""
    response = contract_client.get("/api/products/")
    response.raise_for_status()
    items = response.json()["items"]
    assert items
    return min(items, key=lambda item: float(item["price"]))


@pytest.fixture
def place_order(render) -> Callable[..., str]:
    """``place_order(session_id, flags)``: submit the checkout form."""

    def submit(session_id: str, flags: Mapping[str, bool]) -> str:
        response = render(
            "/checkout",
            flags,
            session_id,
            method="POST",
            data={
                "name": "Jamie Product",
                "email": "jamie@flowlinesupply.com",
                "address": "123 Flow Street\nSan Francisco, CA",
            },
        )
        assert response.status_code == 200, response.text
        return response.text

    return submit


# ---------------------------------------------------------------------------
# Task 10.2: the summary itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stage", STAGES)
def test_displayed_total_is_subtotal_plus_tax(rendered, stage: int) -> None:
    """With items, the page adds up: total = subtotal + tax."""
    amounts = displayed_amounts(rendered(PAGES_BY_KEY["checkout-items"], stage))

    assert amounts["subtotal"] > 0
    assert amounts["tax"] == expected_tax(amounts["subtotal"])
    assert amounts["total"] == round(amounts["subtotal"] + amounts["tax"], 2)


@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize("page_key", CHECKOUT_PAGES)
def test_the_tax_placeholder_is_gone(rendered, page_key: str, stage: int) -> None:
    """The summary shows a tax amount instead of a promise."""
    html = rendered(PAGES_BY_KEY[page_key], stage)

    assert OLD_TAX_PLACEHOLDER not in html


@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize("page_key", CHECKOUT_PAGES)
def test_the_summary_snapshot_is_equal_across_stages(
    rendered, page_key: str, stage: int
) -> None:
    """The new summary lines changed nothing a shopper perceives per stage."""
    page = PAGES_BY_KEY[page_key]

    assert snapshot(rendered(page, stage)) == snapshot(rendered(page, 1))


def test_the_summary_coverage_entries_are_consistent() -> None:
    """The declared break stages match the hooks the selectors name."""
    problems = check_oracle_consistency(SUMMARY_COVERAGE, flows=())

    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize("page_key", CHECKOUT_PAGES)
def test_the_total_hooks_break_in_the_declared_stages(
    rendered, page_key: str, stage: int
) -> None:
    """`.checkout-summary__total` breaks in 2 and 4, its `data-test` in 3 and 4."""
    problems = check_coverage(
        page_key, stage, rendered(PAGES_BY_KEY[page_key], stage), SUMMARY_COVERAGE
    )

    assert not problems, "\n".join(problems)


# ---------------------------------------------------------------------------
# Task 10.3: the summary matches the order (spec "Summary matches the order")
# ---------------------------------------------------------------------------


def test_summary_matches_the_created_order_and_its_invoice(
    render, add_to_cart, place_order, fake_weasyprint
) -> None:
    """What the page showed is what the order and its invoice hold."""
    session_id = "contract-checkout-order"
    add_to_cart(session_id, (("PUL-RNG-003", 2), ("ATL-DSK-005", 1)))

    before = displayed_amounts(render("/checkout", {}, session_id).text)
    assert before["subtotal"] > 0

    result = place_order(session_id, {})
    number = order_number_of(result)

    assert order_amounts(number) == before
    assert invoice_amounts(fake_weasyprint, number) == before


# ---------------------------------------------------------------------------
# Task 10.4: the planted bug (spec "Inconsistent summary", "Order stays correct")
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stage", STAGES)
def test_inconsistent_summary(render, add_to_cart, cheapest_product, stage: int) -> None:
    """The displayed total is not the displayed subtotal plus the displayed tax."""
    session_id = f"contract-checkout-bug-summary-{stage}"
    add_to_cart(session_id, ((str(cheapest_product["sku"]), 1),))
    flags = {**STAGE_FLAGS[stage], CHECKOUT_TOTAL_BUG: True}

    amounts = displayed_amounts(render("/checkout", flags, session_id).text)

    price = round(float(cheapest_product["price"]), 2)
    assert amounts["subtotal"] == price
    assert amounts["tax"] == expected_tax(price) >= 0.01
    assert amounts["total"] != round(amounts["subtotal"] + amounts["tax"], 2)


@pytest.mark.parametrize("stage", STAGES)
def test_order_stays_correct(
    render, add_to_cart, place_order, cheapest_product, fake_weasyprint, stage: int
) -> None:
    """The order created from the inconsistent summary is correct anyway."""
    session_id = f"contract-checkout-bug-order-{stage}"
    add_to_cart(session_id, ((str(cheapest_product["sku"]), 1),))
    flags = {**STAGE_FLAGS[stage], CHECKOUT_TOTAL_BUG: True}

    shown = displayed_amounts(render("/checkout", flags, session_id).text)
    number = order_number_of(place_order(session_id, flags))

    order = order_amounts(number)
    assert order["total"] == round(order["subtotal"] + order["tax"], 2)
    assert order["subtotal"] == shown["subtotal"]
    assert order["tax"] == shown["tax"]
    assert order["total"] != shown["total"]
    assert invoice_amounts(fake_weasyprint, number) == order
