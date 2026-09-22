"""API-006 Checkout and Order Creation: conformance checks of AC-1 to AC-13.

Written from the story text, the index's interpretation rules and design D3
only. Every check arranges its cart through ``POST /api/cart/items`` under an
``X-Session-ID`` of its own (``cf-session-<hex>``) and checks out with the same
header, except AC-12, which uses the story's session ``checkout-test``, and
AC-8, whose session has an empty cart. The product is the story's Aurora
Neural Headphones (id 1, $249.99); AC-4 also checks out carts that include a
second catalogue product (id 2), whose price the criterion does not need.

The customer details are the story's valid ones: "Test User",
"test@example.com" and "123 Test Street". The validation criteria (AC-9 to
AC-11) send their invalid body against a non-empty cart, so a missing
validation cannot hide behind the empty-cart answer. Field types (AC-5): an
integer is a JSON integer (never a boolean), a float is a JSON number and a
string is a JSON string.
"""
from __future__ import annotations

import re
import secrets
from collections.abc import Iterable
from typing import Any

import httpx
import pytest

from .conftest import SESSION_HEADER
from .helpers import ConformanceSetupError

pytestmark = pytest.mark.conformance

PRODUCT_ID = 1
PRODUCT_NAME = "Aurora Neural Headphones"
SECOND_ID = 2
CUSTOMER = {"name": "Test User", "email": "test@example.com", "address": "123 Test Street"}
STORY_SESSION = "checkout-test"
ORDER_NUMBER = re.compile(r"ORD-[A-F0-9]{8}")
ITEM_FIELDS = {
    "id": "integer",
    "product_id": "integer",
    "product_name": "string",
    "quantity": "integer",
    "unit_price": "float",
    "total_price": "float",
}


# ---------------------------------------------------------------------------
# Arrange and inspection helpers
# ---------------------------------------------------------------------------


def new_session() -> str:
    return f"cf-session-{secrets.token_hex(8)}"


def arrange_cart(api: httpx.Client, session: str | None, items: Iterable[tuple[int, int]]) -> None:
    """Put ``(product_id, quantity)`` lines into ``session``'s cart (``None``: no header)."""
    headers = {SESSION_HEADER: session} if session is not None else {}
    for product_id, quantity in items:
        body = {"product_id": product_id, "quantity": quantity}
        response = api.post("/api/cart/items", json=body, headers=headers)
        if response.status_code != 200:
            raise ConformanceSetupError(
                f"arranging the cart of {session!r} with {body} answered {response.status_code}: {response.text[:200]!r}"
            )


def json_body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        raise AssertionError(f"the response is not JSON: {response.text[:200]!r}") from None


def checkout(api: httpx.Client, session: str, body: dict[str, Any] | None = None) -> httpx.Response:
    return api.post("/api/checkout/", json=CUSTOMER if body is None else body, headers={SESSION_HEADER: session})


def successful_checkout(api: httpx.Client, items: Iterable[tuple[int, int]], session: str | None = None) -> tuple[str, Any]:
    """Arrange ``items`` under a new session, check out, and return the session and the 200 body."""
    session = session or new_session()
    arrange_cart(api, session, items)
    response = checkout(api, session)
    assert response.status_code == 200, f"POST /api/checkout/ answered {response.status_code}: {response.text[:300]!r}"
    body = json_body(response)
    assert isinstance(body, dict), f"the checkout response is not a JSON object: {body!r}"
    return session, body


def order_of(body: Any) -> dict[str, Any]:
    order = body.get("order") if isinstance(body, dict) else None
    assert isinstance(order, dict), f"the checkout response has no order object: {body!r}"
    return order


