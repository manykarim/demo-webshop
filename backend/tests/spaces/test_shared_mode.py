"""Shared mode protects the baseline, not individual spaces (task 6.3, design D6).

``require_workshop_write_access`` guards only the control operations that act on
the global ``default`` space. Everything a shopper does, and every read, stays
open, because a forgotten space header must not look like a shop defect.
"""
from __future__ import annotations

import pytest

from backend.app.core.config import settings
from backend.app.core.spaces import SPACE_HEADER, WORKSHOP_WRITE_DENIED_MESSAGE
from backend.app.services.ai_service import AIService, ProductInsight
from backend.tests.spaces.helpers import sqlite_rows

#: The participant space used throughout this module.
OCTOCAT = "octocat"

#: A valid checkout payload for both the API and the form.
CUSTOMER = {
    "name": "Ada Lovelace",
    "email": "ada@example.com",
    "address": "12 Analytical Way",
}


def space_headers(space: str | None) -> dict[str, str]:
    """Request headers that put a request into ``space`` (none for ``default``)."""
    return {SPACE_HEADER: space} if space else {}


def bearer(token: str) -> dict[str, str]:
    """The facilitator's ``Authorization`` header."""
    return {"Authorization": f"Bearer {token}"}


def global_flags() -> dict[str, bool]:
    """The ``feature_flags`` rows as a plain dict."""
    return {key: bool(enabled) for key, enabled in sqlite_rows("SELECT key, enabled FROM feature_flags")}


def assert_denied(response) -> None:
    """The 401 that every guarded operation answers in ``default`` (design D6)."""
    assert response.status_code == 401, response.text
    assert response.headers["WWW-Authenticate"] == "Bearer"
    detail = response.json()["detail"]
    assert detail == WORKSHOP_WRITE_DENIED_MESSAGE
    assert "?space=" in detail
    assert "X-Workshop-Space" in detail


def first_product_id() -> int:
    """The id of a seeded product, for the cart and checkout flows."""
    return int(sqlite_rows("SELECT id FROM products ORDER BY id LIMIT 1")[0][0])


# ---------------------------------------------------------------------------
# The guarded control operations
# ---------------------------------------------------------------------------


def test_a_preset_without_space_or_token_is_denied(app_client, shared_mode) -> None:
    """*Participant forgets the space header*: nothing changes, and 401 explains."""
    before = global_flags()

    response = app_client.post("/api/workshop/preset", json={"preset": "stage2"})

    assert_denied(response)
    assert global_flags() == before


def test_a_participant_space_needs_no_token(app_client, shared_mode) -> None:
    """*Participant uses their space*: their own space is never guarded."""
    response = app_client.post(
        "/api/workshop/preset", json={"preset": "stage2"}, headers=space_headers(OCTOCAT)
    )

    assert response.status_code == 200, response.text
    status = app_client.get("/api/workshop/status", headers=space_headers(OCTOCAT))
    assert status.json()["locator_stage"] == "v2"


def test_the_facilitator_token_opens_the_default_space(app_client, shared_mode) -> None:
    """The token yielded by the fixture is accepted in ``default``."""
    response = app_client.post(
        "/api/workshop/preset", json={"preset": "stage2"}, headers=bearer(shared_mode)
    )

    assert response.status_code == 200, response.text
    assert app_client.get("/api/workshop/status").json()["locator_stage"] == "v2"


def test_a_wrong_token_is_denied(app_client, shared_mode) -> None:
    """A token that does not match is worth no more than no token at all."""
    before = global_flags()

    response = app_client.post(
        "/api/workshop/preset", json={"preset": "stage2"}, headers=bearer(shared_mode + "-wrong")
    )

    assert_denied(response)
    assert global_flags() == before


def test_admin_put_in_the_default_space_is_denied(app_client, shared_mode) -> None:
    """``PUT /api/admin/flags/{key}`` is a control operation too."""
    before = global_flags()

    assert_denied(app_client.put("/api/admin/flags/LOCATOR_V2", json={"enabled": True}))

    assert global_flags() == before


def test_bulk_flags_in_the_default_space_are_denied(app_client, shared_mode) -> None:
    """``POST /api/workshop/flags`` is a control operation too."""
    before = global_flags()

    assert_denied(app_client.post("/api/workshop/flags", json={"flags": {"LOCATOR_V2": True}}))

    assert global_flags() == before


def test_local_mode_needs_no_token_at_all(app_client) -> None:
    """*Local participant applies a preset*: without shared mode nothing is guarded."""
    assert app_client.post("/api/workshop/preset", json={"preset": "stage2"}).status_code == 200
    assert app_client.put("/api/admin/flags/LOCATOR_V3", json={"enabled": True}).status_code == 200
    assert app_client.post(
        "/api/workshop/flags", json={"flags": {"LOCATOR_V4": True}}
    ).status_code == 200


# ---------------------------------------------------------------------------
# What stays open in the default space
# ---------------------------------------------------------------------------


