"""WEB-002 Browse Product Catalogue: conformance checks of AC-1 to AC-13.

Written from the story text, the index's interpretation rules and design D3
only. Every check runs on ``/products`` through the rendered page; expected
product sets come from ``GET /api/products/`` during arrange.

Scoping (design Context and D3): the catalogue cards are the cards inside
``section(page, "All products")``. The mini preview cards under "Collections to
explore" and the search-results region repeat products and are outside every
card assertion here; nothing resolves articles at page level.
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable
from typing import Any

import httpx
import pytest
from playwright.sync_api import expect

from .helpers import ConformanceSetupError, control, phrase, section

pytestmark = pytest.mark.conformance

GRID = "All products"
COLLECTIONS = "Collections to explore"
HIGHLIGHTS = "Handpicked highlights"
SEED_PRODUCTS = 12
SEED_CATEGORIES = 9
LOWEST_PRICE = 39.50
HIGHEST_PRICE = 899.00
POLL_SECONDS = 5.0

PRICE_TEXT = re.compile(r"\$\s?\d[\d,]*(\.\d{2})?")
AMOUNT = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)")


# ---------------------------------------------------------------------------
# Arrange helpers
# ---------------------------------------------------------------------------


def catalogue(api: httpx.Client) -> list[dict[str, Any]]:
    """The products of ``GET /api/products/`` (arrange data, never asserted)."""
    response = api.get("/api/products/")
    if response.status_code != 200:
        raise ConformanceSetupError(f"GET /api/products/ answered {response.status_code}: {response.text[:200]!r}")
    body = response.json()
    items = body.get("items") if isinstance(body, dict) else body
    if not isinstance(items, list) or not items:
        raise ConformanceSetupError(f"GET /api/products/ returned no product list: {str(body)[:200]!r}")
    return items


def names(products: Iterable[dict[str, Any]]) -> set[str]:
    return {product["name"] for product in products}


def in_range(product: dict[str, Any], low: float, high: float) -> bool:
    return low <= float(product["price"]) <= high


def open_catalogue(page: Any) -> Any:
    page.goto("/products")
    grid = section(page, GRID)
    expect(grid).to_be_visible()
    return grid


# ---------------------------------------------------------------------------
# Page helpers
# ---------------------------------------------------------------------------


def grid_names(grid: Any) -> list[str]:
    """The product names of the catalogue cards, in display order."""
    return [text.strip() for text in grid.get_by_role("article").get_by_role("heading").all_inner_texts()]


def poll(read: Callable[[], Any], wanted: Callable[[Any], bool]) -> Any:
    """Re-read until ``wanted`` holds or the poll time is over; return the last value."""
    deadline = time.monotonic() + POLL_SECONDS
    value = read()
    while not wanted(value) and time.monotonic() < deadline:
        time.sleep(0.2)
        value = read()
    return value


def assert_grid_shows(page: Any, expected: set[str]) -> None:
    """The catalogue grid shows exactly the ``expected`` products."""
    page.wait_for_load_state()
    grid = section(page, GRID)
    shown = poll(lambda: grid_names(grid), lambda value: set(value) == expected and len(value) == len(expected))
    assert sorted(shown) == sorted(expected), f"grid shows {sorted(shown)}, expected {sorted(expected)}"


def category_group(page: Any) -> Any:
    group = control(page, "group", "Categories")
    expect(group).to_have_count(1)
    expect(group).to_be_visible()
    return group


def price_group(page: Any) -> Any:
    group = control(page, "group", "Price range")
    expect(group).to_have_count(1)
    expect(group).to_be_visible()
    return group


def sliders(page: Any) -> tuple[Any, Any]:
    group = price_group(page)
    low = group.get_by_role("slider", name="Minimum price")
    high = group.get_by_role("slider", name="Maximum price")
    expect(low).to_be_visible()
    expect(high).to_be_visible()
    return low, high


def slider_value(slider: Any) -> float:
    return float(slider.input_value())


def check_category(page: Any, category: str) -> None:
    """Check the category checkbox found by its label (the criterion quotes the category)."""
    box = page.get_by_role("checkbox", name=category, exact=True)
    expect(box).to_have_count(1)
    expect(box).to_be_visible()
    box.check()
    expect(box).to_be_checked()


def apply_filters(page: Any) -> None:
    button = control(page, "button", "Apply filters")
    expect(button).to_be_visible()
    button.click()
    page.wait_for_load_state()


def money(value: float) -> re.Pattern[str]:
    """A displayed dollar amount for ``value``: ``$100``, ``$100.00`` or ``$39.50``."""
    whole, cents = f"{value:.2f}".split(".")
    tail = r"(\.00)?" if cents == "00" else rf"\.{cents[0]}{cents[1]}?" if cents[1] == "0" else rf"\.{cents}"
    return re.compile(rf"\$\s?{whole}{tail}(?![\d.,])")


def amounts(text: str) -> list[float]:
    """Every dollar amount in ``text``, in order."""
    return [float(value.replace(",", "")) for value in AMOUNT.findall(text)]


def image_loaded(image: Any) -> bool:
    image.scroll_into_view_if_needed()
    return bool(
        poll(
            lambda: image.evaluate("el => el.complete && el.naturalWidth > 0"),
            bool,
        )
    )


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


@pytest.mark.ac("WEB-002_AC-1")
@pytest.mark.planted_bug("BUG_MISSING_BUTTON")
def test_ac_1_full_product_grid(space_page, api) -> None:
    products = catalogue(api)
    grid = open_catalogue(space_page)
    cards = grid.get_by_role("article")

    expect(cards).to_have_count(SEED_PRODUCTS)
    assert sorted(grid_names(grid)) == sorted(names(products))
    for index in range(SEED_PRODUCTS):
        card = cards.nth(index)
        name = card.get_by_role("heading")
        expect(name).to_have_count(1)
        expect(name).to_be_visible()
        image = card.get_by_role("img")
        expect(image.first).to_be_visible()
        assert image_loaded(image.first), f"the image of card {name.inner_text()!r} did not load"
        expect(card).to_contain_text(PRICE_TEXT)
        button = control(card, "button", "Add to Cart")
        expect(button).to_have_count(1)
        expect(button).to_be_visible()

    # A grid layout: at a desktop viewport, several cards share the first row.
    boxes = [cards.nth(index).bounding_box() for index in range(SEED_PRODUCTS)]
    first_row = [box for box in boxes if box and abs(box["y"] - boxes[0]["y"]) < 2]
    assert len(first_row) >= 2, "the catalogue cards are stacked in one column, not laid out in a grid"


@pytest.mark.ac("WEB-002_AC-1")
@pytest.mark.planted_bug("BUG_WRONG_PRICE")
def test_ac_1_card_prices_are_the_product_prices(space_page, api) -> None:
    """The clarified "price": every catalogue card shows its product's price and no other."""
    price_of = {product["name"]: float(product["price"]) for product in catalogue(api)}
    grid = open_catalogue(space_page)
    cards = grid.get_by_role("article")
    expect(cards).to_have_count(SEED_PRODUCTS)

    wrong: dict[str, list[float]] = {}
    for index in range(SEED_PRODUCTS):
        card = cards.nth(index)
        name = " ".join(card.get_by_role("heading").inner_text().split())
        assert name in price_of, f"a catalogue card names no catalogue product: {name!r}"
        shown = amounts(card.inner_text())
        if not shown or any(abs(value - price_of[name]) > 0.005 for value in shown):
            wrong[name] = shown
    assert not wrong, "cards that do not show their product's price: " + ", ".join(
        f"{name} shows {shown}, the product costs {price_of[name]:.2f}" for name, shown in sorted(wrong.items())
    )


