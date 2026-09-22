"""Pages and flag-driven APIs read their flags from the seam (tasks 5.2, 5.3).

Every assertion here sets a flag in space ``octocat`` only and then compares the
same request with and without ``X-Workshop-Space: octocat``: the space must see
its own value and the ``default`` space must stay on the seeded one.
"""
from __future__ import annotations

from collections.abc import Mapping

import pytest

from backend.app.core.db import get_session_factory
from backend.app.core.feature_flags import set_flags
from backend.app.core.spaces import SPACE_HEADER
from backend.tests.spaces.helpers import rendered_stage, sqlite_rows

#: The participant space every test in this module writes to.
OCTOCAT = "octocat"

#: A valid checkout form; the cart is empty, so the POST renders the 400 page.
CHECKOUT_FORM = {
    "name": "Ada Lovelace",
    "email": "ada@example.com",
    "address": "12 Analytical Way",
}


def write_flags(client, space: str, updates: Mapping[str, bool]) -> None:
    """Apply ``updates`` to ``space`` in the loop the application runs on."""

    async def _write() -> None:
        session_factory = get_session_factory()
        async with session_factory() as session:
            await set_flags(session, space, updates)

    client.portal.call(_write)


def space_headers(space: str | None) -> dict[str, str]:
    """Request headers that put a request into ``space`` (none for ``default``)."""
    return {SPACE_HEADER: space} if space else {}


def first_product_id() -> int:
    """The id of a seeded product, for the product detail page."""
    return int(sqlite_rows("SELECT id FROM products ORDER BY id LIMIT 1")[0][0])


def page_responses(client, path: str):
    """The same page rendered in ``octocat`` and in the ``default`` space."""
    return (
        client.get(path, headers=space_headers(OCTOCAT)),
        client.get(path, headers=space_headers(None)),
    )


@pytest.mark.parametrize("path", ["/", "/products", "/cart", "/checkout"])
def test_page_context_uses_the_flags_of_the_request_space(app_client, path: str) -> None:
    """A GET page route renders the flags of its own space."""
    write_flags(app_client, OCTOCAT, {"NEW_CART_UI": True})

    in_space, in_default = page_responses(app_client, path)

    assert in_space.status_code == 200
    assert in_default.status_code == 200
    assert in_space.context["feature_flags"]["NEW_CART_UI"] is True
    assert in_default.context["feature_flags"]["NEW_CART_UI"] is False


def test_product_detail_page_uses_the_flags_of_the_request_space(app_client) -> None:
    """The sixth GET page route, which also takes a path parameter."""
    write_flags(app_client, OCTOCAT, {"NEW_CART_UI": True})

    in_space, in_default = page_responses(app_client, f"/products/{first_product_id()}")

    assert in_space.status_code == 200
    assert in_space.context["feature_flags"]["NEW_CART_UI"] is True
    assert in_default.context["feature_flags"]["NEW_CART_UI"] is False


def test_checkout_submit_uses_the_flags_of_the_request_space(app_client) -> None:
    """``POST /checkout`` renders its flags too, here on the empty-cart 400."""
    write_flags(app_client, OCTOCAT, {"NEW_CART_UI": True})

    in_space = app_client.post("/checkout", data=CHECKOUT_FORM, headers=space_headers(OCTOCAT))
    in_default = app_client.post("/checkout", data=CHECKOUT_FORM, headers=space_headers(None))

    assert in_space.status_code == 400
    assert in_default.status_code == 400
    assert in_space.context["feature_flags"]["NEW_CART_UI"] is True
    assert in_default.context["feature_flags"]["NEW_CART_UI"] is False


def test_locator_stage_is_rendered_per_space(app_client) -> None:
    """The rendered markup, not only the context, follows the space."""
    write_flags(app_client, OCTOCAT, {"LOCATOR_V2": True})

    in_space, in_default = page_responses(app_client, "/products")

    assert rendered_stage(in_space.text) == "v2"
    assert rendered_stage(in_default.text) == "v1"


def test_search_mode_follows_the_space(app_client) -> None:
    """``SEARCH_V2`` reaches ``api/search.py`` through the seam (task 5.3)."""
    write_flags(app_client, OCTOCAT, {"SEARCH_V2": True})

    in_space = app_client.get("/api/search/?query=desk", headers=space_headers(OCTOCAT))
    in_default = app_client.get("/api/search/?query=desk", headers=space_headers(None))

    assert in_space.json()["mode"] == "semantic"
    assert in_default.json()["mode"] == "keyword"


def test_ai_variation_follows_the_space(app_client) -> None:
    """``AIService`` is handed the flags of the request's space (task 5.3)."""
    write_flags(app_client, OCTOCAT, {"AI_VARIED_RESPONSES": True})
    payload = {"question": "desk"}

    in_space = app_client.post("/api/ai/ask", json=payload, headers=space_headers(OCTOCAT))
    in_default = app_client.post("/api/ai/ask", json=payload, headers=space_headers(None))

    assert in_space.json()["workshop_flags"]["varied"] is True
    assert in_default.json()["workshop_flags"]["varied"] is False
