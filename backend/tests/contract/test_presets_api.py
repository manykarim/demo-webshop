"""The presets, through the real endpoints (tasks 14.3 and 14.5).

Everywhere else in this package the stage is chosen by overriding the flag seam,
which is fast and says nothing about the control endpoints. Here the flags are
written the way a facilitator writes them - `POST /api/workshop/preset` and
`POST /api/workshop/flags` - and what the shop renders afterwards is compared
with the overridden render of the same stage. If the endpoints, the preset
tables or the flag seam disagreed, the two would differ.

The scenarios are the spec's:

* "Switching stages" and "Conflicting flags" (`locator-drift`);
* "Buggy preset", "Clean preset", "Stage preset keeps active bugs" and
  "Heal-vs-hide preset" (`planted-bugs`).

These tests are the only ones in the package that write flags. They restore
preset `clean` afterwards, and they never call `POST /api/workshop/reset`: a
reset also empties the space's carts, which the package-scoped matrix fills
once.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from bs4 import Tag

from backend.app.core.workshop import BUG_FLAGS

from .conftest import COVERED_PAGES, PAGES_BY_KEY, Page, zero_planted_delay
from .hooks import extract_hooks, matches, soup_of
from .semantic import accessible_name, document, normalize_text
from .test_checkout_totals import displayed_amounts, expected_tax

#: The bugs preset `drift_and_bug` leaves on.
DRIFT_AND_BUG_FLAGS: tuple[str, ...] = ("BUG_WRONG_PRICE", "BUG_CHECKOUT_TOTAL")

#: The product whose card the wrong price damages (id 3).
WRONG_PRICE_SKU = "PUL-RNG-003"

#: The stage-1 selectors of the two bugged flows (task 14.5). A suite that
#: healed by pinning them would find nothing in stage 4, which is the point.
LISTING_STAGE_1_SELECTORS: tuple[str, ...] = (
    "[data-test='product-price']",
    ".product-card__price",
    "[data-test='add-to-cart-btn']",
)
CHECKOUT_STAGE_1_SELECTORS: tuple[str, ...] = (
    "[data-test='checkout-total']",
    ".checkout-summary__total",
    "#checkout-email",
)


# ---------------------------------------------------------------------------
# Talking to the endpoints
# ---------------------------------------------------------------------------


@pytest.fixture
def workshop(contract_client) -> Iterator[Callable[..., dict]]:
    """Apply presets and flags through the endpoints; restore `clean` after.

    `clean` is the reset of the flag groups (design Decision 12) and touches
    nothing else - no cart, no order - so the package-scoped matrix around
    these tests keeps the carts it filled.
    """

    def call(path: str, payload: dict) -> dict:
        response = contract_client.post(f"/api/workshop/{path}", json=payload)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body.get("status") == "success", body
        return body

    try:
        yield call
    finally:
        contract_client.post("/api/workshop/preset", json={"preset": "clean"})


@pytest.fixture
def status(contract_client) -> Callable[[], dict]:
    """`GET /api/workshop/status` of the default space."""

    def read() -> dict:
        response = contract_client.get("/api/workshop/status")
        assert response.status_code == 200, response.text
        return response.json()

    return read


@pytest.fixture
def live(contract_client, add_to_cart) -> Callable[[Page], str]:
    """Render a matrix page against the flags the endpoints really wrote.

    Each call uses a session of its own and fills that session's cart, so a
    render that consumes its cart (the checkout confirmation) can be repeated.
    `planted_delay` is neutralised, exactly as in the overridden matrix: the
    `buggy` preset turns `BUG_SLOW_RESPONSE` on, and the wall-clock delay is
    asserted by `test_planted_bugs.py`, not here.
    """
    counter = {"n": 0}

    def render_page(page: Page) -> str:
        counter["n"] += 1
        session_id = f"presets-{page.key}-{counter['n']}"
        if page.cart:
            add_to_cart(session_id, page.cart)
        with zero_planted_delay():
            response = contract_client.request(
                page.method,
                page.path,
                headers={"x-session-id": session_id},
                data=dict(page.form) or None,
            )
        assert response.status_code == page.status, (
            f"{page.key} answered {response.status_code}: {response.text[:300]}"
        )
        return response.text

    return render_page


def _hooks_match(live_html: str, overridden_html: str) -> None:
    assert extract_hooks(live_html) == extract_hooks(overridden_html)


# ---------------------------------------------------------------------------
# "Switching stages" and "Conflicting flags"
# ---------------------------------------------------------------------------


def test_switching_stages(workshop, status, live, rendered, fake_weasyprint) -> None:
    """`stage2` then `stage3`: the second preset wins, on every page."""
    workshop("preset", {"preset": "stage2"})
    workshop("preset", {"preset": "stage3"})

    assert status()["locator_stage"] == "v3"

    for page in COVERED_PAGES:
        _hooks_match(live(page), rendered(page, 3))


def test_conflicting_flags(workshop, status, live, rendered, fake_weasyprint) -> None:
    """`LOCATOR_V2` and `LOCATOR_V4` together render stage 4 everywhere."""
    workshop("flags", {"flags": {"LOCATOR_V2": True, "LOCATOR_V4": True}})

    assert status()["locator_stage"] == "v4"

    for page in COVERED_PAGES:
        _hooks_match(live(page), rendered(page, 4))

    listing = live(PAGES_BY_KEY["listing"])
    assert matches(listing, ".product-tile"), "the product card did not reach stage 4"
    assert not matches(listing, ".item-card"), "the stage-2 card name is still rendered"
    assert not matches(listing, ".product-card")


# ---------------------------------------------------------------------------
# "Buggy preset", "Clean preset", "Stage preset keeps active bugs"
# ---------------------------------------------------------------------------


def test_buggy_preset(workshop, status) -> None:
    """`buggy` activates exactly the five registered bugs, in registry order."""
    workshop("preset", {"preset": "buggy"})

    assert status()["active_bugs"] == list(BUG_FLAGS)


def test_clean_preset(workshop, status) -> None:
    """`clean` clears every bug and every locator flag."""
    workshop("preset", {"preset": "buggy"})
    workshop("preset", {"preset": "stage4"})
    workshop("preset", {"preset": "clean"})

    reported = status()
    assert reported["active_bugs"] == []
    assert reported["locator_stage"] == "v1"


def test_a_freshly_seeded_database_reports_no_bugs_and_stage_1(app_client) -> None:
    """The shop as it is seeded: no planted bug active, stage 1.

    `app_client` is the canonical fixture for a private database with products
    and flags seeded and nothing else done to it, so this is the seeded state
    itself and not the state preset `clean` produces.
    """
    response = app_client.get("/api/workshop/status")

    assert response.status_code == 200, response.text
    reported = response.json()
    assert reported["active_bugs"] == []
    assert reported["locator_stage"] == "v1"


def test_a_stage_preset_keeps_the_active_bugs(workshop, status) -> None:
    """`stage1` after `buggy` resets the stage and leaves the bugs alone."""
    workshop("preset", {"preset": "buggy"})
    workshop("preset", {"preset": "stage1"})

    reported = status()
    assert reported["active_bugs"] == list(BUG_FLAGS)
    assert reported["locator_stage"] == "v1"


# ---------------------------------------------------------------------------
# "Heal-vs-hide preset" (task 14.5)
# ---------------------------------------------------------------------------


def _card_of(html: str, product_name: str) -> Tag:
    """The card of ``product_name``, found by its action's role and name.

    No drifting hook is involved: the add-to-cart button is located by its role
    and its accessible name, and the card is the `<article>` it sits in.
    """
    soup = soup_of(html)
    doc = document(soup)
    wanted = f"Add {product_name} to cart"
    buttons = [
        element
        for element in soup.find_all("button")
        if accessible_name(element, doc, "button") == wanted
    ]
    assert len(buttons) == 1, f"expected one {wanted!r} button, found {len(buttons)}"
    card = buttons[0].find_parent("article")
    assert card is not None, f"the {wanted!r} button sits in no article"
    return card


def _price_in(card: Tag) -> str:
    """The currency amount a card shows, read from its text."""
    amounts = [
        token for token in normalize_text(card.get_text(" ")).split() if token.startswith("$")
    ]
    assert len(amounts) == 1, f"expected one amount in the card, found {amounts}"
    return amounts[0]


def test_heal_vs_hide_preset(
    workshop, status, live, render, add_to_cart, contract_client, product_id_by_sku
) -> None:
    """Spec scenario "Heal-vs-hide preset" (`drift_and_bug` after `buggy`).

    The preset is absolute for the groups it owns, so applying it after `buggy`
    must leave exactly two bugs on. Stage 4 then hides every stage-1 selector of
    the two bugged flows, while role, label and text still reach both defects.
    """
    products = {
        str(item["sku"]): item for item in contract_client.get("/api/products/").json()["items"]
    }
    product = products[WRONG_PRICE_SKU]
    actual_price = round(float(product["price"]), 2)
    inflated = f"${round(actual_price * 1.15, 2):,.2f}"

    workshop("preset", {"preset": "buggy"})
    workshop("preset", {"preset": "drift_and_bug"})

    reported = status()
    assert reported["locator_stage"] == "v4"
    assert reported["active_bugs"] == list(DRIFT_AND_BUG_FLAGS)

    listing = live(PAGES_BY_KEY["listing"])
    checkout = live(PAGES_BY_KEY["checkout-items"])

    # Stage 4 hooks, on the page the cards are on.
    assert matches(listing, ".product-tile")

    # The defects are there, found without a single drifting hook.
    card = _card_of(listing, str(product["name"]))
    assert _price_in(card) == inflated, (
        f"the card of {product['name']} shows {_price_in(card)}, expected {inflated}"
    )

    amounts = displayed_amounts(checkout)
    assert amounts["subtotal"] > 0
    assert amounts["tax"] == expected_tax(amounts["subtotal"])
    assert amounts["total"] != round(amounts["subtotal"] + amounts["tax"], 2)

    # ... and every stage-1 selector of those two flows is gone.
    for selector in LISTING_STAGE_1_SELECTORS:
        assert not matches(listing, selector), f"{selector!r} still matches on /products"
    for selector in CHECKOUT_STAGE_1_SELECTORS:
        assert not matches(checkout, selector), f"{selector!r} still matches on /checkout"

    # Each of them matches in a stage 1 render with the same bugs, so the
    # selectors are real and the stage is what broke them.
    bug_flags = dict.fromkeys(DRIFT_AND_BUG_FLAGS, True)
    session_id = "presets-stage1-heal-vs-hide"
    add_to_cart(session_id, PAGES_BY_KEY["checkout-items"].cart)
    with zero_planted_delay():
        stage_1_listing = render("/products", bug_flags, session_id).text
        stage_1_checkout = render("/checkout", bug_flags, session_id).text

    for selector in LISTING_STAGE_1_SELECTORS:
        assert matches(stage_1_listing, selector), f"{selector!r} matches nothing in stage 1"
    for selector in CHECKOUT_STAGE_1_SELECTORS:
        assert matches(stage_1_checkout, selector), f"{selector!r} matches nothing in stage 1"

    assert _price_in(_card_of(stage_1_listing, str(product["name"]))) == inflated
    stage_1_amounts = displayed_amounts(stage_1_checkout)
    assert stage_1_amounts["total"] != round(
        stage_1_amounts["subtotal"] + stage_1_amounts["tax"], 2
    )
