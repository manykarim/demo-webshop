"""No shared cache may store a space-dependent response (change fix-cdn-caching).

The shared Coolify instance runs behind Cloudflare, which served one space's
order invoice to every other space from its cache.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

NO_SHARED_CACHE = "private, no-store"
APP_JS = Path(__file__).resolve().parents[2] / "app" / "static" / "app.js"

DYNAMIC_PATHS = [
    "/",
    "/products",
    "/cart",
    "/checkout",
    "/api/products/",
    "/api/workshop/status",
    "/api/cart/",
    "/search/results?query=desk",
]


def place_order(client) -> int:
    session = {"X-Session-ID": "cache-headers"}
    added = client.post("/api/cart/items", json={"product_id": 1, "quantity": 1}, headers=session)
    assert added.status_code in (200, 201), added.text
    checkout = client.post(
        "/api/checkout/",
        json={"email": "cache@example.com", "name": "Cache Test", "address": "1 Cache Street, Test City"},
        headers=session,
    )
    assert checkout.status_code == 200, checkout.text
    return checkout.json()["order"]["id"]


@pytest.mark.parametrize("path", DYNAMIC_PATHS)
def test_dynamic_responses_forbid_shared_caches(app_client, path: str) -> None:
    response = app_client.get(path)
    assert response.status_code == 200, response.text
    assert response.headers.get("cache-control") == NO_SHARED_CACHE


@pytest.mark.parametrize("document", ["invoice.pdf", "summary.pdf"])
def test_order_documents_forbid_shared_caches(app_client, fake_weasyprint, document: str) -> None:
    order_id = place_order(app_client)
    response = app_client.get(f"/api/docs/orders/{order_id}/{document}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers.get("cache-control") == NO_SHARED_CACHE


@pytest.mark.parametrize("document", ["invoice.pdf", "summary.pdf"])
def test_missing_order_document_forbids_shared_caches(app_client, document: str) -> None:
    response = app_client.get(f"/api/docs/orders/99999/{document}")
    assert response.status_code == 404
    assert response.headers.get("cache-control") == NO_SHARED_CACHE


def test_unavailable_document_forbids_shared_caches(app_client, pdf_unavailable) -> None:
    order_id = place_order(app_client)
    response = app_client.get(f"/api/docs/orders/{order_id}/invoice.pdf")
    assert response.status_code == 503
    assert response.headers.get("cache-control") == NO_SHARED_CACHE


def test_static_assets_keep_their_caching(app_client) -> None:
    script = app_client.get("/static/app.js")
    assert script.status_code == 200
    assert "cache-control" not in script.headers

    stylesheet = re.search(r'href="(/assets/styles\.[0-9a-f]+\.css)"', app_client.get("/").text)
    assert stylesheet, "the page links no per-stage stylesheet"
    styles = app_client.get(stylesheet.group(1))
    assert styles.status_code == 200
    assert styles.headers.get("cache-control") == "public, max-age=31536000, immutable"


def test_script_url_follows_its_content(app_client) -> None:
    digest = hashlib.sha256(APP_JS.read_bytes()).hexdigest()[:16]
    html = app_client.get("/").text
    assert f'src="/static/app.js?v={digest}"' in html
    assert 'src="/static/app.js"' not in html
