from __future__ import annotations

import asyncio
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .config import settings
from ..models.base import Base
from ..models import cart  # noqa: F401  # ensure model registration
from ..models import feature_flag  # noqa: F401
from ..models import order  # noqa: F401
from ..models import product  # noqa: F401
from ..models import user  # noqa: F401

async_engine: AsyncEngine | None = None
async_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global async_engine
    if async_engine is None:
        async_engine = create_async_engine(settings.database_url, echo=False)
    return async_engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global async_session_factory
    if async_session_factory is None:
        async_session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    return async_session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session


async def init_db() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def shutdown_db() -> None:
    global async_engine
    if async_engine is not None:
        await async_engine.dispose()
        async_engine = None
        await asyncio.sleep(0)
