from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..services.product_service import ProductService

router = APIRouter()


@router.get("/", summary="List products")
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
