from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models.order import Order, OrderItem
from .pdf_service import PDFService


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


class OrderService:
    def __init__(self, session: AsyncSession, pdf_service: PDFService):
        self.session = session
        self.pdf_service = pdf_service

    async def create_order(
        self,
        customer: CustomerDetails,
        cart_state: dict,
        *,
        user_id: int | None = None,
        shipping_address_id: int | None = None,
        billing_address_id: int | None = None,
        payment_method_id: int | None = None,
    ) -> tuple[Order, List[str]]:
        if not cart_state["items"]:
            raise ValueError("Cart is empty")

        subtotal, tax, total = calculate_totals(cart_state["items"])
        order_number = f"ORD-{uuid4().hex[:8].upper()}"

        order = Order(
            order_number=order_number,
            customer_name=customer.name,
            customer_email=customer.email,
            customer_address=customer.address,
            subtotal=subtotal,
            tax=tax,
            total=total,
            status="processing",
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

        self.session.add(order)
        await self.session.commit()
        
        # Eagerly load the items relationship to prevent MissingGreenlet error
        result = await self.session.execute(
            select(Order).options(selectinload(Order.items)).filter_by(id=order.id)
        )
        order = result.scalars().one()

        documents = await self.generate_documents(order, cart_state)
        return order, documents

    async def generate_documents(self, order: Order, cart_state: dict) -> List[str]:
        customer = {
            "name": order.customer_name,
            "email": order.customer_email,
            "address": order.customer_address,
        }
        items = cart_state["items"]

        order_context = {
            "order_number": order.order_number,
            "order_date": order.created_at.strftime("%Y-%m-%d"),
            "subtotal": order.subtotal,
            "tax": order.tax,
            "total": order.total,
            "status": order.status,
        }

        invoice_path = await self.pdf_service.render_pdf(
            "pdf/invoice.html",
            {
                "order": order_context,
                "customer": customer,
                "items": items,
            },
            f"invoice_{order.order_number}.pdf",
        )

        summary_path = await self.pdf_service.render_pdf(
            "pdf/order_summary.html",
            {
                "order": order_context,
                "customer": customer,
                "items": items,
            },
            f"summary_{order.order_number}.pdf",
        )

        return [str(invoice_path), str(summary_path)]
