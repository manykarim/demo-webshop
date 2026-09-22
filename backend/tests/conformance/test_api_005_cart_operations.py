"""API-005 Cart Operations: conformance checks of AC-1 to AC-11.

Written from the story text, the index's interpretation rules and design D3
only. Every check talks to the cart API through the ``api`` fixture, which
carries the space header in ``per-check`` mode and nothing in ``default`` mode.
``X-Session-ID`` is sent only where a criterion uses it (AC-9); every other
check uses the fallback session, which the fresh space (or the reset default
space) starts with an empty cart. The product is the story's Aurora Neural
Headphones (id 1, $249.99): two units cost 499.98 and three 749.97.

Validation criteria (AC-4 to AC-6) expect a 422 whose ``detail`` list names the
offending field in an entry's ``loc`` and states the limit in that entry's
message. Field types (AC-2, AC-3, AC-11): an integer is a JSON integer (never a
boolean), a float is a JSON number, and a string is a JSON string.
"""
from __future__ import annotations

import secrets
from typing import Any

import httpx
import pytest

from .conftest import SESSION_HEADER
from .helpers import ConformanceSetupError

pytestmark = pytest.mark.conformance

PRODUCT_ID = 1
PRODUCT_NAME = "Aurora Neural Headphones"
UNIT_PRICE = 249.99
DEFAULT_SESSION = "workshop-demo"
HEADER_SESSION = "test-session-123"
ITEM_FIELDS = {"product_id": "integer", "name": "string", "quantity": "integer", "unit_price": "float", "total_price": "float"}


# ---------------------------------------------------------------------------
# Arrange and inspection helpers
# ---------------------------------------------------------------------------


def arrange_item(api: httpx.Client, product_id: int, quantity: int, headers: dict[str, str] | None = None) -> None:
    """Put ``quantity`` of ``product_id`` into the cart (arrange; failures are setup errors)."""
    body = {"product_id": product_id, "quantity": quantity}
    response = api.post("/api/cart/items", json=body, headers=headers or {})
    if response.status_code != 200:
        raise ConformanceSetupError(f"arranging the cart with {body} answered {response.status_code}: {response.text[:200]!r}")


def json_body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        raise AssertionError(f"the response is not JSON: {response.text[:200]!r}") from None