@pytest.mark.ac("WEB-002_AC-2")
def test_ac_2_category_filter_checkboxes(space_page, api) -> None:
    categories = sorted({product["category"] for product in catalogue(api)})
    if len(categories) != SEED_CATEGORIES:
        raise ConformanceSetupError(f"the seed data holds {len(categories)} categories, the story expects 9")
    open_catalogue(space_page)
    group = category_group(space_page)

    expect(group.get_by_role("checkbox")).to_have_count(SEED_CATEGORIES)
    for category in categories:
        box = group.get_by_role("checkbox", name=category)
        expect(box).to_have_count(1)
        expect(box).to_be_visible()
        expect(box).not_to_be_checked()


@pytest.mark.ac("WEB-002_AC-3")
def test_ac_3_price_range_filter(space_page, api) -> None:
    prices = [float(product["price"]) for product in catalogue(api)]
    if (min(prices), max(prices)) != (LOWEST_PRICE, HIGHEST_PRICE):
        raise ConformanceSetupError(f"seed prices span {min(prices)}-{max(prices)}, the story expects 39.50-899.00")
    open_catalogue(space_page)
    group = price_group(space_page)
    low, high = sliders(space_page)

    assert slider_value(low) == LOWEST_PRICE, f"the minimum handle starts at {low.input_value()}, not 39.50"
    assert slider_value(high) == HIGHEST_PRICE, f"the maximum handle starts at {high.input_value()}, not 899.00"
    assert float(low.evaluate("el => el.min")) == LOWEST_PRICE, "the slider's lowest value is not 39.50"
    assert float(high.evaluate("el => el.max")) == HIGHEST_PRICE, "the slider's highest value is not 899.00"
    expect(group).to_contain_text(money(LOWEST_PRICE))
    expect(group).to_contain_text(money(HIGHEST_PRICE))


