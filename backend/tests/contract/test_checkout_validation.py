"""Regression tests for the checkout form's validation render (WEB-006_AC-4 to AC-6, AC-11).

Before the fix, the checkout form relied on the browser's own checks (which
show no message in the page and let ``a@b`` through) and ``POST /checkout``
declared its rules on the ``Form`` parameters, so a too-short name or address
or an incomplete email address replaced the page with FastAPI's JSON 422 body.
The handler now validates the fields itself, while ``workshop_view`` is active,
and re-renders ``checkout.html`` with status 422: one message per invalid field
inside the field's wrapper, referenced by the field's ``aria-describedby``, the
field marked ``aria-invalid``, a form-level alert, and the values the shopper
typed. The form is ``novalidate``, so every rule is reported the same way.

The render is also a ``COVERED_PAGES`` entry (``checkout-post-invalid``), so the
stage matrix of ``test_stage_contract.py`` checks its hooks; the tests here pin
what a shopper sees in every stage, that nothing is ordered, and that the
checkout API keeps its JSON errors.
"""
from __future__ import annotations

import itertools
import re

import pytest

from backend.app.core.workshop import STAGES

from .conftest import MATRIX_CART, STAGE_FLAGS
from .hooks import soup_of
from .semantic import normalize_text

VALID = {"email": "test@example.com", "name": "Test User", "address": "123 Test Street, City"}

#: The messages a shopper reads next to each invalid field.
MESSAGES = {
    "email": "Enter a valid email address, for example name@example.com.",
    "name": "Enter your full name (at least 2 characters).",
    "address": "Enter your shipping address (at least 5 characters).",
}
FORM_ALERT = "Please correct the fields marked below and place your order again."

#: One invalid value per case, from the story's validation edge cases.
INVALID_CASES = [
    ("email", ""),
    ("email", "notanemail"),
    ("email", "a@b"),
    ("name", ""),
    ("name", "A"),
    ("address", ""),
    ("address", "123"),
    ("address", "1234"),
]

_SESSIONS = itertools.count(1)


def _session(add_to_cart) -> str:
    session_id = f"checkout-validation-{next(_SESSIONS)}"
    add_to_cart(session_id, MATRIX_CART)
    return session_id


def _cart_items(contract_client, session_id: str) -> list:
    response = contract_client.get("/api/cart/", headers={"X-Session-ID": session_id})
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _field(form, name: str):
    field = form.find(attrs={"name": name})
    assert field is not None, f"the form has no {name} field"
    return field


def _described_texts(soup, field) -> list[str]:
    references = (field.get("aria-describedby") or "").split()
    texts = []
    for reference in references:
        target = soup.find(id=reference)
        assert target is not None, f"aria-describedby names the missing id {reference!r}"
        texts.append(normalize_text(target.get_text(" ")))
    return texts


@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize(("key", "value"), INVALID_CASES)
def test_an_invalid_field_re_renders_the_form_with_its_message(
    render, add_to_cart, contract_client, stage: int, key: str, value: str
) -> None:
    session_id = _session(add_to_cart)
    submitted = {**VALID, key: value, "team_size": "5", "notes": "Please gift wrap"}

    response = render("/checkout", STAGE_FLAGS[stage], session_id, method="POST", data=submitted)

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("text/html")
    soup = soup_of(response.text)
    form = soup.find("form", attrs={"action": "/checkout"})
    assert form is not None, "the checkout form is not shown again"
    assert form.has_attr("novalidate")
    # Exactly the invalid field is marked, and its message is next to it.
    for name in VALID:
        field = _field(form, name)
        assert (field.get("aria-invalid") == "true") == (name == key), name
        described = _described_texts(soup, field)
        assert (MESSAGES[name] in described) == (name == key), (name, described)
    message = form.find(string=re.compile(re.escape(MESSAGES[key])))
    assert message is not None, "the message is not inside the checkout form"
    assert message.parent.parent is not form, "a message is a direct child of the form"
    # The form's only direct-child <p> stays the signed-in note.
    assert len(form.find_all("p", recursive=False)) == 1
    # A form-level alert, and still exactly one status region on the page.
    alerts = [normalize_text(alert.get_text(" ")) for alert in soup.find_all(attrs={"role": "alert"})]
    assert any(FORM_ALERT in alert for alert in alerts), alerts
    assert len(soup.find_all(attrs={"role": "status"})) == 1
    # What the shopper typed comes back.
    for name in ("email", "name"):
        if name != key or value:
            assert _field(form, name).get("value") == submitted[name]
    assert normalize_text(_field(form, "notes").get_text()) == "Please gift wrap"
    assert _field(form, "team_size").get("value") == "5"
    # Nothing was ordered: no order number, and the cart still holds its items.
    assert not re.search(r"ORD-[0-9A-F]{8}", response.text)
    assert len(_cart_items(contract_client, session_id)) == len(MATRIX_CART)


