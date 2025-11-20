from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models.cart import CartItem
from ..models.product import Product


@dataclass
class CartLine:
    product_id: int
    name: str
    quantity: int
    unit_price: float

    @property
    def total_price(self) -> float:
        return round(self.unit_price * self.quantity, 2)


class CartService:
    def __init__(self, session: AsyncSession, session_key: str):
        self.session = session
        self.session_key = session_key

    async def add_to_cart(self, product: Product, quantity: int = 1) -> Dict[str, List[dict]]:
        cart_item = await self.session.scalar(
            select(CartItem)
            .where(CartItem.session_key == self.session_key, CartItem.product_id == product.id)
        )

        if cart_item:
            cart_item.quantity += quantity
        else:
            cart_item = CartItem(session_key=self.session_key, product_id=product.id, quantity=quantity)
            self.session.add(cart_item)

        await self.session.commit()
        return await self.get_cart_state()

    async def get_cart_state(self) -> Dict[str, object]:
        stmt = (
            select(CartItem)
            .options(selectinload(CartItem.product))
            .where(CartItem.session_key == self.session_key)
        )
        result = await self.session.execute(stmt)
        items = result.scalars().all()

        lines: List[CartLine] = []
        for item in items:
            if item.product is None:
                continue
            lines.append(
                CartLine(
                    product_id=item.product_id,
                    name=item.product.name,
                    quantity=item.quantity,
                    unit_price=item.product.price,
                )
            )

        total = round(sum(line.total_price for line in lines), 2)
        return {
            "session": self.session_key,
            "items": [
                {
                    "product_id": line.product_id,
                    "name": line.name,
                    "quantity": line.quantity,
                    "unit_price": line.unit_price,
                    "total_price": line.total_price,
                }
                for line in lines
            ],
            "total": total,
        }

    async def clear_cart(self) -> None:
        await self.session.execute(delete(CartItem).where(CartItem.session_key == self.session_key))
        await self.session.commit()
