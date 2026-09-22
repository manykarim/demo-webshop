from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .product import Product


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    customer_name: Mapped[str] = mapped_column(String(120), nullable=False)
    customer_email: Mapped[str] = mapped_column(String(120), nullable=False)
    customer_address: Mapped[str] = mapped_column(String(255), nullable=False)
    subtotal: Mapped[float] = mapped_column(Float, nullable=False)
    tax: Mapped[float] = mapped_column(Float, nullable=False)
    total: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="processing")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # The workshop space that placed the order (design D3). NULL marks seeded
    # demo history, which stays visible in every space; a runtime checkout
    # always stores its space, including "default".
    space: Mapped[str | None] = mapped_column(String(39), nullable=True, index=True)

    shipping_address_id: Mapped[int | None] = mapped_column(ForeignKey("addresses.id", ondelete="SET NULL"), nullable=True)
    billing_address_id: Mapped[int | None] = mapped_column(ForeignKey("addresses.id", ondelete="SET NULL"), nullable=True)
    payment_method_id: Mapped[int | None] = mapped_column(ForeignKey("payment_methods.id", ondelete="SET NULL"), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="orders")
    shipping_address: Mapped["Address"] = relationship("Address", foreign_keys=[shipping_address_id])
    billing_address: Mapped["Address"] = relationship("Address", foreign_keys=[billing_address_id])
    payment_method: Mapped["PaymentMethod"] = relationship("PaymentMethod")
    items: Mapped[list["OrderItem"]] = relationship("OrderItem", cascade="all, delete-orphan", back_populates="order")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "order_number": self.order_number,
            "customer_name": self.customer_name,
            "customer_email": self.customer_email,
            "customer_address": self.customer_address,
            "subtotal": self.subtotal,
            "tax": self.tax,
            "total": self.total,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "user_id": self.user_id,
            "shipping_address_id": self.shipping_address_id,
            "billing_address_id": self.billing_address_id,
            "payment_method_id": self.payment_method_id,
            "items": [item.to_dict() for item in self.items],
        }


class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    product_name: Mapped[str] = mapped_column(String(120), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    total_price: Mapped[float] = mapped_column(Float, nullable=False)

    order: Mapped[Order] = relationship("Order", back_populates="items")
    product: Mapped[Product] = relationship("Product", back_populates="order_items")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "product_id": self.product_id,
            "product_name": self.product_name,
            "quantity": self.quantity,
            "unit_price": self.unit_price,
            "total_price": self.total_price,
        }
