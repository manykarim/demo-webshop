"""WEB-005 Manage Cart: conformance checks of AC-1 to AC-7, AC-9 and AC-10.

Written from the story text, the index's interpretation rules and design D3
only. The primary product is Aurora Neural Headphones (id 1, $249.99); the
second cart line is Insight Smart Notebook (id 2, $39.50) with quantity 2, so
the arranged cart is $249.99 + $79.00 = $328.99. Product data comes from
``GET /api/products/`` during arrange.

Arrange through the API, act and assert through the UI (design D3). The
criteria about the "Add to Cart" action itself (AC-1, AC-2, AC-9) click the
button in the UI: once in the card of the named product under "All products"
on ``/products`` and once in the product's action area on ``/products/1``
(the section holding the ``h1``, never the related cards), and wait for the
POST to ``/api/cart/items`` with ``page.expect_request``. AC-2 runs at
1280x800 and at 390x844; on the small screen it opens the navigation menu
first, as the criterion says. AC-10 (which replaces the withdrawn AC-8) is a
criterion about the cart API and is checked through it, with the
``X-Session-ID`` header, the ``session_id`` cookie alone (the fallback cart),
neither, and both; its sentence about the shop's pages is checked on ``/cart``.
"""
from __future__ import annotations

import re
import secrets
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
from playwright.sync_api import expect

from .conftest import SESSION_COOKIE, SESSION_HEADER
from .helpers import ConformanceSetupError, control, phrase, section

pytestmark = pytest.mark.conformance

PRIMARY_ID = 1
SECOND_ID = 2
SECOND_QUANTITY = 2
DEFAULT_SESSION = "workshop-demo"
VIEWPORTS = {"desktop": {"width": 1280, "height": 800}, "mobile": {"width": 390, "height": 844}}
WHERE = ("products", "detail")


# ---------------------------------------------------------------------------
# Arrange helpers
# ---------------------------------------------------------------------------


def catalogue(api: httpx.Client) -> dict[int, dict[str, Any]]:
    """The products of ``GET /api/products/`` by id (arrange data)."""
    response = api.get("/api/products/")
    if response.status_code != 200:
        raise ConformanceSetupError(f"GET /api/products/ answered {response.status_code}: {response.text[:200]!r}")
    items = response.json().get("items")
    if not isinstance(items, list) or not items:
        raise ConformanceSetupError("GET /api/products/ returned no product list")
    return {int(item["id"]): item for item in items}


def product(api: httpx.Client, product_id: int) -> dict[str, Any]:
    products = catalogue(api)
    if product_id not in products:
        raise ConformanceSetupError(f"the catalogue has no product {product_id}")
    return products[product_id]


def money(amount: float) -> str:
    return f"${amount:,.2f}"


def norm(text: str) -> str:
    return " ".join(text.split())


def new_session() -> str:
    return f"cf-session-{secrets.token_hex(8)}"


# ---------------------------------------------------------------------------
# Page helpers
# ---------------------------------------------------------------------------


def is_add_request(request: Any) -> bool:
    return request.method == "POST" and urlsplit(request.url).path.rstrip("/") == "/api/cart/items"


def add_button(page: Any, item: dict[str, Any], where: str) -> Any:
    """The "Add to Cart" button of ``item``: its card under "All products", or its detail action area."""
    if where == "products":
        page.goto("/products")
        grid = section(page, "All products")
        card = grid.get_by_role("article").filter(has=page.get_by_role("heading", name=item["name"], exact=True))
        expect(card).to_have_count(1)
        button = control(card, "button", "Add to Cart")
    else:
        page.goto(f"/products/{item['id']}")
        title = page.get_by_role("heading", level=1)
        expect(title).to_have_count(1)
        expect(title).to_have_text(phrase(item["name"]))
        area = section(page, item["name"])
        expect(area).to_have_count(1)
        button = control(area, "button", "Add to Cart")
    expect(button).to_have_count(1)
    button.scroll_into_view_if_needed()
    expect(button).to_be_visible()
    return button


def click_add(page: Any, button: Any) -> Any:
    """Click and return the POST to ``/api/cart/items`` it sent, after its response arrived."""
    with page.expect_request(is_add_request) as info:
        button.click()
    request = info.value
    request.response()
    return request


def cookie_session(context: Any) -> str | None:
    values = [cookie["value"] for cookie in context.cookies() if cookie["name"] == SESSION_COOKIE]
    return values[0] if values else None


