"""Cart API, scoped to the requesting space (design D3)."""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.spaces import cart_session_id, cart_storage_key, current_space
from ..services.cart_service import CartService
from ..services.product_service import ProductService

router = APIRouter()


class AddToCartRequest(BaseModel):
    product_id: int = Field(..., ge=1)
    quantity: int = Field(default=1, ge=1, le=20)


@dataclass(frozen=True)
class CartSession:
    """The two cart identities of a request (design D3).

    ``storage_key`` addresses the rows and is space-prefixed outside
    ``default``; ``label`` is the ``X-Session-ID`` the caller sent (or
    ``workshop-demo``) and is what the responses report as ``session``, so it
    never leaks the space.
    """

    storage_key: str
    label: str


def resolve_cart_session(
    session_id: str | None = Header(default=None, alias="X-Session-ID"),
    space: str = Depends(current_space),
) -> CartSession:
    """Cart storage key and reported session id of the requesting space."""
    return CartSession(
        storage_key=cart_storage_key(space, session_id),
        label=cart_session_id(session_id),
    )


@router.get("/", summary="Get cart state")
async def get_cart(
    session: AsyncSession = Depends(get_session),
    cart_session: CartSession = Depends(resolve_cart_session),
):
    cart_service = CartService(
        session=session,
        session_key=cart_session.storage_key,
        session_label=cart_session.label,
    )
    return await cart_service.get_cart_state()


@router.post("/items", summary="Add item to cart")
async def add_to_cart(
    payload: AddToCartRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    cart_session: CartSession = Depends(resolve_cart_session),
):
    cart_service = CartService(
        session=session,
        session_key=cart_session.storage_key,
        session_label=cart_session.label,
    )
    product_service = ProductService(session)
    product = await product_service.get_product_model(payload.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    return await cart_service.add_to_cart(product, payload.quantity)


@router.delete("/", summary="Clear cart")
async def clear_cart(
    session: AsyncSession = Depends(get_session),
    cart_session: CartSession = Depends(resolve_cart_session),
):
    cart_service = CartService(
        session=session,
        session_key=cart_session.storage_key,
        session_label=cart_session.label,
    )
    await cart_service.clear_cart()
    return {"status": "cleared", "session": cart_service.session_label}