def test_shopping_in_the_default_space_stays_open(app_client, shared_mode, fake_weasyprint) -> None:
    """*Shopping in the default space stays open*: no shop flow answers 401."""
    product_id = first_product_id()

    added = app_client.post("/api/cart/items", json={"product_id": product_id, "quantity": 1})
    assert added.status_code != 401, added.text
    assert added.status_code == 200

    read = app_client.get("/api/cart/")
    assert read.status_code != 401
    assert read.json()["items"], "the guard must not have swallowed the add"

    api_checkout = app_client.post("/api/checkout/", json=CUSTOMER)
    assert api_checkout.status_code != 401, api_checkout.text
    assert api_checkout.status_code == 200

    app_client.post("/api/cart/items", json={"product_id": product_id, "quantity": 1})
    form = app_client.post("/checkout", data=CUSTOMER)
    assert form.status_code != 401, form.text
    assert form.status_code == 200
    assert "confirmed" in form.text

    cleared = app_client.delete("/api/cart/")
    assert cleared.status_code != 401
    assert cleared.status_code == 200


@pytest.mark.parametrize(
    "path", ["/api/workshop/status", "/api/workshop/presets", "/api/admin/flags"]
)
def test_reads_in_the_default_space_stay_open(app_client, shared_mode, path: str) -> None:
    """Reads are never guarded; they only ever show the caller's own space."""
    response = app_client.get(path)

    assert response.status_code == 200, response.text


# ---------------------------------------------------------------------------
# The AI helper on a shared instance
# ---------------------------------------------------------------------------