def request_session(request: Any) -> str | None:
    """The session identification a cart request carries: its header, else its cookie."""
    headers = request.all_headers()
    header = headers.get(SESSION_HEADER.lower())
    if header:
        return header
    for part in headers.get("cookie", "").split(";"):
        name, _, value = part.strip().partition("=")
        if name == SESSION_COOKIE and value:
            return value
    return None


def cart_badge(page: Any) -> Any:
    """The cart count badge: the count text inside the header's link to the cart."""
    header = page.get_by_role("banner")
    return header.get_by_role("link").filter(has_text=phrase("Cart")).or_(
        header.get_by_role("link", name=re.compile(r"\bcart\b", re.IGNORECASE))
    )


def open_navigation_menu(page: Any) -> None:
    """Open the navigation menu of the small-screen header (its button has no visible text)."""
    toggle = page.get_by_role("banner").get_by_role("button", name=re.compile(r"navigation|menu", re.IGNORECASE))
    expect(toggle).to_have_count(1)
    expect(toggle).to_be_visible()
    toggle.click()


def cart_lines(page: Any, names: list[str]) -> dict[str, Any]:
    """Each cart line of the cart page by product name: the item that names only that product."""
    main = page.get_by_role("main")
    candidates = main.get_by_role("listitem").or_(main.get_by_role("row")).or_(main.get_by_role("article"))
    lines = {}
    for name in names:
        line = candidates.filter(has_text=phrase(name))
        for other in names:
            if other != name:
                line = line.filter(has_not_text=phrase(other))
        expect(line).to_have_count(1)
        lines[name] = line
    return lines


def shows_quantity(line: Any, quantity: int) -> bool:
    fields = line.get_by_role("spinbutton").or_(line.get_by_role("combobox")).or_(line.get_by_role("textbox"))
    for index in range(fields.count()):
        if fields.nth(index).input_value().strip() == str(quantity):
            return True
    return re.search(rf"(?<![\d.,$]){quantity}(?![\d.,])", norm(line.inner_text())) is not None


def cart_summary(page: Any) -> Any:
    """The cart summary: the section or aside that holds a heading naming the summary."""
    heading = page.get_by_role("main").get_by_role("heading").filter(has_text=re.compile(r"summary", re.IGNORECASE))
    return heading.locator("xpath=ancestor::*[self::section or self::aside][1]")


def arranged_cart(page: Any, context: Any, api: httpx.Client, prefill_cart: Any) -> tuple[dict, dict]:
    products = catalogue(api)
    first, second = products[PRIMARY_ID], products[SECOND_ID]
    prefill_cart(context, [(PRIMARY_ID, 1), (SECOND_ID, SECOND_QUANTITY)])
    page.goto("/cart")
    return first, second


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


@pytest.mark.ac("WEB-005_AC-1")
@pytest.mark.parametrize("where", WHERE)
def test_ac_1_add_to_cart_sends_api_request(space_page, context, api, where: str) -> None:
    item = product(api, PRIMARY_ID)
    button = add_button(space_page, item, where)

    request = click_add(space_page, button)

    body = request.post_data_json
    assert isinstance(body, dict), f"the request body is not a JSON object: {request.post_data!r}"
    carried = {key: value for key, value in body.items() if "product" in key.lower() or key.lower() == "id"}
    assert str(item["id"]) in {str(value) for value in carried.values()}, (
        f"the request does not carry the product id {item['id']}: {body!r}"
    )
    assert request_session(request), "the request carries neither an X-Session-ID header nor a session_id cookie"


@pytest.mark.ac("WEB-005_AC-2")
@pytest.mark.parametrize("viewport", list(VIEWPORTS))
@pytest.mark.parametrize("where", WHERE)
def test_ac_2_cart_badge_updates(space_page, context, api, prefill_cart, where: str, viewport: str) -> None:
    space_page.set_viewport_size(VIEWPORTS[viewport])
    prefill_cart(context, [(SECOND_ID, SECOND_QUANTITY)])
    item = product(api, PRIMARY_ID)
    button = add_button(space_page, item, where)

    request = click_add(space_page, button)

    assert request.response().ok, f"the add request answered {request.response().status}"
    if viewport == "mobile":
        open_navigation_menu(space_page)
    badge = cart_badge(space_page).get_by_text(re.compile(rf"^\s*{SECOND_QUANTITY + 1}\s*$"))
    expect(badge).to_have_count(1)
    expect(badge).to_be_visible()


