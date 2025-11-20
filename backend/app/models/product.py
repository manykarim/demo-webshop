from __future__ import annotations

from typing import List

from sqlalchemy import Column, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, relationship

from .base import Base


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    sku = Column(String(64), nullable=False, unique=True)
    price = Column(Float, nullable=False)
    description = Column(Text, nullable=False)
    image_url = Column(String(255), nullable=True)
    category = Column(String(64), nullable=True)
    inventory = Column(Integer, nullable=False, default=0)
    rating = Column(Float, nullable=True)
    review_count = Column(Integer, nullable=True, default=0)

    order_items: Mapped[List["OrderItem"]] = relationship(
        "OrderItem", back_populates="product", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "sku": self.sku,
            "price": self.price,
            "description": self.description,
            "image_url": self.image_url,
            "category": self.category,
            "inventory": self.inventory,
            "rating": self.rating,
            "review_count": self.review_count,
        }
