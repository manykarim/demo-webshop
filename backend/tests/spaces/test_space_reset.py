"""``POST /api/workshop/reset`` removes exactly what a space created (tasks 8.1
and 8.2, design D7).

Every test builds real state through the public API - presets, carts and
checkouts - and then checks two things after the reset: that the calling space
is back at the baseline, and that no other space, no seeded order and no other
space's documents were touched. ``fake_weasyprint`` makes the checkouts write
``invoice_<order_number>.pdf`` and ``summary_<order_number>.pdf`` into the
temporary ``pdf_output_dir`` of the harness, so the document cleanup is covered
without native PDF libraries.
"""
from __future__ import annotations

from pathlib import Path

from backend.app.core.config import settings
from backend.app.core.feature_flags import baseline_flags
from backend.app.core.spaces import SPACE_HEADER
from backend.tests.spaces.helpers import rendered_stage, sqlite_rows

#: Two participant spaces, and the prefix that must never match the first one.
OCTOCAT = "octocat"
HUBOT = "hubot"
OCTO = "octo"

#: A valid checkout payload.
CUSTOMER = {
    "name": "Ada Lovelace",
    "email": "ada@example.com",
    "address": "12 Analytical Way",
}


def space_headers(space: str | None, session_id: str | None = None) -> dict[str, str]:
    """Headers that put a request into ``space`` with an optional session id."""
    headers: dict[str, str] = {}
    if space:
        headers[SPACE_HEADER] = space
    if session_id:
        headers["X-Session-ID"] = session_id
    return headers


def bearer(token: str) -> dict[str, str]:
    """The facilitator's ``Authorization`` header."""
    return {"Authorization": f"Bearer {token}"}


def first_product_id() -> int:
    """The id of a seeded product."""
    return int(sqlite_rows("SELECT id FROM products ORDER BY id LIMIT 1")[0][0])