@pytest.mark.ac("WEB-002_AC-4")
def test_ac_4_rating_filter(space_page) -> None:
    open_catalogue(space_page)
    box = space_page.get_by_label(phrase("4 stars & up"))

    expect(box).to_have_count(1)
    expect(box).to_be_visible()
    expect(box).to_have_attribute("type", "checkbox")
    expect(box).not_to_be_checked()


@pytest.mark.ac("WEB-002_AC-5")
def test_ac_5_availability_filter(space_page) -> None:
    open_catalogue(space_page)
    box = space_page.get_by_label(phrase("Show in-stock only"))

    expect(box).to_have_count(1)
    expect(box).to_be_visible()
    expect(box).to_have_attribute("type", "checkbox")
    expect(box).not_to_be_checked()


@pytest.mark.ac("WEB-002_AC-6")
def test_ac_6_apply_filters_updates_the_list(space_page, api) -> None:
    products = catalogue(api)
    # The category of the lowest-priced product, plus the rating and stock filters.
    category = min(products, key=lambda product: float(product["price"]))["category"]
    expected = names(
        product
        for product in products
        if product["category"] == category and float(product["rating"]) >= 4 and int(product["inventory"]) > 0
    )
    if not expected or len(expected) == SEED_PRODUCTS:
        raise ConformanceSetupError(f"the filters on {category!r} do not narrow the catalogue: {sorted(expected)}")
    open_catalogue(space_page)

    check_category(space_page, category)
    space_page.get_by_label(phrase("4 stars & up")).check()
    space_page.get_by_label(phrase("Show in-stock only")).check()
    apply_filters(space_page)

    assert_grid_shows(space_page, expected)
    # DELIBERATELY DRIFT-FRAGILE - workshop-rollout task 4.2 gate rehearsal.
    # `product-card` is the stage-1 class name; stage 2 renames the block to
    # `item-card` and stage 4 to `product-tile`, while stage 3 keeps it. So
    # [clean] and [stage3] pass while [stage2], [stage4] and [drift_and_bug]
    # fail. Never merge this branch.
    expect(space_page.locator("css=.product-card")).to_have_count(len(expected))
    count = re.compile(rf"(?<![\d.,$]){len(expected)}\s+(products?|items?|results?)\b", re.IGNORECASE)
    expect(space_page.get_by_text(count)).to_be_visible()


@pytest.mark.ac("WEB-002_AC-7")
def test_ac_7_category_filter(space_page, api) -> None:
    expected = names(product for product in catalogue(api) if product["category"] == "Audio")
    if not expected:
        raise ConformanceSetupError("the seed data holds no Audio product")
    open_catalogue(space_page)

    check_category(space_page, "Audio")
    apply_filters(space_page)

    assert_grid_shows(space_page, expected)


@pytest.mark.ac("WEB-002_AC-8")
def test_ac_8_price_range_filter(space_page, api) -> None:
    expected = names(product for product in catalogue(api) if in_range(product, 100, 300))
    open_catalogue(space_page)
    group = price_group(space_page)
    low, high = sliders(space_page)

    low.fill("100")
    high.fill("300")
    expect(group).to_contain_text(money(100))
    expect(group).to_contain_text(money(300))
    apply_filters(space_page)

    assert_grid_shows(space_page, expected)


@pytest.mark.ac("WEB-002_AC-9")
def test_ac_9_category_and_price_range(space_page, api) -> None:
    products = catalogue(api)
    # A category with products both inside and outside $100-$300, so each filter hides something.
    category = next(
        (
            category
            for category in sorted({product["category"] for product in products})
            if {in_range(product, 100, 300) for product in products if product["category"] == category} == {True, False}
        ),
        None,
    )
    if category is None:
        raise ConformanceSetupError("no category has products both inside and outside $100-$300")
    expected = names(product for product in products if product["category"] == category and in_range(product, 100, 300))
    open_catalogue(space_page)
    low, high = sliders(space_page)

    check_category(space_page, category)
    low.fill("100")
    high.fill("300")
    apply_filters(space_page)

    assert_grid_shows(space_page, expected)


@pytest.mark.ac("WEB-002_AC-9")
def test_ac_9_category_and_upper_price_bound(space_page, api) -> None:
    """The minimum handle stays at its default, the lowest product price."""
    products = catalogue(api)
    cheapest = min(products, key=lambda product: float(product["price"]))
    category = cheapest["category"]
    ceiling = 50
    expected = names(product for product in products if product["category"] == category and float(product["price"]) <= ceiling)
    if cheapest["name"] not in expected or len(expected) == len([p for p in products if p["category"] == category]):
        raise ConformanceSetupError(f"category {category!r} and a ${ceiling} ceiling do not form an intersection")
    open_catalogue(space_page)
    _, high = sliders(space_page)

    check_category(space_page, category)
    high.fill(str(ceiling))
    apply_filters(space_page)

    assert_grid_shows(space_page, expected)


