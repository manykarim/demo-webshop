from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Path as FastAPIPath, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..core.config import settings
from ..core.db import get_session
from ..core.spaces import current_space
from ..models.order import Order
from ..services.order_service import build_document_context, order_visible_in
from ..services.pdf_service import PDFService, pdf_rendering_available

router = APIRouter()

#: The body of the 503 answered while PDF rendering is unavailable. It matches
#: the message of ``PDFRenderingUnavailable``.
PDF_UNAVAILABLE_DETAIL = "PDF rendering is unavailable in this environment"

#: Template and file name prefix per document type.
_DOCUMENTS: dict[str, tuple[str, str]] = {
    "invoice": ("pdf/invoice.html", "invoice"),
    "summary": ("pdf/order_summary.html", "summary"),
}


async def _ensure_document(order: Order, pdf_service: PDFService, doc_type: str) -> Path:
    """Return the order's document, rendering it on demand when it is missing.

    Both documents are rendered from the one context helper the checkout uses
    (design D8), so a document rendered here is identical to the one rendered at
    checkout. ``PDFService`` writes atomically, so an existing file is complete.
    """
    template_name, name_prefix = _DOCUMENTS[doc_type]

    output_dir = Path(settings.pdf_output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    target = output_dir / f"{name_prefix}_{order.order_number}.pdf"
    if target.exists():
        return target

    await pdf_service.render_pdf(template_name, build_document_context(order), target.name)
    return target


async def _fetch_order(session: AsyncSession, order_id: int, space: str) -> Order:
    """The order, if it is visible in ``space`` (design D5).

    An order of another space answers the same 404 as an id that does not
    exist, so sequential ids disclose neither the existence of another
    participant's order nor its documents.
    """
    stmt = (
        select(Order)
        .options(selectinload(Order.items))
        .where(Order.id == order_id, order_visible_in(space))
    )
    order = await session.scalar(stmt)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


def _require_pdf_rendering() -> None:
    """Answer 503 when this environment cannot render PDFs (design D8).

    Checked after the order lookup, so a missing order still answers 404, and
    before any file is served, so a stale document from another environment is
    never handed out while rendering is unavailable.
    """
    if not pdf_rendering_available():
        raise HTTPException(status_code=503, detail=PDF_UNAVAILABLE_DETAIL)


@router.get("/orders/{order_id}/invoice.pdf", summary="Fetch invoice PDF")
async def get_invoice(
    request: Request,
    order_id: int = FastAPIPath(..., ge=1),
    session: AsyncSession = Depends(get_session),
    space: str = Depends(current_space),
):
    order = await _fetch_order(session, order_id, space)
    _require_pdf_rendering()
    pdf_service = PDFService(request.app.state.templates)
    path = await _ensure_document(order, pdf_service, "invoice")
    return FileResponse(path, media_type="application/pdf")


@router.get("/orders/{order_id}/summary.pdf", summary="Fetch order summary PDF")
async def get_order_summary(
    request: Request,
    order_id: int = FastAPIPath(..., ge=1),
    session: AsyncSession = Depends(get_session),
    space: str = Depends(current_space),
):
    order = await _fetch_order(session, order_id, space)
    _require_pdf_rendering()
    pdf_service = PDFService(request.app.state.templates)
    path = await _ensure_document(order, pdf_service, "summary")
    return FileResponse(path, media_type="application/pdf")