@pytest.mark.parametrize("stage", STAGES)
def test_every_invalid_field_gets_its_own_message(render, add_to_cart, stage: int) -> None:
    session_id = _session(add_to_cart)
    data = {"email": "a@b", "name": "A", "address": "123"}

    response = render("/checkout", STAGE_FLAGS[stage], session_id, method="POST", data=data)

    assert response.status_code == 422
    soup = soup_of(response.text)
    form = soup.find("form", attrs={"action": "/checkout"})
    for name, message in MESSAGES.items():
        assert message in _described_texts(soup, _field(form, name)), name
    hooks = [soup.find(attrs={"data-test": f"checkout-{name}-error"}) for name in MESSAGES]
    assert all(hook is not None for hook in hooks) == (stage in (1, 2))


@pytest.mark.parametrize("stage", (1, 2))
def test_the_message_text_is_identical_in_stages_1_and_2(render, add_to_cart, stage: int) -> None:
    def text(flags) -> str:
        response = render(
            "/checkout", flags, _session(add_to_cart), method="POST", data={"email": "a@b", "name": "A", "address": "123"}
        )
        return normalize_text(soup_of(response.text).find("main").get_text(" "))

    assert text(STAGE_FLAGS[stage]) == text(STAGE_FLAGS[1])


def test_a_valid_submission_still_places_the_order(
    render, add_to_cart, contract_client, fake_weasyprint
) -> None:
    session_id = _session(add_to_cart)

    response = render("/checkout", STAGE_FLAGS[1], session_id, method="POST", data=VALID)

    assert response.status_code == 200
    assert re.search(r"Order ORD-[0-9A-F]{8} confirmed!", response.text)
    assert "aria-invalid" not in response.text
    assert _cart_items(contract_client, session_id) == []


def test_an_empty_cart_is_still_reported_for_valid_details(render) -> None:
    response = render("/checkout", STAGE_FLAGS[1], "checkout-validation-empty", method="POST", data=VALID)

    assert response.status_code == 400
    alerts = [normalize_text(alert.get_text(" ")) for alert in soup_of(response.text).find_all(attrs={"role": "alert"})]
    assert any("Your cart is empty" in alert for alert in alerts), alerts


def test_the_checkout_page_shows_no_message_before_a_submission(render, add_to_cart) -> None:
    response = render("/checkout", STAGE_FLAGS[1], _session(add_to_cart))

    assert response.status_code == 200
    assert "aria-invalid" not in response.text
    for message in (*MESSAGES.values(), FORM_ALERT):
        assert message not in response.text


def test_the_checkout_api_keeps_its_json_errors(contract_client, add_to_cart) -> None:
    session_id = _session(add_to_cart)

    response = contract_client.post(
        "/api/checkout/",
        json={"email": "a@b", "name": "A", "address": "123"},
        headers={"X-Session-ID": session_id},
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/json")
