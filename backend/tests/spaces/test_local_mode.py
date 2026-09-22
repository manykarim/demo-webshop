"""A local run is unchanged by spaces (task 11.1, design D1, D3, D6 and D8).

The workshop is normally started on a laptop with no shared mode, no token and
no space header. Nothing this change adds may show up there: the control
endpoints stay open, the pages stay clean, the health payload keeps its shape
and the cart keeps writing the unprefixed keys an existing local database
already holds.

``app_client`` runs with ``WORKSHOP_SHARED_MODE=false``, the value the harness
pins for the whole session, so every request below is a local one.
"""
from __future__ import annotations

from backend.app.core.config import settings
from backend.app.core.spaces import SPACE_COOKIE
from backend.tests.spaces.helpers import rendered_stage, sqlite_rows

#: Pages a participant sees locally, all of them in the ``default`` space.
PAGES = ("/", "/products", "/cart", "/checkout")

#: The session id the local participant's tooling sends.
SESSION_ID = "local-session"


def first_product_id() -> int:
    """The id of a seeded product, for the cart flow."""
    return int(sqlite_rows("SELECT id FROM products ORDER BY id LIMIT 1")[0][0])


def test_a_local_participant_applies_a_preset(app_client) -> None:
    """*Local participant applies a preset*: no space, no token, and it works."""
    response = app_client.post("/api/workshop/preset", json={"preset": "stage2"})

    assert response.status_code == 200, response.text
    assert response.json()["current_status"]["locator_stage"] == "v2"

    # The next page request, again without a space, shows the drifted markup.
    products = app_client.get("/products")
    assert products.status_code == 200
    assert rendered_stage(products.text) == "v2"


def test_every_control_endpoint_stays_open_without_credentials(app_client) -> None:
    """Bulk flags, the admin PUT and the reset need nothing in local mode."""
    flags = app_client.post("/api/workshop/flags", json={"flags": {"LOCATOR_V3": True}})
    assert flags.status_code == 200, flags.text

    admin = app_client.put("/api/admin/flags/LOCATOR_V4", json={"enabled": True})
    assert admin.status_code == 200, admin.text
    assert admin.json() == {"flag": "LOCATOR_V4", "enabled": True}

    reset = app_client.post("/api/workshop/reset")
    assert reset.status_code == 200, reset.text
    assert reset.json()["space"] == "default"

    # The reset put the global flags back to the baseline, so the stage the
    # two writes above produced is gone.
    assert app_client.get("/api/workshop/status").json()["locator_stage"] == "v1"


def test_health_is_unchanged(app_client) -> None:
    """``/health`` gained no space field; monitoring keeps working untouched."""
    response = app_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": settings.app_version}


def test_pages_carry_no_space_indicator(app_client) -> None:
    """*Local mode in ``default``*: no indicator, no hint, no cookie (design D8)."""
    for path in PAGES:
        response = app_client.get(path)

        assert response.status_code == 200, path
        assert "data-workshop-space" not in response.text, path
        assert "workshop-space-hint" not in response.text, path
        assert "Shared baseline" not in response.text, path

        cookies = response.headers.get_list("set-cookie")
        assert not any(SPACE_COOKIE in cookie for cookie in cookies), (path, cookies)


def test_cart_rows_keep_the_legacy_unprefixed_keys(app_client) -> None:
    """*Existing local database*: ``default`` writes the plain session id (design D3)."""
    headers = {"X-Session-ID": SESSION_ID}

    added = app_client.post(
        "/api/cart/items",
        json={"product_id": first_product_id(), "quantity": 2},
        headers=headers,
    )
    assert added.status_code == 200, added.text

    # The stored key is the session id itself: no space, no separator.
    assert sqlite_rows("SELECT DISTINCT session_key FROM cart_items") == [(SESSION_ID,)]

    read = app_client.get("/api/cart/", headers=headers)
    assert read.status_code == 200
    assert read.json()["session"] == SESSION_ID
    assert [item["quantity"] for item in read.json()["items"]] == [2]
