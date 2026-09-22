"""Unit tests for the shared PDF render context (design D8).

Both order documents are rendered from ``build_document_context``. These tests
render the real templates with a strict Jinja environment, so a key the
templates need but the context does not provide fails here instead of only in a
container with WeasyPrint installed. No native libraries are involved.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from backend.app.models import Order, OrderItem
from backend.app.services.order_service import build_document_context

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "app" / "templates"

CUSTOMER_NAME = "Ada Lovelace"
ORDER_DATE = "2024-05-17"
TAX = 10.5


@pytest.fixture
def order() -> Order:
    """A transient order with two items, as ``build_order`` returns one.

    ``created_at`` is set by hand: the column default is applied on insert, and
    this order is never inserted.
    """
    order = Order(
        order_number="ORD-CTX00001",
        customer_name=CUSTOMER_NAME,
        customer_email="ada@example.com",
        customer_address="1 Analytical Way, London",
        subtotal=150.0,
        tax=TAX,
        total=160.5,
        status="processing",
    )
    order.created_at = datetime(2024, 5, 17, 9, 30, 0)
    order.items.append(
        OrderItem(
            product_id=1,
            product_name="Flowline Pressure Sensor",
            quantity=2,
            unit_price=50.0,
            total_price=100.0,
        )
    )
    order.items.append(
        OrderItem(
            product_id=2,
            product_name="Flowline Control Valve",
            quantity=1,
            unit_price=50.0,
            total_price=50.0,
        )
    )
    return order


@pytest.fixture
def environment() -> Environment:
    return Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), undefined=StrictUndefined)


def test_context_describes_the_order_the_customer_and_the_items(order):
    context = build_document_context(order)

    assert context["order"] == {
        "order_number": "ORD-CTX00001",
        "order_date": ORDER_DATE,
        "subtotal": 150.0,
        "tax": TAX,
        "total": 160.5,
        "status": "processing",
    }
    assert context["customer"] == {
        "name": CUSTOMER_NAME,
        "email": "ada@example.com",
        "address": "1 Analytical Way, London",
    }
    assert context["items"] == [
        {
            "product_id": 1,
            "name": "Flowline Pressure Sensor",
            "quantity": 2,
            "unit_price": 50.0,
            "total_price": 100.0,
            "image_url": "",
        },
        {
            "product_id": 2,
            "name": "Flowline Control Valve",
            "quantity": 1,
            "unit_price": 50.0,
            "total_price": 50.0,
            "image_url": "",
        },
    ]


@pytest.mark.parametrize("template_name", ["pdf/invoice.html", "pdf/order_summary.html"])
def test_both_templates_render_strictly_from_the_shared_context(order, environment, template_name):
    html = environment.get_template(template_name).render(build_document_context(order))

    assert CUSTOMER_NAME in html
    assert ORDER_DATE in html
    assert f"{TAX:.2f}" in html
    assert "Flowline Pressure Sensor" in html
    assert "Flowline Control Valve" in html


def test_summary_keeps_an_empty_image_source(order, environment):
    """``image_url`` is empty, which keeps today's empty ``src`` attribute."""
    html = environment.get_template("pdf/order_summary.html").render(build_document_context(order))

    assert 'src=""' in html
