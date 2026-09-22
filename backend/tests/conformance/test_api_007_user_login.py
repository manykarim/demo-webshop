"""API-007 User Login: conformance checks of AC-1 to AC-11.

Written from the story text, the index's interpretation rules and design D3
only. Credentials come from the story: Jamie Rivera
(``jamie@flowlinesupply.com`` / ``demo123``) and Alex Morgan
(``alex.productlead@example.com`` / ``flowline``).

``expires_at`` (AC-1, AC-2) is read with ``datetime.fromisoformat``. The index's
interpretation rules say nothing about datetimes without an offset, and under
ISO 8601 such a value is local time of an unstated zone, so AC-2 requires an
explicit offset before it compares the instant with the current UTC time plus
four hours, within five minutes either way.

Order history (AC-6, AC-7): the ``invoice_url`` and ``summary_url`` of each order
must be ``/api/docs/orders/<that order's id>/invoice.pdf`` and ``.../summary.pdf``
(an absolute URL with that path also matches), and "PDF links" is checked by
fetching each link. "Most recent order first" needs ``created_at`` values that
tell the orders apart: equal timestamps name no most recent order, so AC-7
requires strictly descending ``created_at``.
"""
from __future__ import annotations

import datetime as dt
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest

pytestmark = pytest.mark.conformance

JAMIE = {"email": "jamie@flowlinesupply.com", "password": "demo123"}
ALEX = {"email": "alex.productlead@example.com", "password": "flowline"}
VALIDITY = dt.timedelta(hours=4)
TOLERANCE = dt.timedelta(minutes=5)
ORDER_FIELDS = ("id", "order_number", "status", "total", "created_at")


def json_body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        raise AssertionError(f"the response is not JSON: {response.text[:200]!r}") from None


def login(api: httpx.Client, credentials: dict[str, str]) -> dict[str, Any]:
    """A login that the criterion's Given calls successful: 200 and a JSON object."""
    response = api.post("/api/auth/login", json=credentials)
    assert response.status_code == 200, f"POST /api/auth/login answered {response.status_code}: {response.text[:300]!r}"
    body = json_body(response)
    assert isinstance(body, dict), f"the login response is not a JSON object: {body!r}"
    return body


def array(body: dict[str, Any], key: str) -> list[Any]:
    value = body.get(key)
    assert isinstance(value, list), f"the login response's {key!r} is not an array: {value!r}"
    return value


def parse_datetime(value: Any, what: str) -> dt.datetime:
    assert isinstance(value, str), f"{what} is not a string: {value!r}"
    try:
        return dt.datetime.fromisoformat(value)
    except ValueError:
        raise AssertionError(f"{what} is not an ISO 8601 datetime: {value!r}") from None


def assert_rejected(api: httpx.Client, credentials: dict[str, str]) -> None:
    response = api.post("/api/auth/login", json=credentials)
    assert response.status_code == 401, f"expected 401, got {response.status_code}: {response.text[:200]!r}"
    body = json_body(response)
    assert isinstance(body, dict) and body.get("detail") == "Invalid credentials", f"the 401 body is {body!r}"


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


@pytest.mark.ac("API-007_AC-1")
def test_ac_1_successful_login(api) -> None:
    response = api.post("/api/auth/login", json=JAMIE)

    assert response.status_code == 200, f"POST /api/auth/login answered {response.status_code}: {response.text[:300]!r}"
    body = json_body(response)
    assert isinstance(body, dict), f"the login response is not a JSON object: {body!r}"
    token = body.get("access_token")
    assert isinstance(token, str) and token.strip(), f"access_token is {token!r}"
    assert body.get("token_type") == "bearer", f"token_type is {body.get('token_type')!r}"
    parse_datetime(body.get("expires_at"), "expires_at")
    assert isinstance(body.get("user"), dict), f"user is {body.get('user')!r}"
    for key in ("addresses", "payment_methods", "orders"):
        array(body, key)


@pytest.mark.ac("API-007_AC-2")
def test_ac_2_token_valid_for_4_hours(api) -> None:
    before = dt.datetime.now(dt.UTC)
    body = login(api, JAMIE)
    after = dt.datetime.now(dt.UTC)

    expires = parse_datetime(body.get("expires_at"), "expires_at")

    assert expires.tzinfo is not None and expires.utcoffset() is not None, (
        f"expires_at {body.get('expires_at')!r} has no UTC offset, so it names no instant that can be compared "
        "with the current UTC time"
    )
    assert before + VALIDITY - TOLERANCE <= expires <= after + VALIDITY + TOLERANCE, (
        f"expires_at {expires.isoformat()} is not about 4 hours after {before.isoformat()}"
    )


