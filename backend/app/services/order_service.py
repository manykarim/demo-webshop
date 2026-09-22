from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, List, Tuple
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from ..models.order import Order, OrderItem
from .pdf_service import PDFRenderingUnavailable, PDFService


def order_visible_in(space: str) -> ColumnElement[bool]:
    """The one visibility rule for orders (design D5).

    ``space IS NULL OR space = :space``: seeded demo history carries no space
    and stays visible everywhere, while an order created at runtime is only
    visible in the space that created it - including ``default``. Every place
    that reads orders for a client applies this predicate, so an invoice of
    another participant answers 404 rather than leaking.
    """
    return or_(Order.space.is_(None), Order.space == space)


@dataclass
class CustomerDetails:
    name: str
    email: str
    address: str


def calculate_totals(items: List[dict], tax_rate: float = 0.07) -> Tuple[float, float, float]:
    """Return subtotal, tax, and total for given cart items.

    >>> items = [{"total_price": 120.0}, {"total_price": 30.0}]
    >>> calculate_totals(items, tax_rate=0.1)
    (150.0, 15.0, 165.0)
    """
    subtotal = round(sum(item["total_price"] for item in items), 2)
    tax = round(subtotal * tax_rate, 2)
    total = round(subtotal + tax, 2)
    return subtotal, tax, total


def checkout_summary(cart_state: Mapping[str, Any]) -> dict[str, float]:
    """The amounts the checkout page shows for ``cart_state`` (design D10).

    The same :func:`calculate_totals` and the same default tax rate as
    :meth:`OrderService.create_order`, so the summary a shopper reads can never
    disagree with the order that is created from the same cart. The planted
    defect is applied on top of this result by ``BugView.checkout_total``, never
    here: the order and its documents stay correct.

    >>> checkout_summary({"items": [{"total_price": 39.5}, {"total_price": 39.5}]})
    {'subtotal': 79.0, 'tax': 5.53, 'total': 84.53}
    """
    subtotal, tax, total = calculate_totals(list(cart_state["items"]))
    return {"subtotal": subtotal, "tax": tax, "total": total}


def build_order(
    customer: CustomerDetails,
    cart_state: dict,
    *,
    space: str | None = None,
    user_id: int | None = None,
    shipping_address_id: int | None = None,
    billing_address_id: int | None = None,
    payment_method_id: int | None = None,
    status: str = "processing",
) -> Order:
    """Build an unsaved :class:`Order` with its items (design D8).

    The order is neither added to a session nor committed, and no ``PDFService``
    is involved. That is what lets seeding (design D4) build its order history
    without an :class:`OrderService`, whose constructor requires a renderer,
    and without rendering any document.
    """
    subtotal, tax, total = calculate_totals(cart_state["items"])

    order = Order(
        order_number=f"ORD-{uuid4().hex[:8].upper()}",
        customer_name=customer.name,
        customer_email=customer.email,
        customer_address=customer.address,
        subtotal=subtotal,
        tax=tax,
        total=total,
        status=status,
        space=space,
        user_id=user_id,
        shipping_address_id=shipping_address_id,
        billing_address_id=billing_address_id,
        payment_method_id=payment_method_id,
    )

    for item in cart_state["items"]:
        order.items.append(
            OrderItem(
                product_id=item["product_id"],
                product_name=item["name"],
                quantity=item["quantity"],
                unit_price=item["unit_price"],
                total_price=item["total_price"],
            )
        )

    return order


def build_document_context(order: Order) -> dict:
    """The render context shared by the invoice and the summary (design D8).

    Built from a persisted ``order`` whose ``items`` are loaded, so a document
    rendered on demand in ``api/docs.py`` is identical to the one rendered at
    checkout and the two templates can no longer drift apart. ``image_url`` is
    an empty string, which keeps today's empty ``src`` in ``order_summary.html``.
    """
    return {
        "order": {
            "order_number": order.order_number,
            "order_date": order.created_at.strftime("%Y-%m-%d"),
            "subtotal": order.subtotal,
            "tax": order.tax,
            "total": order.total,
            "status": order.status,
        },
        "customer": {
            "name": order.customer_name,
            "email": order.customer_email,
            "address": order.customer_address,
        },
        "items": [
            {
                "product_id": item.product_id,
                "name": item.product_name,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "total_price": item.total_price,
                "image_url": "",
            }
            for item in order.items
        ],
    }


class OrderService:
    def __init__(self, session: AsyncSession, pdf_service: PDFService):
        self.session = session
        self.pdf_service = pdf_service

    async def create_order(
        self,
        customer: CustomerDetails,
        cart_state: dict,
        *,
        space: str | None = None,
        user_id: int | None = None,
        shipping_address_id: int | None = None,
        billing_address_id: int | None = None,
        payment_method_id: int | None = None,
    ) -> tuple[Order, List[str]]:
        if not cart_state["items"]:
            raise ValueError("Cart is empty")

        order = build_order(
            customer,
            cart_state,
            space=space,
            user_id=user_id,
            shipping_address_id=shipping_address_id,
            billing_address_id=billing_address_id,
            payment_method_id=payment_method_id,
        )

        self.session.add(order)
        await self.session.commit()
        
        # Eagerly load the items relationship to prevent MissingGreenlet error
        result = await self.session.execute(
            select(Order).options(selectinload(Order.items)).filter_by(id=order.id)
        )
        order = result.scalars().one()

        try:
            documents = await self.generate_documents(order)
        except PDFRenderingUnavailable:
            # The order is committed and confirmed; only its documents are
            # missing (design D8). Any other rendering error propagates, so a
            # real PDF defect is never hidden.
            documents = []
        return order, documents

    async def generate_documents(self, order: Order) -> List[str]:
        context = build_document_context(order)

        invoice_path = await self.pdf_service.render_pdf(
            "pdf/invoice.html",
            context,
            f"invoice_{order.order_number}.pdf",
        )

        summary_path = await self.pdf_service.render_pdf(
            "pdf/order_summary.html",
            context,
            f"summary_{order.order_number}.pdf",
        )

        return [str(invoice_path), str(summary_path)]