def apply_preset(client, preset: str, space: str | None = None, token: str | None = None) -> None:
    """``POST /api/workshop/preset`` in ``space``, asserting it was applied."""
    headers = space_headers(space)
    if token:
        headers.update(bearer(token))
    response = client.post("/api/workshop/preset", json={"preset": preset}, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "success", response.text


def add_to_cart(client, space: str | None, session_id: str | None = None) -> None:
    """Put one seeded product into the cart of ``space``/``session_id``."""
    response = client.post(
        "/api/cart/items",
        json={"product_id": first_product_id(), "quantity": 1},
        headers=space_headers(space, session_id),
    )
    assert response.status_code == 200, response.text


def api_checkout(client, space: str | None, session_id: str = "demo") -> str:
    """Check out in ``space`` and return the order number of the new order."""
    add_to_cart(client, space, session_id)
    response = client.post(
        "/api/checkout/", json=CUSTOMER, headers=space_headers(space, session_id)
    )
    assert response.status_code == 200, response.text
    return str(response.json()["order"]["order_number"])


def reset(client, space: str | None = None, token: str | None = None):
    """``POST /api/workshop/reset`` in ``space``."""
    headers = space_headers(space)
    if token:
        headers.update(bearer(token))
    return client.post("/api/workshop/reset", headers=headers)


def status(client, space: str | None = None) -> dict:
    """``GET /api/workshop/status`` of ``space``."""
    response = client.get("/api/workshop/status", headers=space_headers(space))
    assert response.status_code == 200, response.text
    return response.json()


def page_stage(client, space: str | None = None) -> str:
    """The locator stage the product listing renders in ``space``."""
    response = client.get("/products", headers=space_headers(space))
    assert response.status_code == 200, response.text
    return rendered_stage(response.text)


# ---------------------------------------------------------------------------
# State read straight from the database, so nothing is hidden by an API filter
# ---------------------------------------------------------------------------


def documents(order_number: str) -> list[Path]:
    """The two document paths a checkout writes for ``order_number``."""
    output_dir = Path(settings.pdf_output_dir)
    return [
        output_dir / f"invoice_{order_number}.pdf",
        output_dir / f"summary_{order_number}.pdf",
    ]


def cart_keys(pattern: str) -> list[str]:
    """The ``cart_items.session_key`` values matching the SQL ``pattern``."""
    return [
        str(row[0])
        for row in sqlite_rows(
            "SELECT session_key FROM cart_items WHERE session_key LIKE ?", (pattern,)
        )
    ]


def flag_rows(space: str) -> list[tuple]:
    """The ``space_feature_flags`` rows of ``space``."""
    return sqlite_rows("SELECT key, enabled FROM space_feature_flags WHERE space = ?", (space,))


def global_flags() -> dict[str, bool]:
    """The global ``feature_flags`` rows as a plain dict."""
    return {
        str(key): bool(enabled)
        for key, enabled in sqlite_rows("SELECT key, enabled FROM feature_flags")
    }


def order_ids(space: str) -> list[int]:
    """The ids of the runtime orders stored for ``space``."""
    return [int(row[0]) for row in sqlite_rows("SELECT id FROM orders WHERE space = ?", (space,))]


def order_item_count(ids: list[int]) -> int:
    """The number of ``order_items`` rows belonging to ``ids``."""
    if not ids:
        return 0
    placeholders = ", ".join("?" for _ in ids)
    return int(
        sqlite_rows(f"SELECT COUNT(*) FROM order_items WHERE order_id IN ({placeholders})", ids)[0][0]
    )


def seeded_order_count() -> int:
    """The number of seeded demo orders, which carry no space."""
    return int(sqlite_rows("SELECT COUNT(*) FROM orders WHERE space IS NULL")[0][0])


def build_state(client) -> dict:
    """The starting point of the *Reset one space* scenario.

    ``default`` runs stage 3 with every bug on, ``octocat`` runs stage 2 with
    ``NEW_CART_UI`` on (so the reset has a flag to undo that no preset owns),
    two carts and one runtime order, and ``hubot`` runs stage 3 with a cart and
    a runtime order. The checkout empties the cart it used, so the carts are
    filled afterwards.
    """
    apply_preset(client, "stage3")
    apply_preset(client, "buggy")

    apply_preset(client, "stage2", space=OCTOCAT)
    flags = client.post(
        "/api/workshop/flags",
        json={"flags": {"NEW_CART_UI": True}},
        headers=space_headers(OCTOCAT),
    )
    assert flags.status_code == 200, flags.text
    octocat_order = api_checkout(client, OCTOCAT)
    add_to_cart(client, OCTOCAT, "demo")
    add_to_cart(client, OCTOCAT)  # no X-Session-ID: the shared fallback id

    apply_preset(client, "stage3", space=HUBOT)
    hubot_order = api_checkout(client, HUBOT)
    add_to_cart(client, HUBOT, "demo")

    state = {
        "octocat_order": octocat_order,
        "hubot_order": hubot_order,
        "octocat_order_ids": order_ids(OCTOCAT),
        "octocat_flag_rows": len(flag_rows(OCTOCAT)),
        "octocat_cart_keys": sorted(cart_keys(f"{OCTOCAT}:%")),
        "seeded_orders": seeded_order_count(),
    }

    # The scenario is only worth running if the state really exists.
    assert state["octocat_cart_keys"] == [f"{OCTOCAT}:demo", f"{OCTOCAT}:workshop-demo"]
    assert state["octocat_flag_rows"] == 4
    assert len(state["octocat_order_ids"]) == 1
    assert order_item_count(state["octocat_order_ids"]) > 0
    assert all(path.exists() for path in documents(octocat_order))
    assert all(path.exists() for path in documents(hubot_order))
    return state


# ---------------------------------------------------------------------------
# Task 8.1 - resetting one participant space
# ---------------------------------------------------------------------------


def test_resetting_a_space_returns_it_to_the_baseline(seeded_app_client, fake_weasyprint) -> None:
    """*Reset one space*: flags, carts, orders and documents of that space go."""
    state = build_state(seeded_app_client)

    response = reset(seeded_app_client, OCTOCAT)

    assert response.status_code == 200, response.text
    assert response.json()["space"] == OCTOCAT

    assert page_stage(seeded_app_client, OCTOCAT) == "v1"
    octocat_status = status(seeded_app_client, OCTOCAT)
    assert octocat_status["locator_stage"] == "v1"
    assert octocat_status["active_bugs"] == []
    assert octocat_status["all_flags"]["NEW_CART_UI"] is False
    assert flag_rows(OCTOCAT) == []

    for session_id in (None, "demo"):
        cart = seeded_app_client.get("/api/cart/", headers=space_headers(OCTOCAT, session_id))
        assert cart.status_code == 200, cart.text
        assert cart.json()["items"] == []
    assert cart_keys(f"{OCTOCAT}:%") == []

    assert order_ids(OCTOCAT) == []
    assert order_item_count(state["octocat_order_ids"]) == 0
    assert [path.name for path in documents(state["octocat_order"]) if path.exists()] == []


def test_resetting_a_space_leaves_every_other_space_alone(
    seeded_app_client, fake_weasyprint
) -> None:
    """The reset of one space is invisible in ``hubot``, ``default`` and the seeds."""
    state = build_state(seeded_app_client)

    assert reset(seeded_app_client, OCTOCAT).status_code == 200

    assert page_stage(seeded_app_client, HUBOT) == "v3"
    assert status(seeded_app_client, HUBOT)["locator_stage"] == "v3"
    assert cart_keys(f"{HUBOT}:%") == [f"{HUBOT}:demo"]
    assert len(order_ids(HUBOT)) == 1
    assert all(path.exists() for path in documents(state["hubot_order"]))

    assert page_stage(seeded_app_client) == "v3"
    assert status(seeded_app_client)["locator_stage"] == "v3"
    assert seeded_order_count() == state["seeded_orders"]


def test_a_shorter_space_never_matches_a_longer_ones_carts(
    seeded_app_client, fake_weasyprint
) -> None:
    """``octo`` resets only ``octo:%``; ``octocat:%`` is a different prefix."""
    state = build_state(seeded_app_client)

    response = reset(seeded_app_client, OCTO)

    assert response.status_code == 200, response.text
    assert response.json()["removed_cart_items"] == 0
    assert sorted(cart_keys(f"{OCTOCAT}:%")) == state["octocat_cart_keys"]
    assert len(order_ids(OCTOCAT)) == 1


def test_the_response_counts_match_the_removed_rows(seeded_app_client, fake_weasyprint) -> None:
    """The three counts report exactly what disappeared from the database."""
    state = build_state(seeded_app_client)

    body = reset(seeded_app_client, OCTOCAT).json()

    assert body["removed_flags"] == state["octocat_flag_rows"] == 4
    assert body["removed_cart_items"] == len(state["octocat_cart_keys"]) == 2
    assert body["removed_orders"] == len(state["octocat_order_ids"]) == 1
    assert body["locator_stage"] == "v1"
    assert body["active_bugs"] == []
    assert body["ai_mode"] == "deterministic"


# ---------------------------------------------------------------------------
# Task 8.2 - resetting the default space
# ---------------------------------------------------------------------------


def build_default_state(client, token: str | None = None) -> dict:
    """Stage 2, ``NEW_CART_UI``, a legacy cart and a runtime order in ``default``.

    ``octocat`` gets the same kind of state, so every assertion about what a
    ``default`` reset must not touch has something to fail on. ``token`` is the
    facilitator token needed to write the ``default`` flags on a shared
    instance; carts and checkout are open there and never send it.
    """
    apply_preset(client, "stage2", token=token)
    flag_headers = bearer(token) if token else {}
    flags = client.post(
        "/api/workshop/flags", json={"flags": {"NEW_CART_UI": True}}, headers=flag_headers
    )
    assert flags.status_code == 200, flags.text

    default_order = api_checkout(client, None)
    add_to_cart(client, None, "legacy")
    add_to_cart(client, None)  # the shared fallback id, still without a prefix

    apply_preset(client, "stage3", space=OCTOCAT)
    octocat_order = api_checkout(client, OCTOCAT)
    add_to_cart(client, OCTOCAT, "demo")

    state = {
        "default_order": default_order,
        "octocat_order": octocat_order,
        "default_order_ids": order_ids("default"),
        "seeded_orders": seeded_order_count(),
    }

    assert sorted(cart_keys("%")) == ["legacy", f"{OCTOCAT}:demo", "workshop-demo"]
    assert len(state["default_order_ids"]) == 1
    assert global_flags() != baseline_flags()
    assert all(path.exists() for path in documents(default_order))
    assert all(path.exists() for path in documents(octocat_order))
    return state


def test_a_default_reset_restores_the_global_state(seeded_app_client, fake_weasyprint) -> None:
    """In local mode the ``default`` reset needs no credentials and restores the baseline."""
    state = build_default_state(seeded_app_client)
    changed_flags = sum(
        1 for key, value in baseline_flags().items() if global_flags().get(key) != value
    )

    response = reset(seeded_app_client)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["space"] == "default"
    # No flag row is removed in ``default``: the count reports the global rows
    # whose value the reset wrote back to the baseline (LOCATOR_V2, NEW_CART_UI).
    assert body["removed_flags"] == changed_flags == 2
    assert body["removed_cart_items"] == 2
    assert body["removed_orders"] == 1

    assert global_flags() == baseline_flags()
    assert status(seeded_app_client)["locator_stage"] == "v1"
    assert page_stage(seeded_app_client) == "v1"

    assert cart_keys("%") == [f"{OCTOCAT}:demo"]
    assert order_ids("default") == []
    assert order_item_count(state["default_order_ids"]) == 0
    assert [path.name for path in documents(state["default_order"]) if path.exists()] == []

    assert len(order_ids(OCTOCAT)) == 1
    assert all(path.exists() for path in documents(state["octocat_order"]))
    assert status(seeded_app_client, OCTOCAT)["locator_stage"] == "v3"
    assert seeded_order_count() == state["seeded_orders"]


def test_the_default_reset_is_guarded_on_a_shared_instance(
    seeded_app_client, fake_weasyprint, shared_mode
) -> None:
    """*Default-space reset without token*: 401, nothing removed, and a way out."""
    state = build_default_state(seeded_app_client, token=shared_mode)
    carts_before = sorted(cart_keys("%"))
    flags_before = global_flags()

    denied = reset(seeded_app_client)

    assert denied.status_code == 401, denied.text
    assert denied.headers["WWW-Authenticate"] == "Bearer"
    assert sorted(cart_keys("%")) == carts_before
    assert global_flags() == flags_before
    assert order_ids("default") == state["default_order_ids"]

    # A participant space is never guarded, ...
    assert reset(seeded_app_client, OCTOCAT).status_code == 200
    # ... and the facilitator token opens the default space.
    assert reset(seeded_app_client, token=shared_mode).status_code == 200
    assert global_flags() == baseline_flags()
    assert order_ids("default") == []
