"""Live checks of the conformance harness itself (tasks 4.1-4.4).

Marked ``conformance`` and carrying no ``ac`` marker: the report lists them
under "Harness", never as a criterion. They need a running image passed with
``--base-url`` (except ``test_base_url``) and adapt to the space mode.
"""
from __future__ import annotations

import re
import secrets

import httpx
import pytest
from playwright.sync_api import expect

from .conftest import (
    PER_CHECK,
    SESSION_HEADER,
    SPACE_HEADER,
    Space,
    Target,
    next_space_id,
)
from .helpers import control, phrase, section

pytestmark = pytest.mark.conformance


def test_base_url(base_url: str | None, pytestconfig: pytest.Config) -> None:
    """``--base-url`` is the only target selector, and nothing replaces a missing one."""
    option = pytestconfig.getoption("base_url")
    if option:
        assert base_url == option
    else:
        assert base_url is None


def test_status_reports_the_space(space: Space, api: httpx.Client) -> None:
    status = api.get("/api/workshop/status").json()

    if space.mode == PER_CHECK:
        assert re.fullmatch(r"cf-[0-9a-f]{6}-\d{4}", space.id)
        assert api.headers[SPACE_HEADER] == space.id
        assert status["space"] == space.id
    else:
        assert SPACE_HEADER not in api.headers
        assert status["space"] == "default"
    assert status["locator_stage"] == "v1"
    assert status["active_bugs"] == []


def cart_products(client: httpx.Client, session_id: str | None = None) -> list[int]:
    headers = {SESSION_HEADER: session_id} if session_id else {}
    response = client.get("/api/cart/", headers=headers)
    assert response.status_code == 200, response.text
    return [item["product_id"] for item in response.json()["items"]]


def add_item(client: httpx.Client, session_id: str | None = None) -> None:
    headers = {SESSION_HEADER: session_id} if session_id else {}
    response = client.post("/api/cart/items", json={"product_id": 1, "quantity": 2}, headers=headers)
    assert response.status_code == 200, response.text


def test_reset_is_scoped_to_the_space(space: Space, api: httpx.Client, target: Target) -> None:
    """The fixture's reset empties its own space's carts and no other space's."""
    if space.mode == PER_CHECK:
        session_id = f"cf-harness-{secrets.token_hex(4)}"
        with httpx.Client(base_url=target.base_url, timeout=10) as default_space:
            add_item(api, session_id)
            add_item(default_space, session_id)
            try:
                space.reset()
                assert cart_products(api, session_id) == []
                assert cart_products(default_space, session_id) == [1]
            finally:
                default_space.delete("/api/cart/", headers={SESSION_HEADER: session_id})
    else:
        other = next_space_id()
        with httpx.Client(base_url=target.base_url, headers={SPACE_HEADER: other}, timeout=10) as other_space:
            add_item(api)  # the legacy workshop-demo cart of the default space
            add_item(other_space)
            try:
                space.reset()
                assert cart_products(api) == []
                assert cart_products(other_space) == [1]
            finally:
                other_space.post("/api/workshop/reset")


def test_space_page_carries_the_space(space_page, space: Space) -> None:
    response = space_page.goto("/api/workshop/status")

    assert response is not None and response.ok
    assert response.json()["space"] == (space.id if space.mode == PER_CHECK else "default")


def test_prefill_cart_fills_the_cart_page(space_page, context, prefill_cart, space: Space, target: Target) -> None:
    session_id = prefill_cart(context, [1])

    space_page.goto("/cart")

    expect(section(space_page, "Your cart").get_by_role("heading", name="Aurora Neural Headphones")).to_be_visible()
    if space.mode == PER_CHECK:
        with httpx.Client(base_url=target.base_url, timeout=10) as default_space:
            assert cart_products(default_space, session_id) == []


def test_catalogue_cards_are_scoped_by_section(space_page) -> None:
    """Page-wide article lookups are ambiguous on /products; section() is not (design Context)."""
    space_page.goto("/products")
    grid = section(space_page, "All products")
    aurora = space_page.get_by_role("heading", name="Aurora Neural Headphones")

    expect(space_page.get_by_role("article")).to_have_count(18)
    expect(grid.get_by_role("article")).to_have_count(12)
    expect(control(grid, "button", "Add to Cart")).to_have_count(12)
    for card in grid.get_by_role("article").all():
        expect(control(card, "button", "Add to Cart")).to_have_count(1)
    expect(grid.get_by_role("article").filter(has=aurora)).to_have_count(1)
    expect(space_page.get_by_role("article").filter(has=aurora)).to_have_count(2)
    # Role names are accessible names ("Add <product> to cart"), not the quoted phrase.
    expect(space_page.get_by_role("button", name=phrase("Add to Cart"))).to_have_count(0)


def test_detail_actions_are_scoped_to_the_hero(space_page) -> None:
    space_page.goto("/products/1")
    hero = section(space_page, "Aurora Neural Headphones")

    expect(hero.get_by_role("heading", level=1)).to_have_text("Aurora Neural Headphones")
    expect(control(hero, "button", "Add to Cart")).to_have_count(1)
    assert control(space_page, "button", "Add to Cart").count() > 1


@pytest.mark.planted_bug("BUG_CHECKOUT_TOTAL")
def test_variant_bugs_reach_the_page(space_page) -> None:
    """Passes in ``clean`` and the stages; must fail wherever BUG_CHECKOUT_TOTAL is on."""
    response = space_page.goto("/api/workshop/status")

    assert response is not None and response.ok
    assert response.json()["active_bugs"] == []

