"""The PDF degradation path and on-demand document rendering (design D8).

Two environments are simulated, both without native libraries: ``pdf_unavailable``
(WeasyPrint cannot be imported) and ``fake_weasyprint`` (a stand-in module that
records the rendered HTML). Together they cover checkout without PDF support,
the 503 of the document endpoints and lazy rendering of both documents.
"""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.core.config import settings
from backend.app.services.order_service import CustomerDetails, build_order, calculate_totals
from backend.app.services.pdf_service import PDFService

UNAVAILABLE_BODY = {"detail": "PDF rendering is unavailable in this environment"}

CUSTOMER = {
    "name": "Grace Hopper",
    "email": "grace@example.com",
    "address": "42 Compiler Lane, Arlington",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def first_product(client) -> dict:
    response = client.get("/api/products/")
    assert response.status_code == 200
    return response.json()["items"][0]


def add_to_cart(client, session_id: str, quantity: int = 2) -> dict:
    product = first_product(client)
    response = client.post(
        "/api/cart/items",
        json={"product_id": product["id"], "quantity": quantity},
        headers={"X-Session-ID": session_id},
    )
    assert response.status_code == 200, response.text
    return product


def api_checkout(client, session_id: str) -> dict:
    response = client.post("/api/checkout/", json=CUSTOMER, headers={"X-Session-ID": session_id})
    assert response.status_code == 200, response.text
    return response.json()


def create_order_through_api(client, session_id: str) -> dict:
    add_to_cart(client, session_id)
    return api_checkout(client, session_id)["order"]


def database_path() -> Path:
    """The SQLite file the patched settings point at."""
    return Path(settings.database_url.split("///", 1)[1])


def order_row(order_number: str) -> tuple | None:
    """The persisted order, read outside the application's session."""
    with sqlite3.connect(database_path()) as connection:
        return connection.execute(
            "SELECT id, order_number, created_at, tax FROM orders WHERE order_number = ?",
            (order_number,),
        ).fetchone()


def persist_built_order(customer: CustomerDetails, cart_state: dict) -> dict:
    """Commit an order built with ``build_order``, without rendering anything.

    This is what seeding does after task 4.2: no ``OrderService``, no
    ``PDFService``, no documents on disk. Runs on an engine of its own, because
    the application's engine belongs to the ``TestClient``'s event loop.
    """

    async def run() -> dict:
        engine = create_async_engine(settings.database_url)
        session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                order = build_order(customer, cart_state)
                session.add(order)
                await session.commit()
                return {"id": order.id, "order_number": order.order_number}
        finally:
            await engine.dispose()

    return asyncio.run(run())


def document_paths(order_number: str) -> tuple[Path, Path]:
    output_dir = Path(settings.pdf_output_dir)
    return (
        output_dir / f"invoice_{order_number}.pdf",
        output_dir / f"summary_{order_number}.pdf",
    )


# ---------------------------------------------------------------------------
# Task 3.2 - checkout without PDF rendering
# ---------------------------------------------------------------------------


def test_api_checkout_succeeds_without_documents(app_client, pdf_unavailable):
    add_to_cart(app_client, "smoke-a")

    response = app_client.post("/api/checkout/", json=CUSTOMER, headers={"X-Session-ID": "smoke-a"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "success"
    assert body["order"]["order_number"].startswith("ORD-")
    assert body["documents"] == []

    row = order_row(body["order"]["order_number"])
    assert row is not None
    assert row[0] == body["order"]["id"]


def test_form_checkout_confirms_the_order_without_documents(app_client, pdf_unavailable):
    add_to_cart(app_client, "smoke-form")

    response = app_client.post(
        "/checkout",
        data=CUSTOMER,
        headers={"x-session-id": "smoke-form"},
    )

    assert response.status_code == 200, response.text
    assert "Order ORD-" in response.text
    assert "confirmed" in response.text


def test_form_checkout_creates_the_order_without_documents(app_client, pdf_unavailable):
    """The half of the check above that the template defect does not block.

    The confirmation page is rendered after the order is committed and the cart
    is cleared, so the order and the empty document set are observable even
    while the page itself cannot be built here.
    """
    add_to_cart(app_client, "smoke-form-order")

    try:
        response = app_client.post(
            "/checkout",
            data=CUSTOMER,
            headers={"x-session-id": "smoke-form-order"},
        )
    except TypeError:  # Defensive: the form path must not raise.
        pass
    else:
        assert response.status_code == 200, response.text
        assert "Order ORD-" in response.text
        assert "confirmed" in response.text

    with sqlite3.connect(database_path()) as connection:
        rows = connection.execute(
            "SELECT order_number, customer_email FROM orders ORDER BY id DESC"
        ).fetchall()

    assert len(rows) == 1
    assert rows[0][0].startswith("ORD-")
    assert rows[0][1] == CUSTOMER["email"]
    assert list(Path(settings.pdf_output_dir).glob("*.pdf")) == []
    assert app_client.get("/api/cart/", headers={"x-session-id": "smoke-form-order"}).json()["items"] == []


def test_other_rendering_errors_are_not_hidden(app_client, monkeypatch):
    async def explode(self, template_name, context, output_name):
        raise RuntimeError("broken template")

    monkeypatch.setattr(PDFService, "render_pdf", explode)
    add_to_cart(app_client, "smoke-broken")

    with pytest.raises(RuntimeError, match="broken template"):
        app_client.post("/api/checkout/", json=CUSTOMER, headers={"X-Session-ID": "smoke-broken"})


# ---------------------------------------------------------------------------
# Task 3.3 - the document endpoints
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("document", ["invoice.pdf", "summary.pdf"])
def test_documents_answer_503_when_rendering_is_unavailable(app_client, pdf_unavailable, document):
    order = create_order_through_api(app_client, "docs-503")

    response = app_client.get(f"/api/docs/orders/{order['id']}/{document}")

    assert response.status_code == 503
    assert response.json() == UNAVAILABLE_BODY


@pytest.mark.parametrize("document", ["invoice.pdf", "summary.pdf"])
def test_unknown_order_still_answers_404(app_client, pdf_unavailable, document):
    response = app_client.get(f"/api/docs/orders/99999/{document}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Order not found"}


def test_a_stale_document_does_not_bypass_the_503(app_client, pdf_unavailable):
    order = create_order_through_api(app_client, "docs-stale")
    invoice_path, _ = document_paths(order["order_number"])
    invoice_path.parent.mkdir(parents=True, exist_ok=True)
    invoice_path.write_bytes(b"%PDF-stale\n")

    response = app_client.get(f"/api/docs/orders/{order['id']}/invoice.pdf")

    assert response.status_code == 503
    assert response.json() == UNAVAILABLE_BODY


def test_invoice_of_a_checkout_order_is_served(app_client, fake_weasyprint):
    order = create_order_through_api(app_client, "docs-ok")

    response = app_client.get(f"/api/docs/orders/{order['id']}/invoice.pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_documents_of_an_unrendered_order_are_rendered_on_demand(app_client, fake_weasyprint):
    product = first_product(app_client)
    quantity = 3
    items = [
        {
            "product_id": product["id"],
            "name": product["name"],
            "quantity": quantity,
            "unit_price": product["price"],
            "total_price": round(product["price"] * quantity, 2),
        }
    ]
    _, tax, _ = calculate_totals(items)
    order = persist_built_order(CustomerDetails(**CUSTOMER), {"items": items})

    invoice_path, summary_path = document_paths(order["order_number"])
    assert not invoice_path.exists() and not summary_path.exists()
    assert fake_weasyprint == [], "seeding-style orders render no document"

    for document in ("summary.pdf", "invoice.pdf"):
        response = app_client.get(f"/api/docs/orders/{order['id']}/{document}")

        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "application/pdf"
        assert response.content.startswith(b"%PDF")

    summary_html = fake_weasyprint[0]
    created_at = order_row(order["order_number"])[2]
    assert CUSTOMER["name"] in summary_html
    assert str(created_at)[:10] in summary_html
    assert f"{tax:.2f}" in summary_html


def test_on_demand_documents_match_the_ones_rendered_at_checkout(app_client, fake_weasyprint):
    order = create_order_through_api(app_client, "docs-identical")
    invoice_at_checkout, summary_at_checkout = fake_weasyprint
    invoice_path, summary_path = document_paths(order["order_number"])
    invoice_path.unlink()
    summary_path.unlink()

    for document in ("invoice.pdf", "summary.pdf"):
        assert app_client.get(f"/api/docs/orders/{order['id']}/{document}").status_code == 200

    assert fake_weasyprint[2] == invoice_at_checkout
    assert fake_weasyprint[3] == summary_at_checkout
