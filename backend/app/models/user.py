from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, relationship

from .base import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(120), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    full_name = Column(String(120), nullable=False)

    addresses: Mapped[list["Address"]] = relationship("Address", back_populates="user", cascade="all, delete-orphan")
    payment_methods: Mapped[list["PaymentMethod"]] = relationship(
        "PaymentMethod", back_populates="user", cascade="all, delete-orphan"
    )
    orders: Mapped[list["Order"]] = relationship("Order", back_populates="user")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "full_name": self.full_name,
        }


class Address(Base):
    __tablename__ = "addresses"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    label = Column(String(80), nullable=True)
    line1 = Column(String(160), nullable=False)
    line2 = Column(String(160), nullable=True)
    city = Column(String(80), nullable=False)
    state = Column(String(80), nullable=False)
    postal_code = Column(String(20), nullable=False)
    country = Column(String(80), nullable=False)

    user: Mapped[User] = relationship("User", back_populates="addresses")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "line1": self.line1,
            "line2": self.line2,
            "city": self.city,
            "state": self.state,
            "postal_code": self.postal_code,
            "country": self.country,
        }


class PaymentMethod(Base):
    __tablename__ = "payment_methods"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    brand = Column(String(40), nullable=False)
    last4 = Column(String(4), nullable=False)
    exp_month = Column(Integer, nullable=False)
    exp_year = Column(Integer, nullable=False)
    billing_address_id = Column(Integer, ForeignKey("addresses.id", ondelete="SET NULL"), nullable=True)

    user: Mapped[User] = relationship("User", back_populates="payment_methods")
    billing_address: Mapped[Address] = relationship("Address")

    def masked(self) -> str:
        return f"{self.brand} •••• {self.last4}"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "brand": self.brand,
            "last4": self.last4,
            "exp_month": self.exp_month,
            "exp_year": self.exp_year,
            "billing_address_id": self.billing_address_id,
        }
