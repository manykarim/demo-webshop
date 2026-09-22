"""Runtime orders belong to their space (tasks 7.3 and 7.4, design D3/D5).

Seeded demo history carries no space and stays visible everywhere; an order a
checkout created is visible only where it was created. ``order_visible_in`` is
the single predicate behind both the login history and the document endpoints,
so both are asserted against the same order here.
"""
from __future__ import annotations

import sqlite3

from backend.app.core.spaces import SPACE_HEADER
from backend.tests.spaces.helpers import _database_path, sqlite_rows

#: Two participant spaces; neither is ``default``.
OCTOCAT = "octocat"
HUBOT = "hubot"

#: The seeded demo user whose order history the isolation test reuses.
JAMIE = "jamie@flowlinesupply.com"
JAMIE_PASSWORD = "demo123"

#: A valid checkout payload for both the API and the form.
CUSTOMER = {
    "name": "Ada Lovelace",
    "email": "ada@example.com",
    "address": "12 Analytical Way",
}


def space_headers(space: str | None, session_id: str | None = None) -> dict[str, str]:
    """Headers that put a request into ``space`` with an optional session id."""
    headers: dict[str, str] = {}
    if space:
        headers[SPACE_HEADER] = space
    if session_id:
        headers["X-Session-ID"] = session_id
    return headers


def sqlite_execute(sql: str, params: tuple = ()) -> None:
    """Run one committed statement against the active harness database.

    ``_database_path`` of the suite helpers is reused rather than re-derived, so
    this write and every ``sqlite_rows`` read address the same file.
    """
    connection = sqlite3.connect(_database_path())
    try:
        connection.execute(sql, params)
        connection.commit()
    finally:
        connection.close()


def first_product_id() -> int:
    """The id of a seeded product."""
    return int(sqlite_rows("SELECT id FROM products ORDER BY id LIMIT 1")[0][0])


def order_space(order_number: str) -> str | None:
    """The ``orders.space`` value stored for ``order_number``."""
    return sqlite_rows("SELECT space FROM orders WHERE order_number = ?", (order_number,))[0][0]


def api_checkout(client, space: str | None, session_id: str) -> dict:
    """Add an item and check out through ``POST /api/checkout/`` in ``space``."""
    added = client.post(
        "/api/cart/items",
        json={"product_id": first_product_id(), "quantity": 1},
        headers=space_headers(space, session_id),
    )
    assert added.status_code == 200, added.text

    response = client.post(
        "/api/checkout/", json=CUSTOMER, headers=space_headers(space, session_id)
    )
    assert response.status_code == 200, response.text
    return response.json()["order"]


def form_checkout(client, space: str | None, session_id: str) -> str:
    """Add an item and check out through the form ``POST /checkout`` in ``space``."""
    added = client.post(
        "/api/cart/items",
        json={"product_id": first_product_id(), "quantity": 1},
        headers=space_headers(space, session_id),
    )
    assert added.status_code == 200, added.text

    response = client.post(
        "/checkout", data=CUSTOMER, headers=space_headers(space, session_id)
    )
    assert response.status_code == 200, response.text

    rows = sqlite_rows(
        "SELECT order_number FROM orders WHERE space IS NOT NULL ORDER BY id DESC LIMIT 1"
    )
    assert rows, "the form checkout stored no order"
    return str(rows[0][0])


def login(client, space: str | None) -> dict:
    """``POST /api/auth/login`` as the seeded demo user, in ``space``."""
    response = client.post(
        "/api/auth/login",
        json={"email": JAMIE, "password": JAMIE_PASSWORD},
        headers=space_headers(space),
    )
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Task 7.3 - the order carries the space that created it
# ---------------------------------------------------------------------------


def test_an_api_checkout_stores_the_space_of_its_request(seeded_app_client, fake_weasyprint) -> None:
    order = api_checkout(seeded_app_client, OCTOCAT, "demo")

    assert order_space(order["order_number"]) == OCTOCAT


