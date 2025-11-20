from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .product import Product


class CartItem(Base):
    __tablename__ = "cart_items"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_key: Mapped[str] = mapped_column(String(64), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1)

    product: Mapped[Product] = relationship("Product")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_key": self.session_key,
            "product_id": self.product_id,
            "quantity": self.quantity,
            "product": self.product.to_dict() if self.product else None,
        }
