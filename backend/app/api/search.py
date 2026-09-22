from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.feature_flags import get_effective_flags
from ..services.product_service import ProductService
from ..services.rag_index import RAGIndex

router = APIRouter()


@router.get("/", summary="Search products")
async def search_products(
    q: str = Query("", alias="query"),
    session: AsyncSession = Depends(get_session),
    flags: dict[str, bool] = Depends(get_effective_flags),
):
    service = ProductService(session)
    results = await service.search_products(q)
    if flags.get("SEARCH_V2"):
        index = RAGIndex()
        all_products = await service.list_products()
        index.build(all_products)
        context = index.get_context(q)
        return {"mode": "semantic", "results": results, "context": context}

    return {"mode": "keyword", "results": results}


@router.get("/suggest", summary="Suggest product names")
async def suggest_products(
    q: str = Query(..., min_length=1, alias="query"),
    limit: int = Query(8, ge=1, le=20),
    session: AsyncSession = Depends(get_session),
):
    service = ProductService(session)
    suggestions = await service.search_products(q, limit=limit)
    trimmed = [
        {
            "id": item["id"],
            "name": item["name"],
            "price": item["price"],
            "category": item.get("category"),
        }
        for item in suggestions
    ]
    return {"results": trimmed}
