"""WEB-006 Complete Checkout: conformance checks of AC-1 to AC-8 and AC-10 to AC-12.

Written from the story text, the index's interpretation rules and design D3
only. Carts are arranged through the API (Aurora Neural Headphones, id 1, x1
and Insight Smart Notebook, id 2, x2 = $328.99); acting and asserting happen
in the UI on ``/checkout``. The form values come from the story's test data:
``test@example.com``, ``Test User`` and ``123 Test Street, City`` are valid;
``notanemail``, ``a@b``, ``A``, ``123`` and ``1234`` are invalid.

"A validation error is shown for the field" follows the index's rule for
error messages: a message that appears as a result of the action, next to the
field (inside the field's own wrapper, or in the element the field's
``aria-describedby``/``aria-errormessage`` points to) or in an alert-role
element that names the field. Text that was on the page before the action does
not count, so every check compares the field's surroundings before and after.
AC-11 asks for a message next to each invalid field, so an alert elsewhere on
the page does not count there. Fields are found by their labels, inside the
page's main region (the sign-in dialog has an email field too).

AC-1's order total is checked on its own: the total must equal the subtotal
plus the shipping cost plus the tax amount, with "Complimentary" shipping
counted as 0. AC-12 replaces the withdrawn AC-9.
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import expect

from .conftest import SESSION_HEADER
from .helpers import ConformanceSetupError, phrase

pytestmark = pytest.mark.conformance

PRIMARY_ID = 1
SECOND_ID = 2
SECOND_QUANTITY = 2
CART = [(PRIMARY_ID, 1), (SECOND_ID, SECOND_QUANTITY)]

VALID = {"email": "test@example.com", "name": "Test User", "address": "123 Test Street, City"}
FIELDS = {
    "email": re.compile(r"e-?mail", re.IGNORECASE),
    "name": re.compile(r"\bname\b", re.IGNORECASE),
    "address": re.compile(r"\baddress\b", re.IGNORECASE),
    "team_size": re.compile(r"team\s*size", re.IGNORECASE),
    "notes": re.compile(r"instruction|notes?\b", re.IGNORECASE),
}
MENTIONS = {
    "email": re.compile(r"e-?mail", re.IGNORECASE),
    "name": re.compile(r"\bname\b", re.IGNORECASE),
    "address": re.compile(r"(?<!e-mail )(?<!email )address", re.IGNORECASE),
}
SUBMIT = re.compile(r"place\s+order|submit|complete\s+(order|checkout|purchase)|\bpay\b", re.IGNORECASE)
ORDER_TOKEN = re.compile(r"\bORD-[A-Za-z0-9]+")
ORDER_FORMAT = re.compile(r"^ORD-[0-9A-F]{8}$")
SUCCESS_WORDS = re.compile(r"thank|success|confirm|placed|received", re.IGNORECASE)
MONEY = r"\$\s?\d[\d,]*\.\d{2}"

#: The text next to a field: its aria-describedby/aria-errormessage targets and
#: its wrapper, the nearest ancestor that holds a label (short of the form).
NEARBY_JS = """el => {
  const shown = n => !!n && n.getClientRects().length > 0 && getComputedStyle(n).visibility !== 'hidden';
  const parts = [];
  for (const attr of ['aria-describedby', 'aria-errormessage']) {
    for (const ref of (el.getAttribute(attr) || '').split(/\\s+/).filter(Boolean)) {
      const node = document.getElementById(ref);
      if (shown(node)) parts.push(node.innerText);
    }
  }
  let box = el.parentElement;
  while (box && box.tagName !== 'FORM' && !box.querySelector('label')) box = box.parentElement;
  if (box && box.tagName !== 'FORM' && shown(box)) parts.push(box.innerText);
  return parts.join('\\n');
}"""


# ---------------------------------------------------------------------------
# Arrange helpers
# ---------------------------------------------------------------------------


def catalogue(api: httpx.Client) -> dict[int, dict[str, Any]]:
    response = api.get("/api/products/")
    if response.status_code != 200:
        raise ConformanceSetupError(f"GET /api/products/ answered {response.status_code}: {response.text[:200]!r}")
    items = response.json().get("items")
    if not isinstance(items, list) or not items:
        raise ConformanceSetupError("GET /api/products/ returned no product list")
    return {int(item["id"]): item for item in items}


def money(amount: float) -> str:
    return f"${amount:,.2f}"


def norm(text: str) -> str:
    return " ".join(text.split())


def cart_items(api: httpx.Client, session: str) -> list[dict[str, Any]]:
    response = api.get("/api/cart/", headers={SESSION_HEADER: session})
    if response.status_code != 200:
        raise ConformanceSetupError(f"GET /api/cart/ answered {response.status_code}: {response.text[:200]!r}")
    return list(response.json().get("items") or [])


def open_checkout(page: Any, context: Any, prefill_cart: Any, items: list = CART) -> str:
    """Arrange the cart through the API and open ``/checkout``; returns the session id."""
    session = prefill_cart(context, items)
    page.goto("/checkout")
    return session


# ---------------------------------------------------------------------------
# Page helpers
# ---------------------------------------------------------------------------


def form_field(page: Any, key: str) -> Any:
    field = page.get_by_role("main").get_by_label(FIELDS[key]).filter(visible=True)
    expect(field, f"the checkout form has no single visible {key} field").to_have_count(1)
    return field


def fill_form(page: Any, **values: str) -> None:
    for key, value in {**VALID, **values}.items():
        form_field(page, key).fill(value)


def submit_button(page: Any) -> Any:
    button = page.get_by_role("main").get_by_role("button").filter(has_text=SUBMIT)
    expect(button).to_have_count(1)
    expect(button).to_be_visible()
    return button


def poll(condition: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        try:
            if condition():
                return True
        except PlaywrightError:
            pass
        if time.monotonic() > deadline:
            return False
        time.sleep(0.2)


def nearby_lines(page: Any, key: str) -> set[str]:
    field = page.get_by_role("main").get_by_label(FIELDS[key]).filter(visible=True)
    if field.count() != 1:
        return set()
    return {norm(line) for line in field.evaluate(NEARBY_JS).splitlines() if norm(line)}


def alert_texts(page: Any) -> set[str]:
    alerts = page.get_by_role("main").get_by_role("alert").filter(visible=True)
    return {norm(text) for text in alerts.all_inner_texts() if norm(text)}


class Surroundings:
    """What is next to each field, and which alerts show, before an action."""

    def __init__(self, page: Any, keys: list[str]) -> None:
        self.page = page
        self.nearby = {key: nearby_lines(page, key) for key in keys}
        self.alerts = alert_texts(page)

    def new_nearby(self, key: str) -> set[str]:
        return nearby_lines(self.page, key) - self.nearby[key]

    def new_alerts_about(self, key: str) -> set[str]:
        """New alerts that name the field; a confirmation carrying an order number is no error."""
        return {
            text
            for text in alert_texts(self.page) - self.alerts
            if MENTIONS[key].search(text) and not ORDER_TOKEN.search(text)
        }

    def error_for(self, key: str, next_to_field_only: bool = False) -> set[str]:
        found = self.new_nearby(key)
        if not next_to_field_only:
            found |= self.new_alerts_about(key)
        return found


def submit(page: Any) -> None:
    submit_button(page).click()
    page.wait_for_load_state("domcontentloaded")


def checkout_form_shown(page: Any) -> None:
    expect(page).to_have_url(re.compile(r"^[^?#]*/checkout/?([?#].*)?$"))
    expect(form_field(page, "email")).to_be_visible()
    expect(submit_button(page)).to_be_visible()


def no_order_placed(page: Any, api: httpx.Client, session: str) -> None:
    main = page.get_by_role("main")
    expect(main.get_by_text(ORDER_TOKEN)).to_have_count(0)
    assert cart_items(api, session), "the cart was emptied, so an order was placed"


def check_invalid_value(page: Any, context: Any, api: httpx.Client, prefill_cart: Any, key: str, value: str) -> None:
    session = open_checkout(page, context, prefill_cart)
    fill_form(page, **{key: value})
    before = Surroundings(page, [key])

    submit(page)

    assert poll(lambda: bool(before.error_for(key))), f"no validation error is shown for the {key} field after {value!r}"
    no_order_placed(page, api, session)


def check_valid_value(page: Any, context: Any, prefill_cart: Any, key: str) -> None:
    open_checkout(page, context, prefill_cart)
    fill_form(page)
    field = form_field(page, key)
    before = Surroundings(page, [key])
    field.blur()
    assert not before.error_for(key), f"an error is shown for the valid {key} {VALID[key]!r} on leaving the field"

    submit(page)

    main = page.get_by_role("main")
    # The submit either placed the order or showed the form again; either way the page has settled.
    expect(main.get_by_text(ORDER_TOKEN).or_(main.get_by_label(FIELDS[key]).filter(visible=True)).first).to_be_visible()
    shown = before.error_for(key)
    assert not shown, f"an error is shown for the valid {key} {VALID[key]!r}: {shown}"


def order_summary(page: Any) -> Any:
    heading = page.get_by_role("main").get_by_role("heading").filter(has_text=re.compile(r"summary", re.IGNORECASE))
    summary = heading.locator("xpath=ancestor::*[self::section or self::aside][1]")
    expect(summary).to_have_count(1)
    expect(summary).to_be_visible()
    return summary


def place_order(page: Any, context: Any, prefill_cart: Any) -> tuple[str, str]:
    """Place an order in the UI with valid data; returns the session id and the shown order number."""
    session = open_checkout(page, context, prefill_cart)
    fill_form(page)
    submit(page)
    token = page.get_by_role("main").get_by_text(ORDER_TOKEN).filter(visible=True)
    expect(token.first).to_be_visible()
    match = ORDER_TOKEN.search(token.first.inner_text())
    assert match, "no order number is shown"
    return session, match.group(0)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def summary_text(page: Any) -> str:
    return norm(order_summary(page).inner_text())


LABEL = r"[^$\d]{0,40}?"


def amount(text: str, label: str) -> float:
    """The amount that follows ``label`` in the summary text; 0 for complimentary shipping."""
    match = re.search(rf"(?<![a-z]){label}{LABEL}({MONEY}|complimentary|free)", text, re.IGNORECASE)
    assert match, f"the summary shows no {label} amount: {text!r}"
    value = match.group(1)
    if not value.startswith("$"):
        return 0.0
    return float(value.replace("$", "").replace(",", "").strip())


@pytest.mark.ac("WEB-006_AC-1")
def test_ac_1_order_summary_sidebar(space_page, context, api, prefill_cart) -> None:
    products = catalogue(api)
    open_checkout(space_page, context, prefill_cart)
    summary = order_summary(space_page)

    for product_id, quantity in CART:
        item = products[product_id]
        unit = float(item["price"])
        expect(summary).to_contain_text(phrase(item["name"]))
        prices = {money(unit), money(round(unit * quantity, 2))}
        text = norm(summary.inner_text())
        assert any(price in text for price in prices), f"the summary shows no price of {item['name']!r}: {text!r}"
    text = norm(summary.inner_text())
    assert re.search(rf"subtotal{LABEL}{MONEY}", text, re.IGNORECASE), f"no subtotal amount: {text!r}"
    assert re.search(rf"shipping{LABEL}({MONEY}|complimentary|free)", text, re.IGNORECASE), f"no shipping cost: {text!r}"
    assert re.search(rf"tax{LABEL}{MONEY}", text, re.IGNORECASE), f"no tax amount: {text!r}"
    assert re.search(rf"(?<![a-z])total{LABEL}{MONEY}", text, re.IGNORECASE), f"no order total: {text!r}"


@pytest.mark.ac("WEB-006_AC-1")
@pytest.mark.planted_bug("BUG_CHECKOUT_TOTAL")
def test_ac_1_order_total_adds_up(space_page, context, prefill_cart) -> None:
    open_checkout(space_page, context, prefill_cart)
    text = summary_text(space_page)

    subtotal, shipping, tax = amount(text, "subtotal"), amount(text, "shipping"), amount(text, "tax")
    total = amount(text, "total")
    assert total == pytest.approx(subtotal + shipping + tax, abs=0.005), (
        f"the order total {money(total)} is not subtotal {money(subtotal)} + shipping {money(shipping)} "
        f"+ tax {money(tax)}"
    )


def field_kind(field: Any) -> tuple[str, str, bool]:
    return tuple(
        field.evaluate(
            "el => [el.tagName.toLowerCase(), (el.getAttribute('type') || 'text').toLowerCase(),"
            " el.required || el.getAttribute('aria-required') === 'true']"
        )
    )


@pytest.mark.ac("WEB-006_AC-2")
def test_ac_2_required_form_fields(space_page, context, prefill_cart) -> None:
    open_checkout(space_page, context, prefill_cart)

    tag, kind, required = field_kind(form_field(space_page, "email"))
    assert (tag, kind, required) == ("input", "email", True), f"email field is {tag}/{kind}, required={required}"
    tag, kind, required = field_kind(form_field(space_page, "name"))
    assert (tag, kind, required) == ("input", "text", True), f"full name field is {tag}/{kind}, required={required}"
    tag, kind, required = field_kind(form_field(space_page, "address"))
    assert (tag == "textarea" or (tag, kind) == ("input", "text")) and required, (
        f"address field is {tag}/{kind}, required={required}"
    )


@pytest.mark.ac("WEB-006_AC-3")
def test_ac_3_optional_form_fields(space_page, context, prefill_cart) -> None:
    open_checkout(space_page, context, prefill_cart)

    tag, kind, required = field_kind(form_field(space_page, "team_size"))
    assert (tag, kind, required) == ("input", "number", False), f"team size field is {tag}/{kind}, required={required}"
    tag, kind, required = field_kind(form_field(space_page, "notes"))
    assert (tag, required) == ("textarea", False), f"special instructions field is {tag}/{kind}, required={required}"


@pytest.mark.ac("WEB-006_AC-4")
@pytest.mark.parametrize("value", ["notanemail", "a@b"])
def test_ac_4_invalid_email(space_page, context, api, prefill_cart, value: str) -> None:
    check_invalid_value(space_page, context, api, prefill_cart, "email", value)


@pytest.mark.ac("WEB-006_AC-4")
def test_ac_4_valid_email(space_page, context, prefill_cart) -> None:
    check_valid_value(space_page, context, prefill_cart, "email")


@pytest.mark.ac("WEB-006_AC-5")
def test_ac_5_invalid_name(space_page, context, api, prefill_cart) -> None:
    check_invalid_value(space_page, context, api, prefill_cart, "name", "A")


@pytest.mark.ac("WEB-006_AC-5")
def test_ac_5_valid_name(space_page, context, prefill_cart) -> None:
    check_valid_value(space_page, context, prefill_cart, "name")


@pytest.mark.ac("WEB-006_AC-6")
@pytest.mark.parametrize("value", ["123", "1234"])
def test_ac_6_invalid_address(space_page, context, api, prefill_cart, value: str) -> None:
    check_invalid_value(space_page, context, api, prefill_cart, "address", value)


@pytest.mark.ac("WEB-006_AC-6")
def test_ac_6_valid_address(space_page, context, prefill_cart) -> None:
    check_valid_value(space_page, context, prefill_cart, "address")


@pytest.mark.ac("WEB-006_AC-7")
def test_ac_7_successful_order_submission(space_page, context, prefill_cart) -> None:
    _, number = place_order(space_page, context, prefill_cart)

    main = space_page.get_by_role("main")
    expect(main.get_by_text(SUCCESS_WORDS).filter(visible=True).first).to_be_visible()
    assert ORDER_FORMAT.fullmatch(number), f"the order number {number!r} is not ORD- plus 8 characters from 0-9 and A-F"


@pytest.mark.ac("WEB-006_AC-8")
def test_ac_8_invoice_and_summary_pdf_links(space_page, space, context, prefill_cart) -> None:
    place_order(space_page, context, prefill_cart)
    main = space_page.get_by_role("main")

    for what in ("invoice", "summary"):
        link = main.get_by_role("link").filter(has_text=re.compile(what, re.IGNORECASE))
        expect(link, f"no single link to the {what} PDF").to_have_count(1)
        expect(link).to_be_visible()
        href = link.get_attribute("href")
        assert href, f"the {what} link has no target"
        response = space_page.request.get(href, headers=dict(space.headers))
        assert response.status == 200, f"the {what} link {href!r} answered {response.status}"
        content_type = response.headers.get("content-type", "")
        assert content_type.startswith("application/pdf"), f"the {what} link serves {content_type!r}"
        assert response.body().startswith(b"%PDF"), f"the {what} link does not serve a PDF file"


@pytest.mark.ac("WEB-006_AC-12")
def test_ac_12_cart_cleared_after_order(space_page, context, api, prefill_cart) -> None:
    session, _ = place_order(space_page, context, prefill_cart)

    space_page.goto("/cart")

    assert cart_items(api, session) == [], "the cart still has items after the order"
    expect(space_page.get_by_role("main").get_by_text(re.compile(r"empty", re.IGNORECASE)).first).to_be_visible()
    header = space_page.get_by_role("banner")
    cart_link = header.get_by_role("link").filter(has_text=phrase("Cart")).or_(
        header.get_by_role("link", name=re.compile(r"\bcart\b", re.IGNORECASE))
    )
    expect(cart_link).to_have_count(1)
    expect(cart_link).to_be_visible()
    expect(cart_link).not_to_contain_text(re.compile(r"\d"), use_inner_text=True)


@pytest.mark.ac("WEB-006_AC-10")
def test_ac_10_empty_cart_error(space_page, context, prefill_cart) -> None:
    open_checkout(space_page, context, prefill_cart, items=[])
    main = space_page.get_by_role("main")
    expect(main.get_by_role("alert").filter(visible=True)).to_have_count(0)
    fill_form(space_page)

    def posts_checkout(request: Any) -> bool:
        return request.method == "POST" and urlsplit(request.url).path.rstrip("/") == "/checkout"

    with space_page.expect_request(posts_checkout):
        submit_button(space_page).click()

    alert = space_page.get_by_role("main").get_by_role("alert").filter(has_text=phrase("Your cart is empty"))
    expect(alert.first).to_be_visible()
    expect(space_page.get_by_role("main").get_by_text(ORDER_TOKEN)).to_have_count(0)
    expect(space_page.get_by_role("main").get_by_text(re.compile(r"thank you|order (placed|confirmed)", re.IGNORECASE))).to_have_count(0)


@pytest.mark.ac("WEB-006_AC-11")
def test_ac_11_validation_errors_display(space_page, context, api, prefill_cart) -> None:
    invalid = {"email": "a@b", "name": "A", "address": "1234"}
    session = open_checkout(space_page, context, prefill_cart)
    fill_form(space_page, **invalid)
    before = Surroundings(space_page, list(invalid))

    submit(space_page)

    assert poll(lambda: all(before.error_for(key, next_to_field_only=True) for key in invalid)), (
        "not every invalid field has an error message next to it: "
        + ", ".join(f"{key}: {sorted(before.error_for(key, next_to_field_only=True))}" for key in invalid)
    )
    checkout_form_shown(space_page)
    no_order_placed(space_page, api, session)
