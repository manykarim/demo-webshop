"""The drift-proof smoke suite (tasks 7.3, 7.4 and 9.5).

Every flow of the spec's "Shop behavior survives drift" requirement, run in a
real browser against a real server in stages 1 to 4. The suite finds everything
by role, label and text; where it needs a detail of an element it found that
way - the visible icons of the theme toggle, the last message in the chat log -
it evaluates on that element. No id, class or `data-test` appears anywhere in
this file, which is why the same code passes in all four stages.

Three checks ride along:

* **Live DOM** (task 9.5): after each flow, every `data-*` attribute name in the
  document must be a content attribute or `data-test` (stages 1 and 2 only), and
  every id in the document must also occur in the server-rendered HTML of the
  same page and stage, `<template>` content included. That catches a runtime
  marker however the script writes it.
* **Aria snapshot** (task 7.4): the accessibility tree of stage N equals the one
  of stage 1, for the pages the flows visit. Both sides are taken in the same
  browser context - and therefore in the same workshop space, against the same
  session and cart - with the stage-1 side produced by applying preset `stage1`
  in that very context. That space is the stage fixture's own one (task 15.5),
  never `default` and never another stage's, and both snapshots have to name it
  in the site header: an ignored `X-Workshop-Space` header would otherwise let
  the comparison pass for the wrong reason.
* The catalogue renders exactly one add-to-cart button per card that offers an
  action.
"""
from __future__ import annotations

import re

import pytest
from bs4 import BeautifulSoup
from playwright.sync_api import Page, expect

from .conftest import DEFAULT_SPACE, apply_preset, stage_number

pytestmark = pytest.mark.browser

#: The demo account seeded with addresses and order history.
DEMO_EMAIL = "jamie@flowlinesupply.com"
DEMO_PASSWORD = "demo123"
DEMO_FULL_NAME = "Jamie Rivera"
DEMO_FIRST_NAME = "Jamie"
DEMO_ADDRESS_LINE = "123 Flow Street"

#: The accessible name of every add-to-cart button, whatever the product.
ADD_TO_CART = re.compile(r"^Add .+ to cart$")

#: Where a selected search suggestion takes the shopper.
PRODUCT_URL = re.compile(r"/products/\d+$")

#: The `data-*` attributes that carry content rather than a lookup marker
#: (design Decision 3), plus `data-test` - stages 1 and 2 only - and the space
#: indicator of `workshop-spaces`, which is a stable hook.
CONTENT_DATA_ATTRIBUTES = frozenset(
    {"data-product", "data-product-name", "data-category", "data-chat-prompt"}
)
ALLOWED_DATA_ATTRIBUTES = CONTENT_DATA_ATTRIBUTES | {"data-test", "data-workshop-space"}

#: The pages the flows visit, compared as accessibility trees in task 7.4.
ARIA_PAGES: tuple[str, ...] = ("/", "/products", "/products/3", "/cart", "/checkout")

_COLLECT_LIVE_DOM = """() => {
  const attributes = new Set();
  const ids = new Set();
  for (const element of document.querySelectorAll('*')) {
    for (const attribute of element.attributes) {
      attributes.add(attribute.name);
    }
    if (element.id) {
      ids.add(element.id);
    }
  }
  return { attributes: Array.from(attributes), ids: Array.from(ids) };
}"""

_VISIBLE_ICONS = """element => Array.from(element.querySelectorAll('svg path'))
  .filter(icon => getComputedStyle(icon).display !== 'none')
  .length"""

_ANSWERED = """element => {
  const last = element.lastElementChild;
  return Boolean(last) && !last.hasAttribute('aria-busy') && last.textContent.trim().length > 0;
}"""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def cart_badge(page: Page):
    """The cart badge, by its accessible label."""
    return page.get_by_label("Cart items")


def badge_count(page: Page) -> int:
    """The number the cart badge shows, with the empty badge counting as zero."""
    text = (cart_badge(page).text_content() or "").strip()
    return int(text) if text else 0


def flash(page: Page):
    """The confirmation region, by its role."""
    return page.get_by_role("status")


