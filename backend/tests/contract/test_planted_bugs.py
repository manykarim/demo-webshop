"""The planted catalogue bugs (tasks 11.1, 11.2 and 14.4).

`BUG_SLOW_RESPONSE` first: the delay is a dependency,
`core.workshop.planted_delay("catalogue")`, attached to exactly the two
catalogue responses the registry names - the `/products` page and
`GET /api/products/` - and to nothing else (design Decision 11). The first test
records what the app sleeps with `asyncio.sleep` patched, so the whole matrix of
routes is checked in milliseconds; the second one lets the shop really sleep,
which is what the spec's "Slow catalogue" scenario describes.

Then the three catalogue defects that damage a rendered card -
`BUG_MISSING_BUTTON`, `BUG_WRONG_PRICE` and `BUG_BROKEN_LINKS` - each repeated
in stages 1 to 4, because a planted bug behaves identically in every stage.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator

import pytest
from bs4 import Tag

from backend.app.core.workshop import STAGES, WRONG_PRICE_FACTOR

from .conftest import STAGE_FLAGS
from .hooks import matches, soup_of
from .semantic import normalize_text, visible_text

#: The planted bug under test.
SLOW_RESPONSE_BUG = "BUG_SLOW_RESPONSE"

#: The two responses the registry delays.
DELAYED_PATHS: tuple[str, ...] = ("/products", "/api/products/")

#: Everything else a shopper touches, none of which may be delayed.
UNDELAYED_PATHS: tuple[str, ...] = (
    "/",
    "/products/3",
    "/cart",
    "/checkout",
    "/api/cart/",
    "/search/results?query=desk",
)


@pytest.fixture
def recorded_sleeps(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[float]]:
    """Record every `asyncio.sleep` of the app and return at once.

    The patch is installed on the `asyncio` module itself, which is the object
    `core/workshop.py` reaches `sleep` through, and is undone by `monkeypatch`
    after the test.
    """
    durations: list[float] = []
    real_sleep = asyncio.sleep

    async def recording_sleep(delay: float, *args, **kwargs):
        durations.append(delay)
        return await real_sleep(0, *args, **kwargs)

    monkeypatch.setattr(asyncio, "sleep", recording_sleep)
    yield durations


@pytest.mark.parametrize("path", DELAYED_PATHS)
def test_the_catalogue_responses_are_delayed(render, recorded_sleeps, path: str) -> None:
    """One sleep of 1 to 3 seconds, on the two catalogue responses."""
    response = render(path, {SLOW_RESPONSE_BUG: True})

    assert response.status_code == 200
    assert len(recorded_sleeps) == 1, recorded_sleeps
    assert 1.0 <= recorded_sleeps[0] <= 3.0


@pytest.mark.parametrize("path", UNDELAYED_PATHS)
def test_no_other_response_is_delayed(render, recorded_sleeps, path: str) -> None:
    """Every other response the shop serves is untouched."""
    response = render(path, {SLOW_RESPONSE_BUG: True})

    assert response.status_code == 200
    assert recorded_sleeps == []


@pytest.mark.parametrize("path", DELAYED_PATHS)
def test_the_catalogue_is_not_delayed_without_the_bug(
    render, recorded_sleeps, path: str
) -> None:
    """With the flag off, the dependency sleeps not at all."""
    response = render(path, {})

    assert response.status_code == 200
    assert recorded_sleeps == []


def test_slow_catalogue(render) -> None:
    """Spec scenario "Slow catalogue", with the real delay.

    `/products` takes at least a second; the `/cart` request that follows it is
    served at once.
    """
    started = time.perf_counter()
    products = render("/products", {SLOW_RESPONSE_BUG: True})
    products_seconds = time.perf_counter() - started

    started = time.perf_counter()
    cart = render("/cart", {SLOW_RESPONSE_BUG: True})
    cart_seconds = time.perf_counter() - started

    assert products.status_code == 200
    assert cart.status_code == 200
    assert products_seconds >= 1.0, products_seconds
    assert cart_seconds < 1.0, cart_seconds


# ---------------------------------------------------------------------------
# The catalogue scenarios (task 14.4), repeated in stages 1 to 4
# ---------------------------------------------------------------------------
#
# The three catalogue defects damage the *card* and nothing else, so each of
# them is read off a rendered card and then contradicted somewhere the real
# value survives: the cart, the checkout summary, the created order, or the
# product page the broken link points at.
#
# Cards are located by the product's own heading text and their action by role
# and visible text, never by a hook, which is what lets the same assertions run
# in stages 1 to 4. `/products` renders a product more than once - the listing
# grid and the category previews above it - so every assertion is made over
# *every* card of that product, and the counts are compared with the render
# that has the flag off, so a scenario cannot pass because a card disappeared.

MISSING_BUTTON_BUG = "BUG_MISSING_BUTTON"
WRONG_PRICE_BUG = "BUG_WRONG_PRICE"
BROKEN_LINKS_BUG = "BUG_BROKEN_LINKS"

#: The three products the registry's triggers single out, by SKU. Their ids are
#: asserted below rather than hard-coded here.
MISSING_BUTTON_SKU = "ATL-DSK-005"  # id % 5 == 0
WRONG_PRICE_SKU = "PUL-RNG-003"  # id % 3 == 0
BROKEN_LINK_SKU = "NIM-LGT-004"  # id % 4 == 0

#: The visible text of every card action, in every stage.
ADD_TO_CART = "Add to cart"


@pytest.fixture(scope="module")
def catalogue(contract_client) -> dict[str, dict]:
    """The seeded catalogue by SKU, so no test hard-codes an id or a price."""
    response = contract_client.get("/api/products/")
    response.raise_for_status()
    return {str(item["sku"]): item for item in response.json()["items"]}


def cards_named(html: str, product_name: str) -> list[Tag]:
    """Every card of ``product_name`` on a render, by its heading text."""
    cards = []
    for article in soup_of(html).find_all("article"):
        heading = article.find(["h2", "h3", "h4"])
        if heading is not None and normalize_text(heading.get_text(" ")) == product_name:
            cards.append(article)
    return cards


def add_to_cart_buttons(card: Tag) -> list[Tag]:
    """The card's add-to-cart actions, by role and visible text."""
    return [
        element
        for element in card.find_all("button")
        if not str(element.get("role") or "").strip() and visible_text(element) == ADD_TO_CART
    ]


