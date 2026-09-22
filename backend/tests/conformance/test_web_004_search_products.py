"""WEB-004 Search Products: conformance checks of the active criteria AC-1 to AC-3 and AC-5 to AC-9.

WEB-004_AC-4 is withdrawn (replaced by AC-9, an API check without stage variants).

Written from the story text, the index's interpretation rules and design D3
only. AC-1 checks the hero search on ``/``; the other UI checks run on
``/products`` with the test-data queries ``headphones``, ``aurora`` and
``xyz123``. The test data's parameter name ``q`` and its response shapes are
not normative: no criterion refers to them.

Scoping (design D3): result cards are the cards inside the results region
``get_by_role("region", name="Search results")``, never the "All products" grid
or the "Collections to explore" previews, which stay rendered on
``/products``. Network criteria use ``page.expect_request`` with a predicate
that matches the path exactly, so ``/api/search/suggest`` cannot satisfy a
criterion about ``/api/search``.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect

from .helpers import ConformanceSetupError, control, phrase, section

pytestmark = pytest.mark.conformance

PRIMARY = "Aurora Neural Headphones"
NO_MATCH = "xyz123"
PRICE_TEXT = re.compile(r"\$\s?\d[\d,]*(\.\d{2})?")
REQUEST_TIMEOUT_MS = 5000


# ---------------------------------------------------------------------------
# Arrange helpers
# ---------------------------------------------------------------------------


def catalogue(api: httpx.Client) -> dict[str, dict[str, Any]]:
    """The products of ``GET /api/products/`` by name (arrange data)."""
    response = api.get("/api/products/")
    if response.status_code != 200:
        raise ConformanceSetupError(f"GET /api/products/ answered {response.status_code}: {response.text[:200]!r}")
    items = response.json().get("items")
    if not isinstance(items, list) or not items:
        raise ConformanceSetupError("GET /api/products/ returned no product list")
    return {item["name"]: item for item in items}


def matches(product: dict[str, Any], query: str) -> bool:
    """Whether ``query`` occurs in the product's name, description or category."""
    text = " ".join(str(product.get(field) or "") for field in ("name", "description", "category"))
    return query.lower() in text.lower()


def path_is(url: str, path: str) -> bool:
    return urlsplit(url).path.rstrip("/") == path.rstrip("/")


def carries(url: str, value: str) -> bool:
    return any(item == value for _, item in parse_qsl(urlsplit(url).query))


# ---------------------------------------------------------------------------
# Page helpers
# ---------------------------------------------------------------------------


def search_input(page: Any) -> Any:
    box = page.get_by_role("searchbox").filter(visible=True)
    expect(box).to_have_count(1)
    return box


def results_region(page: Any) -> Any:
    return page.get_by_role("region", name="Search results")


def submit_search(page: Any, query: str, *, by_button: bool = False) -> Any:
    box = search_input(page)
    box.fill(query)
    if by_button:
        form = page.get_by_role("search").filter(has=box)
        control(form, "button", "Search").click()
    else:
        box.press("Enter")
    region = results_region(page)
    expect(region).to_be_visible()
    settle(region)
    return region


def settle(region: Any, quiet_ms: int = 800, limit_ms: int = 8000) -> None:
    """Wait until the results stop changing.

    The shop also searches while the shopper types, so a submitted query can
    render its results more than once; the checks read the final render.
    """
    page = region.page
    last = region.inner_html()
    quiet = waited = 0
    while quiet < quiet_ms and waited < limit_ms:
        page.wait_for_timeout(200)
        waited += 200
        current = region.inner_html()
        quiet = quiet + 200 if current == last else 0
        last = current


def result_names(region: Any) -> list[str]:
    return [" ".join(text.split()) for text in region.get_by_role("article").get_by_role("heading").all_inner_texts()]


def image_loaded(image: Any) -> bool:
    image.scroll_into_view_if_needed()
    for _ in range(25):
        if image.evaluate("el => el.complete && el.naturalWidth > 0"):
            return True
        image.page.wait_for_timeout(200)
    return False


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


@pytest.mark.ac("WEB-004_AC-1")
def test_ac_1_search_form_on_the_home_page(space_page) -> None:
    space_page.goto("/")
    hero = space_page.get_by_role("heading", level=1).locator("xpath=ancestor::section[1]")
    expect(hero).to_have_count(1)
    box = hero.get_by_role("searchbox")

    expect(box).to_have_count(1)
    expect(box).to_be_visible()
    purpose = re.compile(r"search|find", re.IGNORECASE)
    labelled = hero.get_by_role("searchbox", name=purpose).or_(hero.get_by_placeholder(purpose))
    expect(labelled.first).to_be_visible()


@pytest.mark.ac("WEB-004_AC-2")
def test_ac_2_search_form_on_the_products_page(space_page) -> None:
    space_page.goto("/products")

    expect(search_input(space_page)).to_be_visible()


@pytest.mark.ac("WEB-004_AC-3")
@pytest.mark.parametrize(("query", "by_button"), [("headphones", False), ("aurora", True)])
def test_ac_3_search_submission_shows_results(space_page, api, query: str, by_button: bool) -> None:
    products = catalogue(api)
    if PRIMARY not in products or not matches(products[PRIMARY], query):
        raise ConformanceSetupError(f"{PRIMARY} does not match {query!r} in the catalogue")
    space_page.goto("/products")

    region = submit_search(space_page, query, by_button=by_button)

    cards = region.get_by_role("article")
    expect(cards.filter(has=space_page.get_by_role("heading", name=PRIMARY))).to_have_count(1)
    shown = result_names(region)
    unrelated = [name for name in shown if name not in products or not matches(products[name], query)]
    assert not unrelated, f"results for {query!r} show products that do not match it: {unrelated}"
    for index in range(cards.count()):
        card = cards.nth(index)
        expect(card.get_by_role("heading")).to_have_count(1)
        expect(card.get_by_role("img").first).to_be_visible()
        expect(card).to_contain_text(PRICE_TEXT)