def server_ids(page: Page, url: str) -> set[str]:
    """Every id in the server-rendered HTML of ``url``, templates included.

    `html.parser` keeps `<template>` children as ordinary nodes, so the ids the
    script clones into the page - the typeahead listbox, for one - are found
    here as well.
    """
    response = page.request.get(url)
    assert response.ok, f"{url}: {response.status}"
    soup = BeautifulSoup(response.text(), "html.parser")
    return {str(tag["id"]) for tag in soup.find_all(attrs={"id": True})}


def check_live_dom(page: Page, stage: str) -> None:
    """Task 9.5: no runtime marker and no runtime id in the live document."""
    live = page.evaluate(_COLLECT_LIVE_DOM)
    problems: list[str] = []

    for name in sorted(live["attributes"]):
        if not name.startswith("data-"):
            continue
        if name not in ALLOWED_DATA_ATTRIBUTES:
            problems.append(f"{name!r} is not a content data attribute")
        elif name == "data-test" and stage_number(stage) > 2:
            problems.append(f"{name!r} must not be rendered in {stage}")

    rendered = server_ids(page, page.url)
    for element_id in sorted(live["ids"]):
        if element_id not in rendered:
            problems.append(f"the id {element_id!r} is written by the script, not the server")

    assert not problems, f"{page.url} in {stage}:\n" + "\n".join(f"  - {p}" for p in problems)


def sign_in(page: Page) -> None:
    """Sign the demo user in from whatever page is open."""
    page.get_by_role("button", name="Log in").click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Email").fill(DEMO_EMAIL)
    dialog.get_by_label("Password").fill(DEMO_PASSWORD)
    dialog.get_by_role("button", name="Sign in").click()
    expect(dialog).to_be_hidden()


# ---------------------------------------------------------------------------
# Task 7.3: the flows
# ---------------------------------------------------------------------------


def test_add_to_cart_from_a_product_card(page: Page, stage: str) -> None:
    """The badge counts up and the confirmation names the product.

    On `/` rather than on `/products`, because `<output>` carries the implicit
    role `status`: the price filter would add two more matches for the
    confirmation region there.
    """
    page.goto("/")
    expect(cart_badge(page)).to_be_attached()
    before = badge_count(page)

    button = page.get_by_role("button", name=ADD_TO_CART).first
    label = button.evaluate("element => element.getAttribute('aria-label')")
    product = re.fullmatch(r"Add (.+) to cart", label).group(1)
    button.click()

    expect(flash(page)).to_have_text(f"{product} added to cart.")
    expect(cart_badge(page)).to_have_text(str(before + 1))

    check_live_dom(page, stage)


def test_sign_in_and_account_menu(page: Page, stage: str) -> None:
    """The dialog closes both ways, the account menu opens, the shopper leaves."""
    page.goto("/")
    login = page.get_by_role("button", name="Log in")
    dialog = page.get_by_role("dialog")

    # Closed by its own close button.
    login.click()
    expect(dialog).to_be_visible()
    page.get_by_role("button", name="Close login form").click()
    expect(dialog).to_be_hidden()

    # Closed by a click on the backdrop, which is the overlay behind the dialog.
    login.click()
    expect(dialog).to_be_visible()
    page.mouse.click(4, 4)
    expect(dialog).to_be_hidden()

    sign_in(page)
    expect(login).to_be_hidden()

    trigger = page.get_by_role("button", name=f"Hi, {DEMO_FIRST_NAME}")
    logout = page.get_by_role("button", name="Log out")
    expect(trigger).to_be_visible()
    expect(logout).to_be_hidden()

    trigger.click()
    expect(logout).to_be_visible()

    logout.click()
    expect(flash(page)).to_have_text("Signed out successfully.")
    expect(login).to_be_visible()

    check_live_dom(page, stage)


def test_checkout_is_prefilled_after_sign_in(page: Page, stage: str) -> None:
    """Email, name and address carry the signed-in shopper's saved details."""
    page.goto("/")
    sign_in(page)

    page.goto("/checkout")
    # The checkout form lives in the main landmark; the sign-in dialog, which
    # carries an "Email" field of its own, is a sibling of it.
    form = page.get_by_role("main")

    expect(form.get_by_label("Email")).to_have_value(DEMO_EMAIL)
    expect(form.get_by_label("Full name")).to_have_value(DEMO_FULL_NAME)
    expect(form.get_by_label("Address")).to_have_value(re.compile(DEMO_ADDRESS_LINE))

    check_live_dom(page, stage)


