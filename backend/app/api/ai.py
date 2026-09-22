from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.feature_flags import get_effective_flags
from ..services.ai_service import AIService

router = APIRouter()


@router.post("/ask", summary="Ask product AI helper")
async def ask_ai(
    payload: dict = Body(...),
    session: AsyncSession = Depends(get_session),
    flags: dict[str, bool] = Depends(get_effective_flags),
):
    question = str(payload.get("question", ""))
    mode = str(payload.get("mode", "summary"))
    provider_override = payload.get("provider")
    # The flags come from the seam, so the helper answers in the space of the
    # request and never queries the flag tables itself (design D4).
    ai_service = AIService(session=session, flags=flags)
    return await ai_service.ask(question=question, mode=mode, provider_override=provider_override)
