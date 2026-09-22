from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.workshop import planted_delay
from ..services.product_service import ProductService

router = APIRouter()


# The product list API is the second catalogue response `BUG_SLOW_RESPONSE`
# delays (drift-coverage Decision 11); the detail endpoint below is not.
@router.get(
    "/",
    summary="List products",
    dependencies=[Depends(planted_delay("catalogue"))],
)
async def list_products(session: AsyncSession = Depends(get_session)):
    service = ProductService(session)
    return {"items": await service.list_products()}


@router.get("/{product_id}", summary="Get product detail")
async def get_product(product_id: int, session: AsyncSession = Depends(get_session)):
    service = ProductService(session)
    try:
        product = await service.get_product(product_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"product": product}
