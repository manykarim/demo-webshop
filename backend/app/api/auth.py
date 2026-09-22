from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..core.db import get_session
from ..core.spaces import current_space
from ..models.order import Order
from ..models.user import Address, PaymentMethod, User
from ..services.order_service import order_visible_in

router = APIRouter()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: dict
    addresses: list[dict]
    payment_methods: list[dict]
    orders: list[dict]


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    space: str = Depends(current_space),
):
    # The order history is loaded through the one visibility rule (design D5),
    # so a login in one space never lists another space's runtime orders while
    # the seeded demo history stays visible everywhere.
    stmt = (
        select(User)
        .where(User.email == payload.email)
        .options(
            selectinload(User.addresses),
            selectinload(User.payment_methods).selectinload(PaymentMethod.billing_address),
            selectinload(User.orders.and_(order_visible_in(space))).selectinload(Order.items),
        )
    )
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if not user or user.password_hash != hash_password(payload.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # An aware UTC instant, serialized with the ``Z`` designator, so API
    # consumers need not guess the zone of the expiry (story API-007 AC-2).
    expires_at = datetime.now(timezone.utc) + timedelta(hours=4)
    token_source = f"{user.email}{expires_at.isoformat()}{secrets.token_hex(8)}"
    token = hashlib.sha256(token_source.encode()).hexdigest()

    addresses = [address.to_dict() for address in user.addresses]
    payments = [
        {
            "id": pm.id,
            "brand": pm.brand,
            "last4": pm.last4,
            "exp_month": pm.exp_month,
            "exp_year": pm.exp_year,
            "billing_address_id": pm.billing_address_id,
            "display": pm.masked(),
        }
        for pm in user.payment_methods
    ]
    orders = [
        {
            "id": order.id,
            "order_number": order.order_number,
            "status": order.status,
            "total": order.total,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "invoice_url": f"/api/docs/orders/{order.id}/invoice.pdf",
            "summary_url": f"/api/docs/orders/{order.id}/summary.pdf",
        }
        for order in sorted(user.orders, key=lambda o: o.created_at or datetime.utcnow(), reverse=True)
    ]

    return LoginResponse(
        access_token=token,
        expires_at=expires_at,
        user=user.to_dict(),
        addresses=addresses,
        payment_methods=payments,
        orders=orders,
    )
