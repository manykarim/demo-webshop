from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.spaces import cart_storage_key, current_space
from ..services.cart_service import CartService
from ..services.order_service import CustomerDetails, OrderService
from ..services.pdf_service import PDFService

router = APIRouter()


class CheckoutRequest(BaseModel):
    name: str = Field(..., min_length=2)
    email: EmailStr
    address: str = Field(..., min_length=5)


def resolve_session_key(
    session_id: str | None = Header(default=None, alias="X-Session-ID"),
    space: str = Depends(current_space),
) -> str:
    """The cart storage key of this request (design D3).

    The checkout never reports the cart ``session``, so only the storage key is
    needed here and no label is passed to :class:`CartService`.
    """
    return cart_storage_key(space, session_id)


@router.post("/", summary="Perform checkout")
async def checkout(
    request: Request,
    payload: CheckoutRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    session_key: str = Depends(resolve_session_key),
    space: str = Depends(current_space),
):
    cart_service = CartService(session=session, session_key=session_key)
    cart_state = await cart_service.get_cart_state()
    if not cart_state["items"]:
        raise HTTPException(status_code=400, detail="Cart is empty")

    templates = request.app.state.templates
    pdf_service = PDFService(templates)
    order_service = OrderService(session=session, pdf_service=pdf_service)

    try:
        order, documents = await order_service.create_order(
            CustomerDetails(name=payload.name, email=payload.email, address=payload.address),
            cart_state,
            space=space,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await cart_service.clear_cart()

    return {
        "status": "success",
        "order": order.to_dict(),
        "documents": documents,
    }
