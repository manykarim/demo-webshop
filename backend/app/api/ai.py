from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..services.ai_service import AIService

router = APIRouter()


@router.post("/ask", summary="Ask product AI helper")
async def ask_ai(
    payload: dict = Body(...),
    session: AsyncSession = Depends(get_session),
):
    question = str(payload.get("question", ""))
    mode = str(payload.get("mode", "summary"))
    provider_override = payload.get("provider")
    ai_service = AIService(session=session)
    return await ai_service.ask(question=question, mode=mode, provider_override=provider_override)