@pytest.mark.ac("WEB-005_AC-3")
def test_ac_3_cart_page_lists_items(space_page, context, api, prefill_cart) -> None:
    first, second = arranged_cart(space_page, context, api, prefill_cart)
    lines = cart_lines(space_page, [first["name"], second["name"]])

    for item, quantity in ((first, 1), (second, SECOND_QUANTITY)):
        line = lines[item["name"]]
        expect(line).to_be_visible()
        assert shows_quantity(line, quantity), f"the line of {item['name']!r} does not show the quantity {quantity}"
        unit = float(item["price"])
        expect(line).to_contain_text(money(unit))
        expect(line).to_contain_text(money(round(unit * quantity, 2)))


@pytest.mark.ac("WEB-005_AC-4")
def test_ac_4_cart_summary(space_page, context, api, prefill_cart) -> None:
    first, second = arranged_cart(space_page, context, api, prefill_cart)
    subtotal = money(round(float(first["price"]) + float(second["price"]) * SECOND_QUANTITY, 2))
    summary = cart_summary(space_page)
    expect(summary).to_have_count(1)
    expect(summary).to_be_visible()

    # Each label is a phrase contained in its label text ("Tax" matches "Estimated tax",
    # "Total" matches "Total due"), followed by its value before the next amount.
    text = norm(summary.inner_text())
    amount = re.escape(subtotal)
    label = r"[^$\d]{0,30}?"
    assert re.search(rf"subtotal{label}{amount}", text, re.IGNORECASE), f"no subtotal of {subtotal}: {text!r}"
    assert re.search(rf"shipping{label}complimentary", text, re.IGNORECASE), f"shipping is not 'Complimentary': {text!r}"
    assert re.search(rf"tax{label}calculated\s+at\s+checkout", text, re.IGNORECASE), (
        f"tax is not 'Calculated at checkout': {text!r}"
    )
    assert re.search(rf"(?<![a-z])total{label}{amount}", text, re.IGNORECASE), f"the total is not {subtotal}: {text!r}"


@pytest.mark.ac("WEB-005_AC-5")
def test_ac_5_proceed_to_checkout(space_page, context, api, prefill_cart) -> None:
    arranged_cart(space_page, context, api, prefill_cart)
    main = space_page.get_by_role("main")
    proceed = control(main, "link", "Proceed to Checkout").or_(control(main, "button", "Proceed to Checkout"))

    expect(proceed).to_have_count(1)
    expect(proceed).to_be_visible()
    proceed.click()
    expect(space_page).to_have_url(re.compile(r"^[^?#]*/checkout/?([?#].*)?$"))


@pytest.mark.ac("WEB-005_AC-6")
def test_ac_6_continue_shopping(space_page, context, api, prefill_cart) -> None:
    arranged_cart(space_page, context, api, prefill_cart)
    main = space_page.get_by_role("main")
    keep = control(main, "link", "Continue Shopping").or_(control(main, "button", "Continue Shopping"))

    expect(keep).to_have_count(1)
    expect(keep).to_be_visible()
    keep.click()
    expect(space_page).to_have_url(re.compile(r"^[^?#]*/products/?([?#].*)?$"))


@pytest.mark.ac("WEB-005_AC-7")
def test_ac_7_empty_cart_state(space_page, context, prefill_cart) -> None:
    prefill_cart(context, [])  # a fresh session with no items
    space_page.goto("/cart")
    main = space_page.get_by_role("main")

    expect(main.get_by_text(phrase("Your cart is still empty"))).to_be_visible()
    expect(control(main, "link", "Proceed to Checkout").or_(control(main, "button", "Proceed to Checkout"))).to_have_count(0)
    expect(main.get_by_text(phrase("Subtotal")).filter(visible=True)).to_have_count(0)
    browse = main.get_by_role("link").or_(main.get_by_role("button")).filter(
        has_text=re.compile(r"browse|shop|products|catalog", re.IGNORECASE)
    )
    expect(browse).to_have_count(1)
    expect(browse).to_be_visible()
    browse.click()
    expect(space_page).to_have_url(re.compile(r"^[^?#]*/products/?([?#].*)?$"))


def cart_of(api: httpx.Client, headers: dict[str, str]) -> dict[str, Any]:
    response = api.get("/api/cart/", headers=headers)
    assert response.status_code == 200, f"GET /api/cart/ answered {response.status_code}: {response.text[:200]}"
    return response.json()


def add_item(api: httpx.Client, headers: dict[str, str], product_id: int) -> dict[str, Any]:
    response = api.post("/api/cart/items", json={"product_id": product_id, "quantity": 1}, headers=headers)
    assert response.status_code == 200, f"POST /api/cart/items answered {response.status_code}: {response.text[:200]}"
    return response.json()