def card_price(card: Tag) -> str:
    """The single currency amount a card shows."""
    amounts = [
        token for token in normalize_text(card.get_text(" ")).split() if token.startswith("$")
    ]
    assert len(amounts) == 1, f"expected one amount in the card, found {amounts}"
    return amounts[0]


def card_target(card: Tag, product_name: str) -> str:
    """Where the card's title link points."""
    links = [
        anchor
        for anchor in card.find_all("a", href=True)
        if normalize_text(anchor.get_text(" ")) == product_name
    ]
    assert len(links) == 1, f"expected one {product_name!r} link in the card, found {len(links)}"
    return str(links[0]["href"])


def currency(amount: float) -> str:
    return f"${amount:,.2f}"


@pytest.mark.parametrize("stage", STAGES)
def test_missing_button(render, catalogue, product_id_by_sku, stage: int) -> None:
    """Spec scenario "Missing button", in every stage.

    Product 5 loses its add-to-cart button, product 4 keeps every one of its
    own. The render with the flag off is the control: it is what says how many
    actions each product has when nothing is planted.
    """
    hidden = catalogue[MISSING_BUTTON_SKU]
    kept = catalogue[BROKEN_LINK_SKU]
    assert product_id_by_sku(MISSING_BUTTON_SKU) % 5 == 0
    assert product_id_by_sku(BROKEN_LINK_SKU) % 5 != 0

    without = render("/products", STAGE_FLAGS[stage]).text
    with_bug = render("/products", {**STAGE_FLAGS[stage], MISSING_BUTTON_BUG: True}).text

    def actions(html: str, product) -> int:
        cards = cards_named(html, str(product["name"]))
        assert cards, f"no card for {product['name']!r} on /products"
        return sum(len(add_to_cart_buttons(card)) for card in cards)

    assert actions(without, hidden) >= 1, "nothing to hide: the control render has no action"
    assert actions(with_bug, hidden) == 0
    assert actions(with_bug, kept) == actions(without, kept) >= 1


