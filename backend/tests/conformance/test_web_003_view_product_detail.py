"""WEB-003 View Product Detail: conformance checks of AC-1 to AC-9.

Written from the story text, the index's interpretation rules and design D3
only. The primary test product is Aurora Neural Headphones (``/products/1``);
the edge cases are the last product (``/products/12``) and the unknown ids
``9999`` and ``abc``. Product data for data-driven assertions comes from
``GET /api/products/`` during arrange.

Scoping (design D3): the action area is the section that holds the ``h1`` with
the product name, which excludes the cards under "You might also like" and
"Trending in the studio". Related cards are the cards inside
``section(page, "You might also like")`` - never the three "Why you'll love it"
feature articles or the trending cards.
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
from playwright.sync_api import expect

from .conftest import SESSION_COOKIE, SESSION_HEADER
from .helpers import ConformanceSetupError, control, phrase, section

pytestmark = pytest.mark.conformance

PRIMARY_ID = 1
LAST_ID = 12
RELATED = "You might also like"
TRENDING = "Trending in the studio"
PRICE_TEXT = re.compile(r"\$\s?\d[\d,]*(\.\d{2})?")
NOT_FOUND = re.compile(r"not\s+found|does\s*n[o']t\s+exist|no\s+longer\s+available|\b404\b|could\s*n[o']t\s+find", re.IGNORECASE)


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


# ---------------------------------------------------------------------------
# Page helpers
# ---------------------------------------------------------------------------


def open_detail(page: Any, item: dict[str, Any]) -> Any:
    """Open the product's detail page; returns its action area (the section holding the h1)."""
    page.goto(f"/products/{item['id']}")
    title = page.get_by_role("heading", level=1)
    expect(title).to_have_count(1)
    expect(title).to_have_text(phrase(item["name"]))
    area = section(page, item["name"])
    expect(area).to_have_count(1)
    expect(area.get_by_role("heading", level=1)).to_be_visible()
    return area


def image_loaded(image: Any) -> bool:
    image.scroll_into_view_if_needed()
    expect(image).to_be_visible()
    for _ in range(25):
        if image.evaluate("el => el.complete && el.naturalWidth > 0"):
            return True
        image.page.wait_for_timeout(200)
    return False


def card_names(container: Any) -> list[str]:
    return [" ".join(text.split()) for text in container.get_by_role("article").get_by_role("heading").all_inner_texts()]


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


@pytest.mark.ac("WEB-003_AC-1")
@pytest.mark.parametrize("product_id", [PRIMARY_ID, LAST_ID])
def test_ac_1_core_information(space_page, api, product_id: int) -> None:
    item = product(api, product_id)
    area = open_detail(space_page, item)

    image = area.get_by_role("img").filter(visible=True)
    expect(image.first).to_be_visible()
    assert image_loaded(image.first), "the product image did not load"
    expect(area.get_by_text(item["category"], exact=True).filter(visible=True).first).to_be_visible()
    expect(area).to_contain_text(re.compile(re.escape(str(item["rating"]))))
    stars = area.get_by_role("img", name=re.compile(r"star", re.IGNORECASE)).or_(
        area.get_by_role("group", name=re.compile(r"star", re.IGNORECASE))
    ).or_(area.get_by_text(re.compile(r"[★☆]")))
    expect(stars.first).to_be_visible()
    expect(area).to_contain_text(re.compile(rf"\b{int(item['review_count'])}\b"))
    expect(area).to_contain_text(money(float(item["price"])))
    expect(area).to_contain_text(" ".join(str(item["description"]).split()))


@pytest.mark.ac("WEB-003_AC-2")
def test_ac_2_star_rating_accuracy(space_page, api) -> None:
    item = product(api, PRIMARY_ID)
    if (float(item["rating"]), int(item["review_count"])) != (4.8, 214):
        raise ConformanceSetupError(f"product 1 is rated {item['rating']} with {item['review_count']} reviews, not 4.8/214")
    area = open_detail(space_page, item)

    shown_as_text = area.get_by_text(re.compile(r"(?<![\d.])4\.8(?![\d])")).filter(visible=True)
    shown_as_name = area.get_by_role("img", name=re.compile(r"(?<![\d.])4\.8(?!\d)")).or_(
        area.get_by_role("group", name=re.compile(r"(?<![\d.])4\.8(?!\d)"))
    )
    assert shown_as_text.count() + shown_as_name.count() > 0, "the rating display does not show 4.8 stars"
    expect(area).to_contain_text(re.compile(r"214\s+reviews|\(\s*214\s*\)", re.IGNORECASE))


