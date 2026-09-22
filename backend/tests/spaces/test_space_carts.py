"""Carts are isolated per space and per session id (task 7.2, design D3).

The storage key is what keeps two participants apart; the reported ``session``
is what tooling compares with the ``X-Session-ID`` it sent, so it must stay the
plain session id in every space and never carry the ``<space>:`` prefix.
"""
from __future__ import annotations

from backend.app.core.spaces import SPACE_HEADER
from backend.tests.spaces.helpers import sqlite_rows

#: Two participant spaces; neither is ``default``.
OCTOCAT = "octocat"
HUBOT = "hubot"


def space_headers(space: str | None, session_id: str | None = None) -> dict[str, str]:
    """Headers that put a request into ``space`` with an optional session id."""
    headers: dict[str, str] = {}
    if space:
        headers[SPACE_HEADER] = space
    if session_id:
        headers["X-Session-ID"] = session_id
    return headers


def product_ids() -> list[int]:
    """The ids of the seeded products, lowest first."""
    return [int(row[0]) for row in sqlite_rows("SELECT id FROM products ORDER BY id")]


def product_name(product_id: int) -> str:
    """The catalogue name of ``product_id``, as the cart page renders it."""
    return str(sqlite_rows("SELECT name FROM products WHERE id = ?", (product_id,))[0][0])


def add_item(client, product_id: int, space: str | None = None, session_id: str | None = None):
    """``POST /api/cart/items`` in ``space`` for ``session_id``."""
    response = client.post(
        "/api/cart/items",
        json={"product_id": product_id, "quantity": 1},
        headers=space_headers(space, session_id),
    )
    assert response.status_code == 200, response.text
    return response.json()


def read_cart(client, space: str | None = None, session_id: str | None = None):
    """``GET /api/cart/`` in ``space`` for ``session_id``."""
    response = client.get("/api/cart/", headers=space_headers(space, session_id))
    assert response.status_code == 200, response.text
    return response.json()


def clear_cart(client, space: str | None = None, session_id: str | None = None):
    """``DELETE /api/cart/`` in ``space`` for ``session_id``."""
    response = client.delete("/api/cart/", headers=space_headers(space, session_id))
    assert response.status_code == 200, response.text
    return response.json()


def storage_keys() -> list[str]:
    """Every distinct ``cart_items.session_key`` currently stored."""
    return sorted({str(row[0]) for row in sqlite_rows("SELECT session_key FROM cart_items")})


def cart_product_ids(state: dict) -> list[int]:
    """The product ids in a cart state, in response order."""
    return [item["product_id"] for item in state["items"]]


def test_the_same_session_id_in_two_spaces_has_two_carts(app_client) -> None:
    """*Same session id in two spaces*: the prefix keeps the rows apart."""
    first, second = product_ids()[:2]

    add_item(app_client, first, OCTOCAT, "demo")
    add_item(app_client, second, HUBOT, "demo")

    assert cart_product_ids(read_cart(app_client, OCTOCAT, "demo")) == [first]
    assert cart_product_ids(read_cart(app_client, HUBOT, "demo")) == [second]
    assert storage_keys() == ["hubot:demo", "octocat:demo"]


def test_every_cart_operation_reports_the_plain_session_id(app_client) -> None:
    """The reported ``session`` is the ``X-Session-ID``, never the storage key."""
    product_id = product_ids()[0]

    added = add_item(app_client, product_id, OCTOCAT, "demo")
    read = read_cart(app_client, OCTOCAT, "demo")
    cleared = clear_cart(app_client, OCTOCAT, "demo")

    assert added["session"] == "demo"
    assert read["session"] == "demo"
    assert cleared == {"status": "cleared", "session": "demo"}


def test_two_session_ids_in_one_space_have_separate_carts(app_client) -> None:
    """Within a space the session id still separates browsers, as before."""
    first, second = product_ids()[:2]

    add_item(app_client, first, OCTOCAT, "alpha")
    add_item(app_client, second, OCTOCAT, "beta")

    assert cart_product_ids(read_cart(app_client, OCTOCAT, "alpha")) == [first]
    assert cart_product_ids(read_cart(app_client, OCTOCAT, "beta")) == [second]
    assert storage_keys() == ["octocat:alpha", "octocat:beta"]


def test_the_cart_api_without_a_session_id_uses_its_own_fallback(app_client) -> None:
    """*Cart API without session id*: the fallback cart belongs to the space."""
    product_id = product_ids()[0]

    added = add_item(app_client, product_id, OCTOCAT)
    assert storage_keys() == ["octocat:workshop-demo"]

    read = read_cart(app_client, OCTOCAT)
    cleared = clear_cart(app_client, OCTOCAT)

    assert storage_keys() == []  # the DELETE addressed the same key
    assert added["session"] == "workshop-demo"
    assert read["session"] == "workshop-demo"
    assert cleared == {"status": "cleared", "session": "workshop-demo"}
    for reported in (added["session"], read["session"], cleared["session"]):
        assert ":" not in reported


def test_the_fallback_cart_of_a_space_is_not_the_default_one(app_client) -> None:
    """The space's fallback rows are prefixed and the ``default`` cart stays empty."""
    product_id = product_ids()[0]

    add_item(app_client, product_id, OCTOCAT)

    assert storage_keys() == ["octocat:workshop-demo"]
    assert read_cart(app_client)["items"] == []
    assert read_cart(app_client)["session"] == "workshop-demo"


def test_the_cart_page_shows_the_fallback_cart_of_its_space(app_client) -> None:
    """``/cart`` without a ``session_id`` cookie reads the same fallback key."""
    product_id = product_ids()[0]
    add_item(app_client, product_id, OCTOCAT)

    page = app_client.get("/cart", headers=space_headers(OCTOCAT))

    assert page.status_code == 200
    assert product_name(product_id) in page.text
    assert product_name(product_id) not in app_client.get("/cart").text


def test_the_cart_page_follows_the_session_id_cookie(app_client) -> None:
    """``/cart`` with ``session_id=demo`` reads the API cart of that session."""
    product_id = product_ids()[0]
    add_item(app_client, product_id, OCTOCAT, "demo")
    app_client.cookies.set("session_id", "demo", domain="testserver.local", path="/")

    try:
        page = app_client.get("/cart", headers=space_headers(OCTOCAT))
    finally:
        app_client.cookies.clear()

    assert page.status_code == 200
    assert product_name(product_id) in page.text


def test_the_default_space_keeps_the_legacy_keys(app_client) -> None:
    """*Local mode compatibility*: unprefixed keys and unchanged ``session`` values."""
    first, second = product_ids()[:2]

    with_header = add_item(app_client, first, None, "demo")
    without_header = add_item(app_client, second, None)

    assert storage_keys() == ["demo", "workshop-demo"]
    assert with_header["session"] == "demo"
    assert without_header["session"] == "workshop-demo"
    assert read_cart(app_client, None, "demo")["session"] == "demo"
    assert read_cart(app_client)["session"] == "workshop-demo"
    assert clear_cart(app_client, None, "demo") == {"status": "cleared", "session": "demo"}
    assert clear_cart(app_client) == {"status": "cleared", "session": "workshop-demo"}
