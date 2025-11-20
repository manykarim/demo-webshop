from __future__ import annotations

from typing import Dict

from cachetools import TTLCache
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.feature_flag import FeatureFlag
from .config import settings

_cache = TTLCache(maxsize=32, ttl=settings.feature_flag_cache_seconds)


async def list_feature_flags(session: AsyncSession) -> Dict[str, bool]:
    cached = _cache.get("flags")
    if cached:
        return cached

    result = await session.execute(select(FeatureFlag))
    flags = {flag.key: flag.enabled for flag in result.scalars().all()}

    if settings.feature_flag_overrides:
        flags.update(settings.feature_flag_overrides)

    _cache["flags"] = flags
    return flags


async def set_feature_flag(session: AsyncSession, key: str, enabled: bool) -> Dict[str, bool]:
    key_upper = key.upper()
    flag = await session.scalar(select(FeatureFlag).where(FeatureFlag.key == key_upper))
    if not flag:
        flag = FeatureFlag(key=key_upper, enabled=enabled)
        session.add(flag)
    else:
        flag.enabled = enabled

    await session.commit()
    _cache.pop("flags", None)
    return await list_feature_flags(session)


async def is_enabled(session: AsyncSession, key: str) -> bool:
    flags = await list_feature_flags(session)
    return flags.get(key.upper(), False)
