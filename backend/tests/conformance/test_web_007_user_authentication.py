"""WEB-007 User Authentication: conformance checks of AC-1 to AC-10.

Written from the story text, the index's interpretation rules and design D3
only. The credentials come from the story's test data: Jamie
(``jamie@flowlinesupply.com`` / ``demo123``, shown as "Jamie" or the full
name), a wrong password for Jamie and the unknown ``nobody@example.com``.

Quoted UI text (the header's "Log in" and the dropdown's "Log out") is matched
against visible text through ``control()``; the story's revisions name these
labels (as imported: "Sign in" and "Logout", which under the index's whitespace
rule does not match "Log out"). The authentication dialog is found by its role and accessible
name, its fields by their labels, and its close button, which has no visible
text, by its accessible name. The header is the page's banner landmark.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from .helpers import control

pytestmark = pytest.mark.conformance

EMAIL = "jamie@flowlinesupply.com"
PASSWORD = "demo123"
USER_NAME = re.compile(r"\bjamie\b", re.IGNORECASE)
WRONG_CREDENTIALS = [("wrong-password", EMAIL, "wrongpass"), ("unknown-user", "nobody@example.com", "anypass")]
DIALOG_NAME = re.compile(r"sign\s*in|log\s*in|login|account|authenticat", re.IGNORECASE)
SUBMIT = re.compile(r"sign\s+in|log\s*in|submit", re.IGNORECASE)
INVALID = re.compile(r"invalid|incorrect|wrong|not\s+(match|recogni[sz]ed|found)|unknown", re.IGNORECASE)
PAGES = ("/", "/products", "/cart")

#: Whether the dialog overlays the page and the background is dimmed: the
#: element at a corner of the viewport belongs to the dialog's overlay (an
#: ancestor of the dialog, or the dialog itself for a native modal), and that
#: overlay - or the native backdrop - has a translucent background or a filter.
OVERLAY_JS = """dialog => {
  const alpha = color => {
    const m = color.match(/rgba?\\(([^)]+)\\)/);
    if (!m) return 0;
    const parts = m[1].split(',').map(s => s.trim());
    return parts.length === 4 ? parseFloat(parts[3]) : 1;
  };
  const dims = el => {
    const style = getComputedStyle(el);
    const a = alpha(style.backgroundColor);
    return (a > 0 && a < 1) || (style.backdropFilter && style.backdropFilter !== 'none');
  };
  const corner = document.elementFromPoint(3, window.innerHeight - 3);
  if (!corner) return {covered: false, dimmed: false};
  const overlay = [];
  for (let n = corner; n; n = n.parentElement) {
    if (n === dialog || n.contains(dialog)) { overlay.push(n); }
  }
  const covered = overlay.length > 0 && overlay[0] !== document.body && overlay[0] !== document.documentElement;
  let dimmed = overlay.some(el => el !== document.body && el !== document.documentElement && dims(el));
  if (!dimmed && dialog.matches && dialog.matches(':modal')) {
    const backdrop = getComputedStyle(dialog, '::backdrop');
    dimmed = alpha(backdrop.backgroundColor) > 0 || (backdrop.backdropFilter && backdrop.backdropFilter !== 'none');
  }
  return {covered, dimmed};
}"""


# ---------------------------------------------------------------------------
# Page helpers
# ---------------------------------------------------------------------------


def header(page: Any) -> Any:
    return page.get_by_role("banner")


def sign_in_button(page: Any) -> Any:
    """The header button that opens the authentication dialog, quoted as "Log in"."""
    return control(header(page), "button", "Log in")


def auth_dialog(page: Any) -> Any:
    return page.get_by_role("dialog", name=DIALOG_NAME)


def open_dialog(page: Any) -> Any:
    button = sign_in_button(page)
    expect(button).to_have_count(1)
    expect(button).to_be_visible()
    button.click()
    dialog = auth_dialog(page)
    expect(dialog).to_have_count(1)
    expect(dialog).to_be_visible()
    return dialog


def submit_credentials(dialog: Any, email: str, password: str) -> None:
    dialog.get_by_label(re.compile(r"e-?mail", re.IGNORECASE)).fill(email)
    dialog.get_by_label(re.compile(r"password", re.IGNORECASE)).fill(password)
    submit = dialog.get_by_role("button").filter(has_text=SUBMIT)
    expect(submit).to_have_count(1)
    submit.click()


def account_indicator(page: Any) -> Any:
    """The account dropdown's trigger or indicator in the header: the control that shows the user's name."""
    return header(page).get_by_role("button").filter(has_text=USER_NAME)


def sign_in(page: Any) -> Any:
    page.goto("/")
    dialog = open_dialog(page)
    submit_credentials(dialog, EMAIL, PASSWORD)
    expect(dialog).to_be_hidden()
    indicator = account_indicator(page)
    expect(indicator).to_have_count(1)
    expect(indicator).to_be_visible()
    return indicator


def open_account_dropdown(page: Any) -> Any:
    """Open the dropdown; returns the header, which holds it."""
    indicator = sign_in(page)
    indicator.click()
    return header(page)


def order_entries(page: Any, dropdown: Any) -> Any:
    """The entries of the "Recent orders" section: the list named after the section."""
    section_list = dropdown.get_by_role("list", name=re.compile(r"recent\s+orders", re.IGNORECASE))
    expect(section_list).to_have_count(1)
    expect(section_list).to_be_visible()
    return section_list.get_by_role("listitem")


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


@pytest.mark.ac("WEB-007_AC-1")
@pytest.mark.parametrize("path", PAGES)
def test_ac_1_log_in_button_in_header(space_page, path: str) -> None:
    space_page.goto(path)

    button = sign_in_button(space_page)
    expect(button).to_have_count(1)
    expect(button).to_be_visible()


@pytest.mark.ac("WEB-007_AC-2")
def test_ac_2_authentication_modal_opens(space_page) -> None:
    space_page.goto("/")

    dialog = open_dialog(space_page)

    state = dialog.evaluate(OVERLAY_JS)
    assert state["covered"], "the dialog does not overlay the page content"
    assert state["dimmed"], "the background content is not dimmed or de-emphasized"


@pytest.mark.ac("WEB-007_AC-3")
def test_ac_3_modal_contains_login_form(space_page) -> None:
    space_page.goto("/")
    dialog = open_dialog(space_page)

    email = dialog.get_by_label(re.compile(r"e-?mail", re.IGNORECASE))
    expect(email).to_be_visible()
    expect(email).to_be_editable()
    password = dialog.get_by_label(re.compile(r"password", re.IGNORECASE))
    expect(password).to_be_visible()
    expect(password).to_have_attribute("type", "password")
    submit = dialog.get_by_role("button").filter(has_text=SUBMIT)
    expect(submit).to_have_count(1)
    expect(submit).to_be_visible()
    close = dialog.get_by_role("button", name=re.compile(r"close|dismiss", re.IGNORECASE))
    expect(close).to_have_count(1)
    expect(close).to_be_visible()


@pytest.mark.ac("WEB-007_AC-4")
def test_ac_4_successful_login(space_page) -> None:
    space_page.goto("/")
    dialog = open_dialog(space_page)

    submit_credentials(dialog, EMAIL, PASSWORD)

    expect(dialog).to_be_hidden()
    expect(sign_in_button(space_page)).to_have_count(0)
    indicator = account_indicator(space_page)
    expect(indicator).to_have_count(1)
    expect(indicator).to_be_visible()
    expect(indicator).to_contain_text(USER_NAME)


@pytest.mark.ac("WEB-007_AC-5")
def test_ac_5_account_dropdown_contents(space_page) -> None:
    dropdown = open_account_dropdown(space_page)

    for label, pattern in (
        ("user name", USER_NAME),
        ("saved addresses", re.compile(r"saved\s+addresses|addresses", re.IGNORECASE)),
        ("payment methods", re.compile(r"payment\s+methods?", re.IGNORECASE)),
        ("recent orders", re.compile(r"recent\s+orders", re.IGNORECASE)),
    ):
        shown = dropdown.get_by_text(pattern).filter(visible=True)
        assert shown.count() >= 1, f"the account dropdown shows no {label}"
    orders = order_entries(space_page, dropdown)
    assert orders.count() >= 1, "the recent orders section lists no order"
    for index in range(orders.count()):
        entry = orders.nth(index)
        links = entry.get_by_role("link").filter(has_text=re.compile(r"invoice|summary", re.IGNORECASE))
        assert links.count() >= 1, f"order entry {index + 1} has no link to a PDF document"


@pytest.mark.ac("WEB-007_AC-6")
def test_ac_6_order_pdf_links(space_page, space) -> None:
    dropdown = open_account_dropdown(space_page)
    orders = order_entries(space_page, dropdown)
    assert orders.count() >= 1, "the recent orders section lists no order"

    for index in range(orders.count()):
        entry = orders.nth(index)
        for what in ("invoice", "summary"):
            link = entry.get_by_role("link").filter(has_text=re.compile(what, re.IGNORECASE))
            expect(link, f"order entry {index + 1} has no single {what} link").to_have_count(1)
            href = link.get_attribute("href")
            assert href, f"the {what} link of order entry {index + 1} has no target"
            response = space_page.request.get(href, headers=dict(space.headers))
            assert response.status == 200, f"the {what} link {href!r} answered {response.status}"
            content_type = response.headers.get("content-type", "")
            assert content_type.startswith("application/pdf"), f"the {what} link {href!r} serves {content_type!r}"


@pytest.mark.ac("WEB-007_AC-7")
def test_ac_7_logout(space_page) -> None:
    dropdown = open_account_dropdown(space_page)
    logout = control(dropdown, "button", "Log out")
    expect(logout).to_have_count(1)
    expect(logout).to_be_visible()

    logout.click()

    expect(account_indicator(space_page)).to_have_count(0)
    button = sign_in_button(space_page)
    expect(button).to_have_count(1)
    expect(button).to_be_visible()
    space_page.reload()
    expect(account_indicator(space_page)).to_have_count(0)
    expect(sign_in_button(space_page)).to_be_visible()


@pytest.mark.ac("WEB-007_AC-8")
@pytest.mark.parametrize(("case", "email", "password"), WRONG_CREDENTIALS, ids=[case for case, *_ in WRONG_CREDENTIALS])
def test_ac_8_invalid_credentials(space_page, case: str, email: str, password: str) -> None:
    space_page.goto("/")
    dialog = open_dialog(space_page)
    expect(dialog.get_by_role("alert").filter(visible=True)).to_have_count(0)

    submit_credentials(dialog, email, password)

    alert = dialog.get_by_role("alert").filter(visible=True)
    expect(alert).to_have_count(1)
    expect(alert).to_contain_text(INVALID)
    expect(dialog).to_be_visible()
    expect(account_indicator(space_page)).to_have_count(0)


@pytest.mark.ac("WEB-007_AC-9")
def test_ac_9_close_modal(space_page) -> None:
    space_page.goto("/products")
    url = space_page.url
    logins: list[str] = []
    space_page.on(
        "request",
        lambda request: logins.append(request.url)
        if urlsplit(request.url).path.rstrip("/") == "/api/auth/login"
        else None,
    )
    dialog = open_dialog(space_page)
    close = dialog.get_by_role("button", name=re.compile(r"close|dismiss", re.IGNORECASE))
    expect(close).to_have_count(1)

    close.click()

    expect(dialog).to_be_hidden()
    assert space_page.url == url, f"the visitor was taken from {url} to {space_page.url}"
    space_page.wait_for_timeout(300)
    assert logins == [], f"closing the dialog made a login attempt: {logins}"


@pytest.mark.ac("WEB-007_AC-10")
def test_ac_10_login_state_persists(space_page) -> None:
    sign_in(space_page)

    for path in ("/products", "/cart"):
        space_page.goto(path)
        indicator = account_indicator(space_page)
        expect(indicator).to_have_count(1)
        expect(indicator).to_be_visible()
        expect(sign_in_button(space_page)).to_have_count(0)
