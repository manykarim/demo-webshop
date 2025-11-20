from __future__ import annotations

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Path as FastAPIPath, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..core.config import settings
from ..core.db import get_session
from ..models.order import Order
from ..services.pdf_service import PDFService

router = APIRouter()


def _build_item_payload(order: Order) -> list[dict]:
    return [
        {
            "product_id": item.product_id,
            "name": item.product_name,
            "quantity": item.quantity,
            "unit_price": item.unit_price,
            "total_price": item.total_price,
        }
        for item in order.items
    ]


async def _ensure_document(order: Order, pdf_service: PDFService, doc_type: str) -> Path:
    output_dir = Path(settings.pdf_output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if doc_type == "invoice":
        target = output_dir / f"invoice_{order.order_number}.pdf"
        if target.exists():
            return target
        await pdf_service.render_pdf(
            "pdf/invoice.html",
            {
                "order": {
                    "order_number": order.order_number,
                    "order_date": order.created_at.strftime("%Y-%m-%d"),
                    "subtotal": order.subtotal,
                    "tax": order.tax,
                    "total": order.total,
                },
                "customer": {
                    "name": order.customer_name,
                    "email": order.customer_email,
                    "address": order.customer_address,
                },
                "items": _build_item_payload(order),
            },
            target.name,
        )
        return target

    target = output_dir / f"summary_{order.order_number}.pdf"
    if target.exists():
        return target

    await pdf_service.render_pdf(
        "pdf/order_summary.html",
        {
            "order": {
                "order_number": order.order_number,
                "status": order.status,
                "subtotal": order.subtotal,
                "total": order.total,
            },
            "items": _build_item_payload(order),
        },
        target.name,
    )
    return target


async def _fetch_order(session: AsyncSession, order_id: int) -> Order:
    stmt = (
        select(Order)
        .options(selectinload(Order.items))
        .where(Order.id == order_id)
    )
    order = await session.scalar(stmt)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.get("/orders/{order_id}/invoice.pdf", summary="Fetch invoice PDF")
async def get_invoice(
    request: Request,
    order_id: int = FastAPIPath(..., ge=1),
    session: AsyncSession = Depends(get_session),
):
    order = await _fetch_order(session, order_id)
    pdf_service = PDFService(request.app.state.templates)
    path = await _ensure_document(order, pdf_service, "invoice")
    return FileResponse(path, media_type="application/pdf")


@router.get("/orders/{order_id}/summary.pdf", summary="Fetch order summary PDF")
async def get_order_summary(
    request: Request,
    order_id: int = FastAPIPath(..., ge=1),
    session: AsyncSession = Depends(get_session),
):
    order = await _fetch_order(session, order_id)
    pdf_service = PDFService(request.app.state.templates)
    path = await _ensure_document(order, pdf_service, "summary")
    return FileResponse(path, media_type="application/pdf")
