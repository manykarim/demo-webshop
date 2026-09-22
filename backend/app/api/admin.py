"""Single-flag admin API, scoped to the requesting space (design D4 and D6)."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.feature_flags import get_effective_flags, resolve_effective_flags, set_flags
from ..core.spaces import current_space, require_workshop_write_access

router = APIRouter()


@router.get("/flags", summary="List feature flags")
async def list_flags(flags: dict[str, bool] = Depends(get_effective_flags)):
    """The effective flags of the requesting space, never those of another."""
    return flags


@router.put(
    "/flags/{flag_key}",
    summary="Toggle feature flag",
    dependencies=[Depends(require_workshop_write_access)],
)
async def set_flag(
    flag_key: str,
    payload: dict = Body(...),
    session: AsyncSession = Depends(get_session),
    space: str = Depends(current_space),
):
    """Set one flag in the requesting space and report its effective value."""
    if "enabled" not in payload:
        raise HTTPException(status_code=400, detail="Missing 'enabled' boolean in payload")

    await set_flags(session, space, {flag_key: bool(payload["enabled"])})

    # Resolved again rather than read from the request-cached dependency, and
    # through the seam, so an environment override still wins over the write.
    updated = await resolve_effective_flags(space)
    flag_key_upper = flag_key.upper()
    return {"flag": flag_key_upper, "enabled": updated.get(flag_key_upper)}