def test_search_suggestions_with_keyboard_selection(page: Page, stage: str) -> None:
    """Typing offers options; the keyboard picks one and opens its product."""
    page.goto("/")
    search = page.get_by_role("searchbox", name="Search products")
    search.fill("desk")

    options = page.get_by_role("option")
    expect(options.first).to_be_visible()

    search.press("ArrowDown")
    selected = page.get_by_role("option", selected=True)
    expect(selected).to_have_count(1)
    suggestion = (selected.text_content() or "").strip()
    # The open dropdown is markup the script built: its ids must come from the
    # server's templates (task 9.5).
    check_live_dom(page, stage)

    search.press("Enter")
    page.wait_for_url(PRODUCT_URL)

    heading = (page.get_by_role("heading", level=1).text_content() or "").strip()
    assert suggestion.startswith(heading), f"{suggestion!r} is not the product {heading!r}"

    check_live_dom(page, stage)


def test_mobile_navigation(page: Page, stage: str) -> None:
    """At 390x844 the menu is behind the toggle, and the toggle opens it."""
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto("/")

    toggle = page.get_by_role("button", name="Toggle navigation")
    menu_link = page.get_by_role("navigation", name="Primary navigation").get_by_role(
        "link", name="Products"
    )

    expect(toggle).to_be_visible()
    expect(menu_link).to_be_hidden()

    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    expect(menu_link).to_be_visible()

    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(menu_link).to_be_hidden()

    check_live_dom(page, stage)


def test_theme_toggle(page: Page, stage: str) -> None:
    """The toggle flips the theme, its state, its label and its icon."""
    page.emulate_media(color_scheme="light")
    page.goto("/")

    light = page.get_by_role("button", name="Switch to dark mode")
    expect(light).to_have_attribute("aria-pressed", "false")
    expect(light).to_have_text("Dark mode")
    assert light.evaluate(_VISIBLE_ICONS) == 1
    assert page.evaluate("document.body.classList.contains('theme-dark')") is False

    light.click()

    dark = page.get_by_role("button", name="Switch to light mode")
    expect(dark).to_have_attribute("aria-pressed", "true")
    expect(dark).to_have_text("Light mode")
    assert dark.evaluate(_VISIBLE_ICONS) == 1
    assert page.evaluate("document.body.classList.contains('theme-dark')") is True

    dark.click()
    expect(light).to_have_attribute("aria-pressed", "false")
    assert page.evaluate("document.body.classList.contains('theme-dark')") is False

    check_live_dom(page, stage)


def test_chat_widget_answers(page: Page, stage: str) -> None:
    """The assistant replies with a mock answer in the conversation log."""
    page.goto("/")
    page.get_by_role("button", name="Open AI shop assistant").click()

    log = page.get_by_role("log", name="Conversation")
    expect(log).to_be_visible()

    question = "Which desk do you recommend for a small studio?"
    page.get_by_label("Ask Flowline Supply AI assistant").fill(question)
    page.get_by_role("button", name="Send").click()

    expect(log).to_contain_text(question)
    page.wait_for_function(_ANSWERED, arg=log.element_handle())
    answer = log.evaluate("element => element.lastElementChild.textContent.trim()")

    assert answer and answer != question

    check_live_dom(page, stage)


def test_every_card_offers_one_add_to_cart_button(page: Page, stage: str) -> None:
    """On `/products`, a card that acts has exactly one add-to-cart button."""
    page.goto("/products")
    cards = page.get_by_role("article")
    total = cards.count()
    assert total > 0

    acting = 0
    for index in range(total):
        card = cards.nth(index)
        buttons = card.get_by_role("button")
        add_buttons = card.get_by_role("button", name=ADD_TO_CART)
        if buttons.count() == 0:
            # The category previews render read-only cards (`show_actions=False`).
            continue
        acting += 1
        assert add_buttons.count() == 1, f"card {index} has {add_buttons.count()} add buttons"
        title = (card.get_by_role("heading").first.text_content() or "").strip()
        label = add_buttons.evaluate("element => element.getAttribute('aria-label')")
        assert label == f"Add {title} to cart"

    assert acting > 0

    check_live_dom(page, stage)


# ---------------------------------------------------------------------------
# Task 7.4: the accessibility tree is the same in every stage
# ---------------------------------------------------------------------------