@pytest.mark.ac("API-007_AC-3")
def test_ac_3_user_object(api) -> None:
    user = login(api, JAMIE).get("user")

    assert isinstance(user, dict), f"user is {user!r}"
    assert user.get("email") == "jamie@flowlinesupply.com", f"user.email is {user.get('email')!r}"
    assert user.get("full_name") == "Jamie Rivera", f"user.full_name is {user.get('full_name')!r}"


@pytest.mark.ac("API-007_AC-4")
def test_ac_4_addresses(api) -> None:
    addresses = array(login(api, JAMIE), "addresses")

    assert len(addresses) == 2, f"expected 2 addresses, got {addresses!r}"
    assert all(isinstance(address, dict) for address in addresses), f"addresses holds non-objects: {addresses!r}"
    got = [(address.get("label"), address.get("city")) for address in addresses]
    assert got == [("Home", "San Francisco"), ("Studio", "San Francisco")], f"the addresses are {got}"


@pytest.mark.ac("API-007_AC-5")
def test_ac_5_payment_methods(api) -> None:
    methods = array(login(api, JAMIE), "payment_methods")

    assert len(methods) == 2, f"expected 2 payment methods, got {methods!r}"
    assert all(isinstance(method, dict) for method in methods), f"payment_methods holds non-objects: {methods!r}"
    got = [(method.get("brand"), method.get("last4")) for method in methods]
    assert got == [("Visa", "4242"), ("Amex", "3782")], f"the payment methods are {got}"
    for method in methods:
        display = method.get("display")
        assert isinstance(display, str) and method["last4"] in display, (
            f"the display of {method.get('brand')} is not a masked card string ending in its last4: {display!r}"
        )


@pytest.mark.ac("API-007_AC-6")
def test_ac_6_orders_with_pdf_links(api) -> None:
    orders = array(login(api, JAMIE), "orders")

    assert len(orders) == 2, f"expected 2 orders, got {orders!r}"
    for order in orders:
        assert isinstance(order, dict), f"an order is not a JSON object: {order!r}"
        missing = [name for name in ORDER_FIELDS if name not in order]
        assert not missing, f"order {order.get('order_number')!r} lacks {missing}: {order!r}"
        for kind in ("invoice", "summary"):
            url = order.get(f"{kind}_url")
            expected = f"/api/docs/orders/{order['id']}/{kind}.pdf"
            assert isinstance(url, str) and urlsplit(url).path == expected, f"{kind}_url is {url!r}, expected {expected}"


@pytest.mark.ac("API-007_AC-6")
def test_ac_6_pdf_links_serve_pdfs(api) -> None:
    orders = array(login(api, JAMIE), "orders")

    links = [order.get(f"{kind}_url") for order in orders if isinstance(order, dict) for kind in ("invoice", "summary")]

    assert links and all(isinstance(link, str) for link in links), f"the orders carry no links: {orders!r}"
    for link in links:
        response = api.get(link)
        assert response.status_code == 200, f"GET {link} answered {response.status_code}"
        content_type = response.headers.get("content-type", "")
        assert content_type.split(";")[0].strip() == "application/pdf", f"GET {link} is {content_type!r}"


@pytest.mark.ac("API-007_AC-7")
def test_ac_7_orders_most_recent_first(api) -> None:
    orders = array(login(api, JAMIE), "orders")

    assert len(orders) >= 2 and all(isinstance(order, dict) for order in orders), f"the orders are {orders!r}"
    created = [parse_datetime(order.get("created_at"), f"created_at of {order.get('order_number')}") for order in orders]
    assert all(newer > older for newer, older in zip(created, created[1:])), (
        "the orders are not strictly most recent first: "
        + ", ".join(f"{order.get('order_number')} {order.get('created_at')}" for order in orders)
    )


@pytest.mark.ac("API-007_AC-8")
def test_ac_8_wrong_password_is_401(api) -> None:
    assert_rejected(api, {"email": "jamie@flowlinesupply.com", "password": "wrongpassword"})


@pytest.mark.ac("API-007_AC-9")
def test_ac_9_unknown_user_is_401(api) -> None:
    assert_rejected(api, {"email": "nonexistent@example.com", "password": "anything"})


@pytest.mark.ac("API-007_AC-10")
def test_ac_10_second_user(api) -> None:
    body = login(api, ALEX)

    user = body.get("user")
    assert isinstance(user, dict) and user.get("full_name") == "Alex Morgan", f"user is {user!r}"
    assert len(array(body, "addresses")) == 1, f"addresses is {body.get('addresses')!r}"
    assert len(array(body, "payment_methods")) == 1, f"payment_methods is {body.get('payment_methods')!r}"
    assert len(array(body, "orders")) == 1, f"orders is {body.get('orders')!r}"


@pytest.mark.ac("API-007_AC-11")
def test_ac_11_email_validation(api) -> None:
    response = api.post("/api/auth/login", json={"email": "not-valid", "password": "demo123"})

    assert response.status_code == 422, f"expected 422, got {response.status_code}: {response.text[:200]!r}"