def test_an_api_checkout_without_a_space_stores_default(seeded_app_client, fake_weasyprint) -> None:
    """A runtime order in ``default`` stores ``"default"``, never NULL."""
    order = api_checkout(seeded_app_client, None, "demo")

    assert order_space(order["order_number"]) == "default"


def test_a_form_checkout_stores_the_space_of_its_request(seeded_app_client, fake_weasyprint) -> None:
    order_number = form_checkout(seeded_app_client, OCTOCAT, "demo")

    assert order_space(order_number) == OCTOCAT


def test_seeded_orders_keep_no_space(seeded_app_client, fake_weasyprint) -> None:
    """Seeded demo history stays spaceless, so every space keeps seeing it."""
    seeded = sqlite_rows("SELECT space FROM orders WHERE user_id IS NOT NULL")

    assert seeded, "the seeded database holds no user order"
    assert {row[0] for row in seeded} == {None}


# ---------------------------------------------------------------------------
# Task 7.4 - order_visible_in, applied to login history and documents
# ---------------------------------------------------------------------------


def test_order_history_is_isolated_per_space(seeded_app_client, fake_weasyprint) -> None:
    """*Order history isolation*: seeded history everywhere, runtime orders at home."""
    order = api_checkout(seeded_app_client, OCTOCAT, "demo")
    # Checkout does not link a user yet, so the link is made here; the order
    # then reaches the login history through the relationship under test.
    sqlite_execute(
        "UPDATE orders SET user_id = (SELECT id FROM users WHERE email = ?) "
        "WHERE order_number = ?",
        (JAMIE, order["order_number"]),
    )
    # The seeded history of this one user: every other seeded order belongs to
    # another user and never appears in this login response at all.
    seeded_numbers = {
        str(row[0])
        for row in sqlite_rows(
            "SELECT order_number FROM orders WHERE space IS NULL "
            "AND user_id = (SELECT id FROM users WHERE email = ?)",
            (JAMIE,),
        )
    }
    assert seeded_numbers, "the seeded database holds no order for this user"

    from_hubot = {entry["order_number"] for entry in login(seeded_app_client, HUBOT)["orders"]}
    from_octocat = {entry["order_number"] for entry in login(seeded_app_client, OCTOCAT)["orders"]}

    assert from_hubot == seeded_numbers
    assert order["order_number"] not in from_hubot
    assert from_octocat == seeded_numbers | {order["order_number"]}


def test_a_document_of_another_space_is_indistinguishable_from_a_missing_one(
    seeded_app_client, fake_weasyprint
) -> None:
    """An invoice of another space answers exactly the 404 of an unknown id."""
    order = api_checkout(seeded_app_client, OCTOCAT, "demo")
    url = f"/api/docs/orders/{order['id']}/invoice.pdf"

    foreign = seeded_app_client.get(url, headers=space_headers(HUBOT))
    missing = seeded_app_client.get(
        "/api/docs/orders/99999/invoice.pdf", headers=space_headers(HUBOT)
    )

    assert foreign.status_code == missing.status_code == 404
    assert foreign.content == missing.content


def test_the_owning_space_still_gets_its_document(seeded_app_client, fake_weasyprint) -> None:
    order = api_checkout(seeded_app_client, OCTOCAT, "demo")

    response = seeded_app_client.get(
        f"/api/docs/orders/{order['id']}/invoice.pdf", headers=space_headers(OCTOCAT)
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"


def test_a_seeded_document_stays_available_in_every_space(
    seeded_app_client, fake_weasyprint
) -> None:
    """Seeded orders carry no space, so their documents are visible everywhere."""
    order_id = int(sqlite_rows("SELECT id FROM orders ORDER BY id LIMIT 1")[0][0])
    url = f"/api/docs/orders/{order_id}/invoice.pdf"

    assert seeded_app_client.get(url).status_code == 200
    assert seeded_app_client.get(url, headers=space_headers(HUBOT)).status_code == 200