def browser_session_id(page: Page) -> str:
    """The session id the shop script generated for this browser context.

    The cart API reads ``X-Session-ID`` and falls back to the shared demo cart,
    so a request made next to the page has to send the same id the page uses -
    which is the ``session_id`` cookie the script set on the first load.
    """
    for cookie in page.context.cookies():
        if cookie["name"] == "session_id":
            return str(cookie["value"])
    raise AssertionError("the shop script set no session cookie")


def fill_cart(page: Page) -> int:
    """Put a fixed cart behind the context's session, and return its size."""
    headers = {"X-Session-ID": browser_session_id(page)}
    products = page.request.get("/api/products/").json()["items"][:2]
    quantity = 0
    for factor, product in enumerate(products, start=1):
        response = page.request.post(
            "/api/cart/items",
            data={"product_id": product["id"], "quantity": factor},
            headers=headers,
        )
        assert response.ok, response.text()
        quantity += factor
    return quantity


def aria_snapshots(page: Page, quantity: int) -> dict[str, str]:
    """The accessibility tree of every page the flows visit."""
    trees: dict[str, str] = {}
    for path in ARIA_PAGES:
        page.goto(path)
        # The badge is filled by the script, so waiting for it also waits for
        # the page to have finished settling.
        expect(cart_badge(page)).to_have_text(str(quantity))
        trees[path] = page.locator("body").aria_snapshot()
    return trees


def test_aria_snapshot_equals_stage_one(
    page: Page, stage: str, workshop_space: str
) -> None:
    """Task 7.4: stage N and stage 1, same context, same session, same cart.

    Both passes run in this parametrization's own workshop space (task 15.5),
    so the baseline is recorded where the stage is applied - never in `default`
    and never in another stage's space.
    """
    page.goto("/")
    quantity = fill_cart(page)

    # The baseline is preset `stage1`, not `clean`: stage presets change only
    # locator flags, so the two passes differ in exactly those.
    apply_preset(page, "stage1")
    baseline = aria_snapshots(page, quantity)

    apply_preset(page, stage)
    current = aria_snapshots(page, quantity)

    # The space indicator is part of the stable contract (task 15.2), so it is
    # in both trees, and it names the space this context browses in. Asserting
    # it on both sides is what makes the equality below meaningful: a dropped
    # or ignored space header would show `Space: default` here, or nothing.
    indicator = f"Space: {workshop_space}"
    assert workshop_space != DEFAULT_SPACE
    for path in ARIA_PAGES:
        assert indicator in baseline[path], f"{path}: stage-1 baseline"
        assert indicator in current[path], f"{path}: {stage}"

    for path in ARIA_PAGES:
        assert current[path] == baseline[path], f"{path} differs in {stage}"


# ---------------------------------------------------------------------------
# Task 9.5: the live DOM check catches what it is there for
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="a runtime data-* marker must be reported")
def test_live_dom_check_catches_a_runtime_marker(page: Page) -> None:
    page.goto("/")
    apply_preset(page, "stage1")
    page.evaluate("document.body.dataset.probe = '1'")

    check_live_dom(page, "stage1")


@pytest.mark.xfail(strict=True, reason="a runtime id must be reported")
def test_live_dom_check_catches_a_runtime_id(page: Page) -> None:
    page.goto("/")
    apply_preset(page, "stage1")
    page.evaluate(
        "document.body.appendChild(Object.assign(document.createElement('div'),"
        " { id: 'runtime-probe' }))"
    )

    check_live_dom(page, "stage1")


# ---------------------------------------------------------------------------
# Task 15.5: the suite never leaves its spaces
# ---------------------------------------------------------------------------


def test_the_default_space_is_still_on_stage_one(playwright, base_url: str) -> None:
    """No preset of this suite reaches the space the server serves by default.

    Asked through an API request context of its own, because every browser
    context of this suite carries an `X-Workshop-Space` header and would answer
    for its own space instead.
    """
    api = playwright.request.new_context(base_url=base_url)
    try:
        response = api.get("/api/workshop/status")
        assert response.ok, response.text()
        status = response.json()
    finally:
        api.dispose()

    assert status["space"] == DEFAULT_SPACE
    assert status["locator_stage"] == "v1"