@pytest.mark.ac("WEB-002_AC-10")
def test_ac_10_reset_filters(space_page, api) -> None:
    products = catalogue(api)
    open_catalogue(space_page)
    low, high = sliders(space_page)
    defaults = (slider_value(low), slider_value(high))

    check_category(space_page, "Audio")
    space_page.get_by_label(phrase("4 stars & up")).check()
    space_page.get_by_label(phrase("Show in-stock only")).check()
    low.fill("100")
    high.fill("300")
    apply_filters(space_page)
    expect(section(space_page, GRID).get_by_role("article")).not_to_have_count(SEED_PRODUCTS)

    reset = control(space_page, "link", "Reset")
    expect(reset).to_have_count(1)
    expect(reset).to_be_visible()
    reset.click()
    space_page.wait_for_load_state()

    boxes = space_page.get_by_role("checkbox")
    for index in range(boxes.count()):
        expect(boxes.nth(index)).not_to_be_checked()
    low, high = sliders(space_page)
    assert (slider_value(low), slider_value(high)) == defaults
    assert_grid_shows(space_page, names(products))


@pytest.mark.ac("WEB-002_AC-11")
def test_ac_11_collections_to_explore(space_page, api) -> None:
    products = catalogue(api)
    category_of = {product["name"]: product["category"] for product in products}
    open_catalogue(space_page)
    collections = section(space_page, COLLECTIONS)
    collections.scroll_into_view_if_needed()
    expect(collections).to_be_visible()

    previews = 0
    for category in sorted(set(category_of.values())):
        # A category preview: the category's name outside any product card, with the cards shown for it.
        labels = collections.get_by_text(category, exact=True)
        for index in range(labels.count()):
            label = labels.nth(index)
            if label.evaluate("el => el.closest('article') !== null"):
                continue
            previews += 1
            preview = label.locator("xpath=ancestor::*[.//article][1]")
            shown = [text.strip() for text in preview.get_by_role("article").get_by_role("heading").all_inner_texts()]
            assert 1 <= len(shown) <= 3, f"the {category} preview shows {len(shown)} products: {shown}"
            others = [name for name in shown if category_of.get(name) != category]
            assert not others, f"the {category} preview shows products of other categories: {others}"
    assert previews >= 1, "no category preview is displayed under 'Collections to explore'"


@pytest.mark.ac("WEB-002_AC-12")
def test_ac_12_handpicked_highlights(space_page, api) -> None:
    products = catalogue(api)
    ranked = sorted(products, key=lambda product: float(product["price"]), reverse=True)
    top = [product["name"] for product in ranked[:3]]
    others = [product["name"] for product in ranked[3:]]
    open_catalogue(space_page)
    highlights = section(space_page, HIGHLIGHTS)
    expect(highlights).to_be_visible()

    text = " ".join(highlights.inner_text().split())
    positions = [text.find(name) for name in top]
    assert all(position >= 0 for position in positions), f"highlights miss some of {top}: {text!r}"
    assert positions == sorted(positions), f"highlights are not ordered by price, highest first: {text!r}"
    shown_others = [name for name in others if name in text]
    assert not shown_others, f"highlights show products outside the top 3 by price: {shown_others}"


@pytest.mark.ac("WEB-002_AC-13")
def test_ac_13_empty_state(space_page, api) -> None:
    products = catalogue(api)
    if any(product["category"] == "Audio" and in_range(product, 100, 200) for product in products):
        raise ConformanceSetupError("an Audio product costs $100-$200, so the filters would not match zero products")
    open_catalogue(space_page)
    low, high = sliders(space_page)

    check_category(space_page, "Audio")
    low.fill("100")
    high.fill("200")
    apply_filters(space_page)

    grid = section(space_page, GRID)
    expect(grid.get_by_role("article")).to_have_count(0)
    # The message belongs to the grid it replaces; hidden text elsewhere on the page does not count.
    message = grid.get_by_text(re.compile(r"\bno\b[^.]*\b(products?|results?|items?|matches)\b", re.IGNORECASE))
    expect(message).to_be_visible()
    suggestion = grid.get_by_text(re.compile(r"\b(adjust|reset|clear|chang|broaden|widen|remov)\w*\b[^.]*\bfilter", re.IGNORECASE))
    expect(suggestion).to_be_visible()