@pytest.mark.parametrize("stage", STAGES)
def test_price_mismatch_is_detectable_in_one_run(
    render, add_to_cart, catalogue, product_id_by_sku, fake_weasyprint, stage: int
) -> None:
    """Spec scenario "Price mismatch is detectable in one run", in every stage.

    The card lies; the cart, the checkout summary and the created order do not,
    so one run of one suite can prove the mismatch.
    """
    from .test_checkout_totals import displayed_amounts, order_amounts, order_number_of

    product = catalogue[WRONG_PRICE_SKU]
    assert product_id_by_sku(WRONG_PRICE_SKU) % 3 == 0
    actual = round(float(product["price"]), 2)
    inflated = round(actual * WRONG_PRICE_FACTOR, 2)
    assert inflated != actual
    quantity = 2
    flags = {**STAGE_FLAGS[stage], WRONG_PRICE_BUG: True}
    session_id = f"contract-wrong-price-{stage}"

    listing = render("/products", flags).text
    cards = cards_named(listing, str(product["name"]))
    assert cards, f"no card for {product['name']!r} on /products"
    for card in cards:
        assert card_price(card) == currency(inflated)

    add_to_cart(session_id, ((WRONG_PRICE_SKU, quantity),))

    cart = render("/cart", flags, session_id).text
    lines = cards_named(cart, str(product["name"]))
    assert len(lines) == 1, f"expected one cart line, found {len(lines)}"
    assert f"{quantity} × {currency(actual)}" in normalize_text(lines[0].get_text(" "))

    summary = displayed_amounts(render("/checkout", flags, session_id).text)
    assert summary["subtotal"] == round(actual * quantity, 2)

    placed = render(
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
    assert placed.status_code == 200, placed.text
    order = order_amounts(order_number_of(placed.text))
    assert order["subtotal"] == round(actual * quantity, 2)
    assert order["subtotal"] == summary["subtotal"]
    assert order["total"] == summary["total"]


@pytest.mark.parametrize("stage", STAGES)
def test_broken_links(render, catalogue, product_id_by_sku, stage: int) -> None:
    """`BUG_BROKEN_LINKS`: the card points at a page that is not a product.

    The status code is not pinned: the detail route answers with its HTML
    not-found page (404, added by `acceptance-conformance` for WEB-003_AC-9).
    What must hold is that it is a client error and that no product detail is
    served: the only `h1` allowed is the not-found page's own title.
    """
    product = catalogue[BROKEN_LINK_SKU]
    product_id = product_id_by_sku(BROKEN_LINK_SKU)
    assert product_id % 4 == 0
    flags = {**STAGE_FLAGS[stage], BROKEN_LINKS_BUG: True}

    listing = render("/products", flags).text
    cards = cards_named(listing, str(product["name"]))
    assert cards, f"no card for {product['name']!r} on /products"
    targets = {card_target(card, str(product["name"])) for card in cards}
    assert targets == {f"/products/invalid-{product_id}"}

    broken = render(f"/products/invalid-{product_id}", flags)

    assert 400 <= broken.status_code < 500, broken.status_code
    titles = [normalize_text(h1.get_text(" ")) for h1 in matches(broken.text, "h1")]
    assert titles in ([], ["Product not found"]), titles
    assert str(product["name"]) not in broken.text
    assert not [
        element
        for element in soup_of(broken.text).find_all("button")
        if visible_text(element) == ADD_TO_CART
    ]


@pytest.mark.parametrize("stage", STAGES)
def test_links_are_intact_without_the_bug(
    render, catalogue, product_id_by_sku, stage: int
) -> None:
    """With the flag off the same card links to the product page, which is served."""
    product = catalogue[BROKEN_LINK_SKU]
    product_id = product_id_by_sku(BROKEN_LINK_SKU)
    flags = STAGE_FLAGS[stage]

    listing = render("/products", flags).text
    cards = cards_named(listing, str(product["name"]))
    assert cards
    assert {card_target(card, str(product["name"])) for card in cards} == {
        f"/products/{product_id}"
    }

    detail = render(f"/products/{product_id}", flags)

    assert detail.status_code == 200
    assert str(product["name"]) in detail.text