def is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def is_float(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


TYPE_CHECKS = {"integer": is_integer, "float": is_float, "string": lambda value: isinstance(value, str)}


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


@pytest.mark.ac("API-006_AC-1")
def test_ac_1_successful_checkout_creates_an_order(api) -> None:
    session = new_session()
    arrange_cart(api, session, [(PRODUCT_ID, 1)])

    response = checkout(api, session)

    assert response.status_code == 200, f"POST /api/checkout/ answered {response.status_code}: {response.text[:300]!r}"
    body = json_body(response)
    assert isinstance(body, dict), f"the checkout response is not a JSON object: {body!r}"
    assert body.get("status") == "success", f"the response's status is {body.get('status')!r}"
    assert isinstance(body.get("order"), dict), f"the response has no order object: {body!r}"
    assert isinstance(body.get("documents"), list), f"the response has no documents array: {body!r}"


@pytest.mark.ac("API-006_AC-2")
def test_ac_2_order_number_format(api) -> None:
    _, body = successful_checkout(api, [(PRODUCT_ID, 1)])

    number = order_of(body).get("order_number")

    assert isinstance(number, str) and ORDER_NUMBER.fullmatch(number), f"the order number is {number!r}"


@pytest.mark.ac("API-006_AC-3")
def test_ac_3_financial_data(api) -> None:
    _, body = successful_checkout(api, [(PRODUCT_ID, 2)])

    order = order_of(body)

    assert order.get("subtotal") == 499.98, f"order.subtotal is {order.get('subtotal')!r}"
    assert order.get("tax") == 35.0, f"order.tax is {order.get('tax')!r}"
    assert order.get("total") == 534.98, f"order.total is {order.get('total')!r}"


@pytest.mark.ac("API-006_AC-4")
@pytest.mark.parametrize(
    "items",
    [[(PRODUCT_ID, 1)], [(PRODUCT_ID, 2)], [(PRODUCT_ID, 3), (SECOND_ID, 2)], [(SECOND_ID, 7)]],
    ids=["1x1", "1x2", "1x3+2x2", "2x7"],
)
def test_ac_4_tax_at_7_percent(api, items) -> None:
    _, body = successful_checkout(api, items)

    order = order_of(body)
    subtotal, tax, total = order.get("subtotal"), order.get("tax"), order.get("total")

    assert all(is_float(value) for value in (subtotal, tax, total)), f"the order's amounts are {order!r}"
    assert tax == round(subtotal * 0.07, 2), f"order.tax {tax!r} is not round({subtotal!r} * 0.07, 2)"
    assert total == round(subtotal + tax, 2), f"order.total {total!r} is not round({subtotal!r} + {tax!r}, 2)"


@pytest.mark.ac("API-006_AC-5")
def test_ac_5_order_item_details(api) -> None:
    _, body = successful_checkout(api, [(PRODUCT_ID, 2), (SECOND_ID, 1)])

    items = order_of(body).get("items")

    assert isinstance(items, list) and len(items) == 2, f"order.items is {items!r}"
    for item in items:
        assert isinstance(item, dict), f"an order item is not a JSON object: {item!r}"
        for name, kind in ITEM_FIELDS.items():
            assert name in item, f"the order item has no {name!r} field: {item!r}"
            assert TYPE_CHECKS[kind](item[name]), f"the order item's {name!r} is not a {kind}: {item[name]!r}"
        product = item["unit_price"] * item["quantity"]
        assert abs(item["total_price"] - product) < 0.005, f"total_price {item['total_price']!r} is not unit_price * quantity in {item!r}"
    primary = [item for item in items if item["product_id"] == PRODUCT_ID]
    assert len(primary) == 1, f"expected one order item for product {PRODUCT_ID}: {items!r}"
    assert primary[0]["product_name"] == PRODUCT_NAME, f"the product name is {primary[0]['product_name']!r}"
    assert primary[0]["quantity"] == 2 and primary[0]["unit_price"] == 249.99, f"the order item is {primary[0]!r}"


@pytest.mark.ac("API-006_AC-6")
def test_ac_6_documents_are_generated(api) -> None:
    _, body = successful_checkout(api, [(PRODUCT_ID, 1)])

    documents = body.get("documents")

    assert isinstance(documents, list) and len(documents) == 2, f"documents is {documents!r}"
    assert all(isinstance(path, str) for path in documents), f"documents holds non-strings: {documents!r}"
    invoices = [path for path in documents if "invoice_ORD-" in path and path.endswith(".pdf")]
    summaries = [path for path in documents if "summary_ORD-" in path and path.endswith(".pdf")]
    assert len(invoices) == 1, f"expected one invoice path in {documents!r}"
    assert len(summaries) == 1, f"expected one summary path in {documents!r}"


@pytest.mark.ac("API-006_AC-7")
def test_ac_7_cart_cleared_after_checkout(api) -> None:
    session, _ = successful_checkout(api, [(PRODUCT_ID, 1)])

    response = api.get("/api/cart/", headers={SESSION_HEADER: session})

    assert response.status_code == 200, f"GET /api/cart/ answered {response.status_code}: {response.text[:200]!r}"
    cart = json_body(response)
    assert cart.get("items") == [], f"the cart still holds {cart.get('items')!r}"
    total = cart.get("total")
    assert is_float(total) and total == 0, f"the cart total is {total!r}"


@pytest.mark.ac("API-006_AC-8")
def test_ac_8_empty_cart_returns_400(api) -> None:
    response = checkout(api, new_session())

    assert response.status_code == 400, f"expected 400, got {response.status_code}: {response.text[:200]!r}"
    body = json_body(response)
    assert isinstance(body, dict) and body.get("detail") == "Cart is empty", f"the 400 body is {body!r}"


def assert_rejected(api: httpx.Client, body: dict[str, Any]) -> None:
    session = new_session()
    arrange_cart(api, session, [(PRODUCT_ID, 1)])

    response = checkout(api, session, body)

    assert response.status_code == 422, f"expected 422, got {response.status_code}: {response.text[:200]!r}"


@pytest.mark.ac("API-006_AC-9")
def test_ac_9_name_minimum_2_characters(api) -> None:
    assert_rejected(api, {"name": "A", "email": "test@example.com", "address": "123 Test Street"})


@pytest.mark.ac("API-006_AC-10")
def test_ac_10_email_valid_format(api) -> None:
    assert_rejected(api, {"name": "Test", "email": "not-an-email", "address": "123 Test Street"})


@pytest.mark.ac("API-006_AC-11")
def test_ac_11_address_minimum_5_characters(api) -> None:
    assert_rejected(api, {"name": "Test", "email": "test@example.com", "address": "Hi"})


@pytest.mark.ac("API-006_AC-12")
def test_ac_12_order_from_the_header_session(api) -> None:
    arrange_cart(api, STORY_SESSION, [(PRODUCT_ID, 2)])
    arrange_cart(api, None, [(SECOND_ID, 1)])
    cart = json_body(api.get("/api/cart/", headers={SESSION_HEADER: STORY_SESSION}))
    expected = sorted((item["product_id"], item["quantity"]) for item in cart.get("items") or [])
    if expected != [(PRODUCT_ID, 2)]:
        raise ConformanceSetupError(f"the arranged cart of {STORY_SESSION!r} holds {cart!r}")

    response = checkout(api, STORY_SESSION)

    assert response.status_code == 200, f"POST /api/checkout/ answered {response.status_code}: {response.text[:300]!r}"
    items = order_of(json_body(response)).get("items")
    assert isinstance(items, list), f"order.items is {items!r}"
    ordered = sorted((item.get("product_id"), item.get("quantity")) for item in items)
    assert ordered == expected, f"the order holds {ordered}, the cart of {STORY_SESSION!r} held {expected}"


@pytest.mark.ac("API-006_AC-13")
def test_ac_13_customer_data(api) -> None:
    _, body = successful_checkout(api, [(PRODUCT_ID, 1)])

    order = order_of(body)

    assert order.get("customer_name") == "Test User", f"order.customer_name is {order.get('customer_name')!r}"
    assert order.get("customer_email") == "test@example.com", f"order.customer_email is {order.get('customer_email')!r}"
    assert order.get("customer_address") == "123 Test Street", f"order.customer_address is {order.get('customer_address')!r}"
    assert order.get("status") == "processing", f"order.status is {order.get('status')!r}"
