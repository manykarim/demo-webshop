from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..services.cart_service import CartService
from ..services.product_service import ProductService

router = APIRouter()


class AddToCartRequest(BaseModel):
    product_id: int = Field(..., ge=1)
    quantity: int = Field(default=1, ge=1, le=20)


def resolve_session_key(session_id: str | None = Header(default=None, alias="X-Session-ID")) -> str:
    return session_id or "workshop-demo"


@router.get("/", summary="Get cart state")
async def get_cart(
    session: AsyncSession = Depends(get_session),
    session_key: str = Depends(resolve_session_key),
):
    cart_service = CartService(session=session, session_key=session_key)
    return await cart_service.get_cart_state()


@router.post("/items", summary="Add item to cart")
async def add_to_cart(
    payload: AddToCartRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    session_key: str = Depends(resolve_session_key),
):
    cart_service = CartService(session=session, session_key=session_key)
    product_service = ProductService(session)
    product = await product_service.get_product_model(payload.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    return await cart_service.add_to_cart(product, payload.quantity)


@router.delete("/", summary="Clear cart")
async def clear_cart(
    session: AsyncSession = Depends(get_session),
    session_key: str = Depends(resolve_session_key),
):
    cart_service = CartService(session=session, session_key=session_key)
    await cart_service.clear_cart()
    return {"status": "cleared", "session": cart_service.session_key}