def data_identifies(attributes: dict[str, str], item: dict[str, Any]) -> bool:
    wanted = {str(item["id"]), str(item["name"]), str(item.get("sku", ""))} - {""}
    for value in attributes.values():
        if value.strip() in wanted:
            return True
        try:
            decoded = json.loads(value)
        except ValueError:
            continue
        if isinstance(decoded, dict) and str(decoded.get("id")) == str(item["id"]):
            return True
    return False


@pytest.mark.ac("WEB-003_AC-3")
def test_ac_3_add_to_cart_button(space_page, context, api) -> None:
    item = product(api, PRIMARY_ID)
    area = open_detail(space_page, item)
    button = control(area, "button", "Add to Cart")

    expect(button).to_have_count(1)
    expect(button).to_be_visible()
    data = button.evaluate("el => Object.fromEntries(Object.entries(el.dataset))")
    data_attributes = {name: str(value) for name, value in data.items()}
    assert data_identifies(data_attributes, item), f"no data attribute of the button identifies the product: {data_attributes}"

    def add_request(request: Any) -> bool:
        return request.method == "POST" and urlsplit(request.url).path.rstrip("/") == "/api/cart/items"

    with space_page.expect_request(add_request) as info:
        button.click()
    info.value.response()
    session_ids = [cookie["value"] for cookie in context.cookies() if cookie["name"] == SESSION_COOKIE]
    session_id = info.value.headers.get(SESSION_HEADER.lower()) or (session_ids[0] if session_ids else None)
    assert session_id, "the page has no session id to read its cart with"
    cart = api.get("/api/cart/", headers={SESSION_HEADER: session_id})
    assert cart.status_code == 200, cart.text
    added = [line["product_id"] for line in cart.json()["items"]]
    assert added == [item["id"]], f"the cart of the page's session holds {added}, expected [{item['id']}]"


@pytest.mark.ac("WEB-003_AC-4")
def test_ac_4_buy_now(space_page, api) -> None:
    item = product(api, PRIMARY_ID)
    area = open_detail(space_page, item)
    buy_now = area.get_by_role("link").or_(area.get_by_role("button")).filter(has_text=phrase("Buy Now"))

    expect(buy_now).to_have_count(1)
    expect(buy_now).to_be_visible()
    buy_now.click()
    expect(space_page).to_have_url(re.compile(r"^[^?#]*/checkout/?([?#].*)?$"))


@pytest.mark.ac("WEB-003_AC-5")
@pytest.mark.planted_bug("BUG_BROKEN_LINKS")
def test_ac_5_related_products_of_the_first_product(space_page, api) -> None:
    """``/products/1``: its related cards include products whose links the broken-links bug damages."""
    check_related_products(space_page, api, PRIMARY_ID)


@pytest.mark.ac("WEB-003_AC-5")
def test_ac_5_related_products_of_the_last_product(space_page, api) -> None:
    check_related_products(space_page, api, LAST_ID)


def check_related_products(space_page: Any, api: httpx.Client, product_id: int) -> None:
    products = catalogue(api)
    item = products[product_id]
    by_name = {entry["name"]: entry for entry in products.values()}
    same_category = {entry["name"] for entry in products.values() if entry["category"] == item["category"] and entry["id"] != product_id}
    open_detail(space_page, item)
    related = section(space_page, RELATED)
    related.scroll_into_view_if_needed()
    expect(related).to_be_visible()

    shown = card_names(related)
    assert 1 <= len(shown) <= 4, f"'You might also like' shows {len(shown)} products: {shown}"
    assert item["name"] not in shown, "the product recommends itself"
    unknown = [name for name in shown if name not in by_name]
    assert not unknown, f"related cards name unknown products: {unknown}"
    categories = [name in same_category for name in shown]
    assert categories == sorted(categories, reverse=True), f"same-category products are not shown first: {shown}"
    assert sum(categories) == min(len(same_category), len(shown)), f"same-category products are missing: {shown}"

    cards = related.get_by_role("article")
    for index in range(cards.count()):
        card = cards.nth(index)
        name = " ".join(card.get_by_role("heading").inner_text().split())
        links = card.get_by_role("link")
        assert links.count() >= 1, f"the related card of {name!r} has no link"
        for number in range(links.count()):
            href = links.nth(number).get_attribute("href")
            assert href, f"a link of the related card {name!r} has no target"
            response = space_page.request.get(href)
            assert response.status == 200, f"the link {href!r} of the related card {name!r} answered {response.status}"
            assert f"/products/{by_name[name]['id']}" == urlsplit(response.url).path.rstrip("/"), (
                f"the link {href!r} of the related card {name!r} does not lead to its detail page"
            )


