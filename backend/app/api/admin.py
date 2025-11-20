from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.feature_flags import list_feature_flags, set_feature_flag

router = APIRouter()


@router.get("/flags", summary="List feature flags")
async def list_flags(session: AsyncSession = Depends(get_session)):
    return await list_feature_flags(session)


@router.put("/flags/{flag_key}", summary="Toggle feature flag")
async def set_flag(flag_key: str, payload: dict = Body(...), session: AsyncSession = Depends(get_session)):
    if "enabled" not in payload:
        raise HTTPException(status_code=400, detail="Missing 'enabled' boolean in payload")
    updated = await set_feature_flag(session, flag_key, bool(payload["enabled"]))
    flag_key_upper = flag_key.upper()
    return {"flag": flag_key_upper, "enabled": updated.get(flag_key_upper)}