@pytest.mark.ac("WEB-004_AC-5")
def test_ac_5_autocomplete_suggestions(space_page) -> None:
    space_page.goto("/products")
    box = search_input(space_page)
    box.click()

    try:
        with space_page.expect_request(
            lambda request: path_is(request.url, "/api/search/suggest"), timeout=REQUEST_TIMEOUT_MS
        ):
            box.press_sequentially("aur", delay=120)
    except PlaywrightTimeoutError:
        raise AssertionError("typing in the search input sent no request to /api/search/suggest") from None

    form = space_page.get_by_role("search").filter(has=box)
    suggestions = form.get_by_role("listbox").or_(form.get_by_role("list")).filter(visible=True)
    expect(suggestions).to_have_count(1)
    expect(suggestions.get_by_role("option").or_(suggestions.get_by_role("listitem")).first).to_be_visible()
    field, listing = box.bounding_box(), suggestions.bounding_box()
    assert field and listing and listing["y"] >= field["y"] + field["height"] - 2, "the suggestions are not below the input"


@pytest.mark.ac("WEB-004_AC-6")
@pytest.mark.parametrize("path", ["/products", "/"])
def test_ac_6_clear_search_results(space_page, path: str) -> None:
    space_page.goto(path)
    region = submit_search(space_page, "headphones")
    expect(region.get_by_role("article").first).to_be_visible()

    clear = (
        control(space_page, "button", "Clear search")
        .or_(control(space_page, "button", "Clear results"))
        .filter(visible=True)
    )
    expect(clear).to_have_count(1)
    clear.click()

    expect(results_region(space_page)).to_be_hidden()
    if path == "/products":
        expect(section(space_page, "All products").get_by_role("article").first).to_be_visible()
    else:
        expect(space_page.get_by_role("heading", level=1)).to_be_visible()
    expect(search_input(space_page)).to_have_value("")


@pytest.mark.ac("WEB-004_AC-7")
def test_ac_7_empty_state(space_page, api) -> None:
    if any(matches(product, NO_MATCH) for product in catalogue(api).values()):
        raise ConformanceSetupError(f"a product matches {NO_MATCH!r}")
    space_page.goto("/products")

    region = submit_search(space_page, NO_MATCH)

    expect(region.get_by_role("article")).to_have_count(0)
    message = region.get_by_text(re.compile(r"\bno\b[^.]*\b(products?|results?|matches|items?)\b", re.IGNORECASE))
    expect(message).to_be_visible()


@pytest.mark.ac("WEB-004_AC-8")
@pytest.mark.parametrize("query", ["headphones", "aurora"])
def test_ac_8_results_are_product_cards(space_page, api, query: str) -> None:
    products = catalogue(api)
    space_page.goto("/products")

    region = submit_search(space_page, query)

    cards = region.get_by_role("article")
    expect(cards.first).to_be_visible()
    for index in range(cards.count()):
        card = cards.nth(index)
        heading = card.get_by_role("heading")
        expect(heading).to_have_count(1)
        name = " ".join(heading.inner_text().split())
        assert name in products, f"a result card names no catalogue product: {name!r}"
        expect(card).to_contain_text(PRICE_TEXT)
        image = card.get_by_role("img").first
        expect(image).to_be_visible()
        assert image_loaded(image), f"the image of the result card {name!r} did not load"
        button = control(card, "button", "Add to Cart")
        expect(button).to_have_count(1)
        expect(button).to_be_visible()
        detail = f"/products/{products[name]['id']}"
        links = card.get_by_role("link")
        targets = [links.nth(number).get_attribute("href") or "" for number in range(links.count())]
        assert any(path_is(target, detail) for target in targets), f"the result card {name!r} links to {targets}, not {detail}"
        response = space_page.request.get(detail)
        assert response.status == 200, f"{detail} answered {response.status}"
        assert phrase(name).search(response.text()), f"{detail} does not show {name!r}"


def listed_names(body: Any) -> list[str]:
    """The names of the product objects anywhere in a JSON response."""
    if isinstance(body, dict):
        own = [str(body["name"])] if "name" in body and ("id" in body or "price" in body) else []
        return own + [name for value in body.values() for name in listed_names(value)]
    if isinstance(body, list):
        return [name for value in body for name in listed_names(value)]
    return []


@pytest.mark.ac("WEB-004_AC-9")
@pytest.mark.parametrize(("query", "expected"), [("headphones", PRIMARY), ("aurora", PRIMARY), (NO_MATCH, None)])
def test_ac_9_search_via_api(api, query: str, expected: str | None) -> None:
    products = catalogue(api)

    response = api.get("/api/search/", params={"query": query})

    assert response.status_code == 200, f"GET /api/search/?query={query} answered {response.status_code}"
    names = listed_names(response.json())
    unrelated = [name for name in names if name not in products or not matches(products[name], query)]
    assert not unrelated, f"the search API lists products that do not match {query!r}: {unrelated}"
    if expected is None:
        assert names == [], f"the search API lists {names} for {query!r}, which matches no product"
    else:
        assert expected in names, f"the search API does not list {expected} for {query!r}: {names}"