@pytest.mark.ac("WEB-003_AC-6")
def test_ac_6_trending_in_the_studio(space_page, api) -> None:
    products = catalogue(api)
    item = products[PRIMARY_ID]
    names = {entry["name"] for entry in products.values()}
    open_detail(space_page, item)
    trending = section(space_page, TRENDING)
    trending.scroll_into_view_if_needed()
    expect(trending).to_be_visible()

    cards = trending.get_by_role("article")
    assert cards.count() >= 1, "'Trending in the studio' shows no product"
    for index in range(cards.count()):
        card = cards.nth(index)
        heading = card.get_by_role("heading")
        expect(heading).to_have_count(1)
        name = " ".join(heading.inner_text().split())
        assert name in names, f"a trending card names no catalogue product: {name!r}"
        expect(card).to_contain_text(PRICE_TEXT)
        image = card.get_by_role("img")
        expect(image.first).to_be_visible()
        assert image_loaded(image.first), f"the image of the trending card {name!r} did not load"


@pytest.mark.ac("WEB-003_AC-7")
def test_ac_7_product_highlights(space_page, api) -> None:
    open_detail(space_page, product(api, PRIMARY_ID))
    main = space_page.get_by_role("main")

    for label, pattern in (
        ("warranty", re.compile(r"warrant", re.IGNORECASE)),
        ("compatibility", re.compile(r"compatib", re.IGNORECASE)),
        ("impact or sustainability", re.compile(r"impact|sustainab", re.IGNORECASE)),
    ):
        item = main.get_by_text(pattern).filter(visible=True)
        assert item.count() >= 1, f"no visible {label} highlight"
        item.first.scroll_into_view_if_needed()
        expect(item.first).to_be_visible()


@pytest.mark.ac("WEB-003_AC-8")
def test_ac_8_back_button_returns_to_the_catalogue(space_page, api) -> None:
    item = product(api, PRIMARY_ID)
    space_page.goto("/products")
    grid = section(space_page, "All products")
    card = grid.get_by_role("article").filter(has=space_page.get_by_role("heading", name=item["name"]))
    expect(card).to_have_count(1)
    card.get_by_role("link", name=item["name"], exact=True).click()
    expect(space_page.get_by_role("heading", level=1)).to_have_text(phrase(item["name"]))

    space_page.go_back()

    expect(space_page).to_have_url(re.compile(r"/products/?([?#].*)?$"))
    expect(section(space_page, "All products").get_by_role("article").first).to_be_visible()


@pytest.mark.ac("WEB-003_AC-8")
def test_ac_8_navigation_link_returns_to_the_catalogue(space_page, api) -> None:
    open_detail(space_page, product(api, PRIMARY_ID))
    navigation = space_page.get_by_role("navigation")
    link = control(navigation, "link", "Products")
    expect(link.first).to_be_visible()

    link.first.click()

    expect(space_page).to_have_url(re.compile(r"/products/?([?#].*)?$"))
    expect(section(space_page, "All products").get_by_role("article").first).to_be_visible()


@pytest.mark.ac("WEB-003_AC-9")
@pytest.mark.parametrize("invalid_id", ["9999", "abc"])
def test_ac_9_invalid_product_id(space_page, api, invalid_id: str) -> None:
    if invalid_id.isdigit() and int(invalid_id) in catalogue(api):
        raise ConformanceSetupError(f"product {invalid_id} exists")

    response = space_page.goto(f"/products/{invalid_id}")

    assert response is not None
    content_type = response.headers.get("content-type", "")
    assert content_type.startswith("text/html"), f"the visitor gets a {content_type!r} response, not a page"
    message = space_page.get_by_text(NOT_FOUND).filter(visible=True)
    assert message.count() >= 1, "no visible not-found message"
    expect(message.first).to_be_visible()
    # No product detail page: no product title and no purchase actions of a product.
    names = [entry["name"] for entry in catalogue(api).values()]
    for title in space_page.get_by_role("heading", level=1).all_inner_texts():
        assert " ".join(title.split()) not in names, f"the page shows the detail title {title!r}"
    expect(control(space_page, "link", "Buy Now").or_(control(space_page, "button", "Buy Now"))).to_have_count(0)
