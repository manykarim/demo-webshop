from __future__ import annotations

from typing import Dict, List, Optional

from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.product import Product


class ProductService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_products(
        self,
        limit: int | None = None,
        order: str = "name",
        category: Optional[str] = None,
        categories: Optional[list[str]] = None,
        price_min: Optional[float] = None,
        price_max: Optional[float] = None,
        rating_min: Optional[float] = None,
        in_stock: bool | None = None,
    ) -> list[dict]:
        stmt = select(Product)
        filters: list = []
        if categories:
            normalized = [value.strip().lower() for value in categories if value]
            if normalized:
                filters.append(func.lower(Product.category).in_(normalized))
        elif category:
            filters.append(func.lower(Product.category) == category)
        if price_min is not None:
            filters.append(Product.price >= price_min)
        if price_max is not None:
            filters.append(Product.price <= price_max)
        if rating_min is not None:
            filters.append(Product.rating.is_not(None))
            filters.append(Product.rating >= rating_min)
        if in_stock:
            filters.append(Product.inventory > 0)
        if filters:
            stmt = stmt.where(*filters)
        if order == "name":
            stmt = stmt.order_by(asc(Product.name))
        elif order == "newest":
            stmt = stmt.order_by(desc(Product.id))
        elif order == "price_desc":
            stmt = stmt.order_by(desc(Product.price))
        elif order == "price_asc":
            stmt = stmt.order_by(asc(Product.price))
        else:
            stmt = stmt.order_by(asc(Product.name))

        if limit:
            stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        products = result.scalars().all()
        return [product.to_dict() for product in products]

    async def get_product(self, product_id: int) -> dict:
        product = await self.session.get(Product, product_id)
        if not product:
            raise ValueError("Product not found")
        return product.to_dict()

    async def get_product_model(self, product_id: int) -> Product | None:
        return await self.session.get(Product, product_id)

    async def search_products(self, query: str, limit: int | None = None) -> list[dict]:
        if not query:
            return await self.list_products(limit=limit)
        pattern = f"%{query}%"
        stmt = select(Product).where(
            or_(Product.name.ilike(pattern), Product.description.ilike(pattern), Product.category.ilike(pattern))
        )
        if limit:
            stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        products = result.scalars().all()
        return [product.to_dict() for product in products]

    async def get_products_by_ids(self, product_ids: list[int]) -> Dict[int, Product]:
        if not product_ids:
            return {}
        stmt = select(Product).where(Product.id.in_(product_ids))
        result = await self.session.execute(stmt)
        products = result.scalars().all()
        return {product.id: product for product in products}

    async def list_categories(self) -> List[str]:
        stmt = select(Product.category).distinct().where(Product.category.is_not(None))
        result = await self.session.execute(stmt)
        categories = [row[0] for row in result.all() if row[0]]
        categories.sort()
        return categories

    async def get_price_bounds(self) -> tuple[float, float]:
        stmt = select(func.min(Product.price), func.max(Product.price))
        result = await self.session.execute(stmt)
        min_price, max_price = result.one_or_none() or (0.0, 0.0)
        if min_price is None:
            min_price = 0.0
        if max_price is None:
            max_price = min_price
        return float(min_price), float(max_price)