def configure_real_provider(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Configure OpenAI and replace the HTTP call with a recording stub.

    Returns the list of questions the stub was asked, which stays empty while
    the shop refuses to leave the mock provider.
    """
    monkeypatch.setattr(settings, "ai_provider", "openai")
    monkeypatch.setattr(settings, "ai_api_key", "test")

    asked: list[str] = []

    async def record(self, *, question: str, mode: str, context: str) -> ProductInsight:
        asked.append(question)
        return ProductInsight(product="Live", summary="(Live) answer", price=None, highlights=[])

    monkeypatch.setattr(AIService, "_call_openai_chat", record)
    return asked


def use_live_ai(client, space: str) -> None:
    """Turn ``AI_DETERMINISTIC`` off in ``space``, so only shared mode forces mock."""
    response = client.post(
        "/api/workshop/flags",
        json={"flags": {"AI_DETERMINISTIC": False}},
        headers=space_headers(space),
    )
    assert response.status_code == 200, response.text


def ask(client, space: str) -> dict:
    """``POST /api/ai/ask`` in ``space``, explicitly asking for OpenAI."""
    response = client.post(
        "/api/ai/ask",
        json={"question": "desk", "provider": "openai"},
        headers=space_headers(space),
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_shared_mode_answers_with_the_mock_provider(
    app_client, shared_mode, monkeypatch: pytest.MonkeyPatch
) -> None:
    """*Real AI provider configured*: neither the setting nor the request override wins."""
    asked = configure_real_provider(monkeypatch)
    use_live_ai(app_client, OCTOCAT)

    answer = ask(app_client, OCTOCAT)

    assert answer["provider"] == "mock"
    assert answer["answer"]["summary"].startswith("(Mock)")
    assert asked == []


def test_without_shared_mode_the_configured_provider_is_used(
    app_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control: the same request reaches the provider when shared mode is off."""
    asked = configure_real_provider(monkeypatch)
    use_live_ai(app_client, OCTOCAT)

    answer = ask(app_client, OCTOCAT)

    assert answer["provider"] == "openai"
    assert asked == ["desk"]


# ---------------------------------------------------------------------------
# No endpoint enumerates the other spaces (task 11.2, design D6)
# ---------------------------------------------------------------------------

#: The two other participants whose rows must stay invisible to ``octocat``.
HUBOT = "hubot"
MONA = "mona"

#: The cart session id both of them send, so only the space keeps them apart.
SHARED_SESSION_ID = "demo"

#: Routes that must be in the enumeration list. A later change that hides or
#: renames one of them fails this test instead of quietly shrinking it.
REQUIRED_GET_PATHS = frozenset(
    {
        "/api/workshop/status",
        "/api/workshop/presets",
        "/api/admin/flags",
        "/",
        "/products",
        "/cart",
        "/checkout",
    }
)


def session_headers(space: str) -> dict[str, str]:
    """Space and cart session of one of the two other participants."""
    return {**space_headers(space), "X-Session-ID": SHARED_SESSION_ID}


def collect_api_routes(router, prefix: str = ""):
    """Every ``APIRoute`` reachable from ``router``, with its full path.

    ``app.routes`` is walked rather than ``/openapi.json``, so the routers
    registered with ``include_in_schema=False`` are covered too. FastAPI no
    longer flattens an included router into ``app.routes`` - it appends one
    ``_IncludedRouter`` per ``include_router`` call - so the walk descends into
    a nested router and prepends the prefix it was included under. Both layouts
    are handled, and a ``Mount`` such as ``/static`` has no ``routes`` and is
    skipped.
    """
    from fastapi.routing import APIRoute

    for route in getattr(router, "routes", []):
        if isinstance(route, APIRoute):
            yield prefix + route.path, route
            continue
        nested = getattr(route, "original_router", None) or getattr(route, "app", None)
        if nested is None or not hasattr(nested, "routes"):
            continue
        context = getattr(route, "include_context", None)
        nested_prefix = getattr(context, "prefix", None) or getattr(route, "path", "") or ""
        yield from collect_api_routes(nested, prefix + nested_prefix)


def enumerable_get_paths() -> list[str]:
    """Every parameterless GET route of the application, deduplicated."""
    from backend.app.main import app

    paths = {
        path
        for path, route in collect_api_routes(app)
        if "GET" in (route.methods or set()) and "{" not in path
    }
    return sorted(paths)


def shop_as(client, space: str, *, product_id: int) -> str:
    """Give ``space`` a flag row, a live cart row and an order; return its number.

    The second add is not redundant: ``POST /api/checkout/`` calls
    ``CartService.clear_cart()``, so without it the space would own no cart row
    for the enumeration check to find.
    """
    headers = session_headers(space)

    preset = client.post("/api/workshop/preset", json={"preset": "stage3"}, headers=headers)
    assert preset.status_code == 200, preset.text

    added = client.post(
        "/api/cart/items", json={"product_id": product_id, "quantity": 1}, headers=headers
    )
    assert added.status_code == 200, added.text

    checkout = client.post("/api/checkout/", json=CUSTOMER, headers=headers)
    assert checkout.status_code == 200, checkout.text
    order_number = str(checkout.json()["order"]["order_number"])

    restocked = client.post(
        "/api/cart/items", json={"product_id": product_id, "quantity": 1}, headers=headers
    )
    assert restocked.status_code == 200, restocked.text

    return order_number


def space_row_counts(space: str) -> tuple[int, int, int]:
    """How many flag, cart and order rows ``space`` owns right now."""
    flags = sqlite_rows(
        "SELECT COUNT(*) FROM space_feature_flags WHERE space = ?", (space,)
    )[0][0]
    carts = sqlite_rows(
        "SELECT COUNT(*) FROM cart_items WHERE session_key = ?",
        (f"{space}:{SHARED_SESSION_ID}",),
    )[0][0]
    orders = sqlite_rows("SELECT COUNT(*) FROM orders WHERE space = ?", (space,))[0][0]
    return int(flags), int(carts), int(orders)


def test_no_endpoint_enumerates_another_space(app_client, shared_mode, fake_weasyprint) -> None:
    """*Curious participant*: ``octocat`` cannot read any trace of the others.

    ``hubot`` leaves a flag row, a cart row and an order behind; ``mona`` does
    the same and then resets, so a space whose rows a reset removed is covered
    as well. Every parameterless GET route is then called as ``octocat``, with
    no token, and no response body may mention either of them.
    """
    product_id = first_product_id()

    hubot_order = shop_as(app_client, HUBOT, product_id=product_id)
    shop_as(app_client, MONA, product_id=product_id)
    reset = app_client.post("/api/workshop/reset", headers=space_headers(MONA))
    assert reset.status_code == 200, reset.text

    # There is really something to find at the moment of the calls below, so a
    # later change to checkout, reset or the storage layout cannot make this
    # test pass by leaving the database empty.
    hubot_flags, hubot_carts, hubot_orders = space_row_counts(HUBOT)
    assert hubot_flags >= 1, "hubot must own at least one space flag row"
    assert (hubot_carts, hubot_orders) == (1, 1), "hubot must own a cart row and an order"
    assert space_row_counts(MONA) == (0, 0, 0), "the reset must have emptied mona"

    paths = enumerable_get_paths()
    assert REQUIRED_GET_PATHS <= set(paths), sorted(REQUIRED_GET_PATHS - set(paths))

    forbidden = {
        HUBOT.encode(): HUBOT,
        MONA.encode(): MONA,
        hubot_order.encode(): "hubot's order number",
    }
    leaks: list[tuple[str, int, str]] = []
    for path in paths:
        response = app_client.get(path, headers=space_headers(OCTOCAT))
        # A 4xx - a 422 for a route whose query parameter is missing, say - is
        # a fine answer; it simply carries nothing to leak.
        assert response.status_code < 500, (path, response.text[:200])
        body = response.content
        leaks.extend(
            (path, response.status_code, label)
            for needle, label in forbidden.items()
            if needle in body
        )

    assert leaks == []


def test_no_route_exposes_a_spaces_path(app_client, shared_mode) -> None:
    """There is no listing endpoint: ``spaces`` appears in no route at all."""
    from backend.app.main import app

    paths = [path for path, _ in collect_api_routes(app)]
    paths.extend(getattr(route, "path", "") or "" for route in app.routes)

    assert [path for path in paths if "spaces" in path] == []