def product_ids(cart: dict[str, Any]) -> list[int]:
    return [int(line["product_id"]) for line in cart.get("items", [])]


@pytest.mark.ac("WEB-005_AC-10")
def test_ac_10_session_from_header(api) -> None:
    session = new_session()
    added = add_item(api, {SESSION_HEADER: session}, PRIMARY_ID)

    assert added.get("session") == session, f"the add response names the session {added.get('session')!r}"
    cart = cart_of(api, {SESSION_HEADER: session})
    assert cart.get("session") == session and product_ids(cart) == [PRIMARY_ID], f"the header's cart is {cart!r}"
    assert product_ids(cart_of(api, {SESSION_HEADER: new_session()})) == [], "another session sees the item"


@pytest.mark.ac("WEB-005_AC-10")
def test_ac_10_cookie_alone_uses_the_default_session(api) -> None:
    session = new_session()
    add_item(api, {SESSION_HEADER: session}, PRIMARY_ID)
    cookie = {"Cookie": f"{SESSION_COOKIE}={session}"}

    cart = cart_of(api, cookie)
    assert cart.get("session") == DEFAULT_SESSION, f"with the cookie alone the cart names the session {cart.get('session')!r}"
    assert product_ids(cart) == [], f"with the cookie alone the API returns the cookie's items: {cart!r}"
    added = add_item(api, cookie, SECOND_ID)
    assert added.get("session") == DEFAULT_SESSION, f"the add response names the session {added.get('session')!r}"
    assert product_ids(cart_of(api, {})) == [SECOND_ID], "the item added with the cookie alone is not in the default cart"
    assert product_ids(cart_of(api, {SESSION_HEADER: session})) == [PRIMARY_ID], "the cookie's own cart changed"


@pytest.mark.ac("WEB-005_AC-10")
def test_ac_10_session_defaults_to_workshop_demo(api) -> None:
    added = add_item(api, {}, PRIMARY_ID)

    assert added.get("session") == DEFAULT_SESSION, f"the add response names the session {added.get('session')!r}"
    cart = cart_of(api, {})
    assert cart.get("session") == DEFAULT_SESSION, f"the cart without identification is {cart!r}"
    assert product_ids(cart) == [PRIMARY_ID], f"the default cart holds {product_ids(cart)}"


@pytest.mark.ac("WEB-005_AC-10")
def test_ac_10_header_wins_over_cookie(api) -> None:
    header, cookie = new_session(), new_session()
    both = {SESSION_HEADER: header, "Cookie": f"{SESSION_COOKIE}={cookie}"}
    added = add_item(api, both, PRIMARY_ID)

    assert added.get("session") == header, f"the add response names the session {added.get('session')!r}"
    assert product_ids(cart_of(api, {SESSION_HEADER: header})) == [PRIMARY_ID], "the header's cart lacks the item"
    cart = cart_of(api, both)
    assert cart.get("session") == header, f"with both, the cart names the session {cart.get('session')!r}"


@pytest.mark.ac("WEB-005_AC-10")
def test_ac_10_pages_identify_the_cart_by_cookie(space_page, context, api, prefill_cart) -> None:
    item = product(api, PRIMARY_ID)
    prefill_cart(context, [(PRIMARY_ID, 1)])

    space_page.goto("/cart")

    expect(cart_lines(space_page, [item["name"]])[item["name"]]).to_be_visible()


@pytest.mark.ac("WEB-005_AC-9")
@pytest.mark.parametrize("where", WHERE)
def test_ac_9_duplicate_add_increments_quantity(space_page, context, api, prefill_cart, where: str) -> None:
    prefilled = prefill_cart(context, [(PRIMARY_ID, 1)])
    item = product(api, PRIMARY_ID)
    button = add_button(space_page, item, where)

    request = click_add(space_page, button)

    assert request.response().ok, f"the add request answered {request.response().status}"
    session = request_session(request) or cookie_session(context) or prefilled
    cart = cart_of(api, {SESSION_HEADER: session})
    lines = [line for line in cart["items"] if int(line["product_id"]) == PRIMARY_ID]
    assert len(lines) == 1, f"the cart has {len(lines)} lines for product {PRIMARY_ID}: {cart['items']!r}"
    assert int(lines[0]["quantity"]) == 2, f"the quantity is {lines[0]['quantity']}, expected 2"
    assert len(cart["items"]) == 1, f"a new line item was created: {cart['items']!r}"