def is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def is_float(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


TYPE_CHECKS = {"integer": is_integer, "float": is_float, "string": lambda value: isinstance(value, str)}


def assert_item_types(item: dict[str, Any]) -> None:
    for name, kind in ITEM_FIELDS.items():
        assert name in item, f"the cart item has no {name!r} field: {item!r}"
        assert TYPE_CHECKS[kind](item[name]), f"the cart item's {name!r} is not a {kind}: {item[name]!r}"


def lines_for(state: Any, product_id: int) -> list[dict[str, Any]]:
    assert isinstance(state, dict), f"the cart state is not a JSON object: {state!r}"
    items = state.get("items")
    assert isinstance(items, list), f"the cart state has no items array: {state!r}"
    return [item for item in items if isinstance(item, dict) and item.get("product_id") == product_id]


def validation_entries(response: httpx.Response, field: str) -> list[dict[str, Any]]:
    """The ``detail`` entries of a 422 whose ``loc`` names ``field``."""
    assert response.status_code == 422, f"expected 422, got {response.status_code}: {response.text[:300]!r}"
    body = json_body(response)
    detail = body.get("detail") if isinstance(body, dict) else None
    assert isinstance(detail, list) and detail, f"the 422 body has no detail list: {body!r}"
    entries = [entry for entry in detail if isinstance(entry, dict) and field in (entry.get("loc") or [])]
    assert entries, f"no validation entry names {field!r} in its loc: {detail!r}"
    return entries


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


@pytest.mark.ac("API-005_AC-1")
def test_ac_1_empty_cart_state(api) -> None:
    response = api.get("/api/cart/")

    assert response.status_code == 200, f"GET /api/cart/ answered {response.status_code}: {response.text[:200]!r}"
    body = json_body(response)
    assert body.get("session") == DEFAULT_SESSION, f"the empty cart names the session {body.get('session')!r}"
    assert body.get("items") == [], f"the empty cart's items are {body.get('items')!r}"
    total = body.get("total")
    assert is_float(total) and total == 0, f"the empty cart's total is {total!r}"


@pytest.mark.ac("API-005_AC-2")
def test_ac_2_add_item(api) -> None:
    response = api.post("/api/cart/items", json={"product_id": PRODUCT_ID, "quantity": 2})

    assert response.status_code == 200, f"POST /api/cart/items answered {response.status_code}: {response.text[:200]!r}"
    body = json_body(response)
    assert isinstance(body, dict) and {"session", "items", "total"} <= body.keys(), f"no cart state in {body!r}"
    lines = lines_for(body, PRODUCT_ID)
    assert len(lines) == 1, f"expected one entry for product {PRODUCT_ID}, got {lines!r}"
    item = lines[0]
    assert_item_types(item)
    assert item["name"] == PRODUCT_NAME, f"the entry's name is {item['name']!r}"
    assert item["quantity"] == 2, f"the entry's quantity is {item['quantity']!r}"
    assert item["unit_price"] == UNIT_PRICE, f"the entry's unit_price is {item['unit_price']!r}"
    assert item["total_price"] == 499.98, f"the entry's total_price is {item['total_price']!r}"
    assert body["total"] == 499.98, f"the cart total is {body['total']!r}"
    assert json_body(api.get("/api/cart/")) == body, "the response is not the cart state GET /api/cart/ returns afterwards"


@pytest.mark.ac("API-005_AC-3")
def test_ac_3_same_product_increments_quantity(api) -> None:
    arrange_item(api, PRODUCT_ID, 2)

    response = api.post("/api/cart/items", json={"product_id": PRODUCT_ID, "quantity": 1})

    assert response.status_code == 200, f"POST /api/cart/items answered {response.status_code}: {response.text[:200]!r}"
    lines = lines_for(json_body(response), PRODUCT_ID)
    assert len(lines) == 1, f"expected one entry for product {PRODUCT_ID}, got {lines!r}"
    item = lines[0]
    assert_item_types(item)
    assert item["quantity"] == 3, f"the entry's quantity is {item['quantity']!r}"
    assert item["total_price"] == 749.97, f"the entry's total_price is {item['total_price']!r}"


@pytest.mark.ac("API-005_AC-4")
def test_ac_4_quantity_at_most_20(api) -> None:
    response = api.post("/api/cart/items", json={"product_id": PRODUCT_ID, "quantity": 21})

    entries = validation_entries(response, "quantity")
    assert any("20" in str(entry.get("msg", "")) for entry in entries), f"no message states the limit 20: {entries!r}"


@pytest.mark.ac("API-005_AC-5")
def test_ac_5_quantity_at_least_1(api) -> None:
    response = api.post("/api/cart/items", json={"product_id": PRODUCT_ID, "quantity": 0})

    entries = validation_entries(response, "quantity")
    assert any("1" in str(entry.get("msg", "")) for entry in entries), f"no message states the limit 1: {entries!r}"


@pytest.mark.ac("API-005_AC-6")
def test_ac_6_product_id_at_least_1(api) -> None:
    response = api.post("/api/cart/items", json={"product_id": 0, "quantity": 1})

    entries = validation_entries(response, "product_id")
    assert any("1" in str(entry.get("msg", "")) for entry in entries), f"no message states the limit 1: {entries!r}"


@pytest.mark.ac("API-005_AC-7")
def test_ac_7_unknown_product_is_404(api) -> None:
    response = api.post("/api/cart/items", json={"product_id": 999, "quantity": 1})

    assert response.status_code == 404, f"expected 404, got {response.status_code}: {response.text[:200]!r}"
    body = json_body(response)
    assert isinstance(body, dict) and body.get("detail") == "Product not found", f"the 404 body is {body!r}"


@pytest.mark.ac("API-005_AC-8")
def test_ac_8_clear_cart(api) -> None:
    arrange_item(api, PRODUCT_ID, 1)

    response = api.delete("/api/cart/")

    assert response.status_code == 200, f"DELETE /api/cart/ answered {response.status_code}: {response.text[:200]!r}"
    body = json_body(response)
    assert body == {"status": "cleared", "session": DEFAULT_SESSION}, f"the clear response is {body!r}"
    assert json_body(api.get("/api/cart/")).get("items") == [], "the cart still holds items after it was cleared"


@pytest.mark.ac("API-005_AC-9")
def test_ac_9_session_from_header(api) -> None:
    headers = {SESSION_HEADER: HEADER_SESSION}
    added = api.post("/api/cart/items", json={"product_id": PRODUCT_ID, "quantity": 1}, headers=headers)
    assert added.status_code == 200, f"POST /api/cart/items answered {added.status_code}: {added.text[:200]!r}"

    response = api.get("/api/cart/", headers=headers)

    assert response.status_code == 200, f"GET /api/cart/ answered {response.status_code}: {response.text[:200]!r}"
    body = json_body(response)
    assert body.get("session") == HEADER_SESSION, f"the cart names the session {body.get('session')!r}"
    lines = lines_for(body, PRODUCT_ID)
    assert len(lines) == 1 and lines[0].get("quantity") == 1, f"the header's cart holds {body.get('items')!r}"


@pytest.mark.ac("API-005_AC-9")
def test_ac_9_other_session_does_not_see_the_item(api) -> None:
    arrange_item(api, PRODUCT_ID, 1, {SESSION_HEADER: HEADER_SESSION})
    other = f"cf-session-{secrets.token_hex(8)}"

    body = json_body(api.get("/api/cart/", headers={SESSION_HEADER: other}))

    assert body.get("session") == other and body.get("items") == [], f"another session's cart is {body!r}"


@pytest.mark.ac("API-005_AC-10")
def test_ac_10_default_session_key(api) -> None:
    response = api.get("/api/cart/")

    assert response.status_code == 200, f"GET /api/cart/ answered {response.status_code}: {response.text[:200]!r}"
    body = json_body(response)
    assert body.get("session") == DEFAULT_SESSION, f"without X-Session-ID the cart names the session {body.get('session')!r}"


@pytest.mark.ac("API-005_AC-11")
def test_ac_11_cart_item_structure(api) -> None:
    arrange_item(api, PRODUCT_ID, 3)
    arrange_item(api, 2, 2)

    response = api.get("/api/cart/")

    assert response.status_code == 200, f"GET /api/cart/ answered {response.status_code}: {response.text[:200]!r}"
    items = json_body(response).get("items")
    assert isinstance(items, list) and len(items) == 2, f"expected two cart items, got {items!r}"
    for item in items:
        assert isinstance(item, dict), f"a cart item is not a JSON object: {item!r}"
        assert_item_types(item)
        expected = round(item["unit_price"] * item["quantity"], 2)
        assert item["total_price"] == expected, f"total_price {item['total_price']!r} is not {expected} for {item!r}"
    primary = [item for item in items if item["product_id"] == PRODUCT_ID]
    assert len(primary) == 1 and primary[0]["total_price"] == 749.97, f"product {PRODUCT_ID}'s line is {primary!r}"
