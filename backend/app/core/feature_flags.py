"""The one flag API of the shop: effective flags per workshop space (design D4).

Flag values are resolved **per request and never cached**. The old process-local
``TTLCache`` went stale across workers and instances and could not answer "the
change is effective for the next request in the same space", so it is gone; the
cost is one indexed read of about fifteen rows per request.

**Precedence** (the wording the other changes quote): the environment override
(``WORKSHOP_FLAG_*``), then the space value (non-default spaces), then the
baseline (non-default spaces) or the global value (the ``default`` space).

``default`` is the global space and keeps using the ``feature_flags`` table.
Every other space keeps only the flags it has actually set, in
``space_feature_flags``, and falls back to the fixed :func:`baseline_flags`
rather than to the live global rows: a facilitator demo in ``default`` must not
leak into a participant space that has set nothing, and a space must come back
to the same known state after a reset regardless of what ``default`` looks like.

:func:`get_effective_flags` is **the seam**: every consumer of flags - page
routes, the workshop and admin APIs, search, the AI helper and the template
helpers of ``drift-coverage`` - receives that dict and never queries the flag
tables itself. ``backend/tests/unit/test_flag_seam.py`` enforces it.
"""
from __future__ import annotations

from collections.abc import Mapping

from fastapi import Depends
from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.feature_flag import FeatureFlag, SpaceFeatureFlag
from .config import settings
from .db import get_session_factory
from .spaces import DEFAULT_SPACE, current_space


def baseline_flags() -> dict[str, bool]:
    """The flag values a space that has set nothing sees.

    The seeded defaults of ``seeds/seed_data.py`` with preset ``clean`` applied
    on top, as a fresh dict. Both sources are imported lazily inside the
    function: ``seed_data`` and ``core/workshop.py`` import this module, so a
    module-level import would be a cycle.

    Since ``drift-coverage`` (its task 15.1) both sources are that change's own:
    the seeded rows generate one disabled row per entry of ``PLANTED_BUGS``, and
    the preset comes from :func:`~backend.app.core.workshop.build_presets`
    rather than from ``api/workshop.py``, so a flag added to either registry -
    ``BUG_CHECKOUT_TOTAL``, say - is part of every space's baseline without a
    second edit here.
    """
    from ..seeds.seed_data import FEATURE_FLAGS
    from .workshop import build_presets

    flags = {str(flag["key"]).upper(): bool(flag["enabled"]) for flag in FEATURE_FLAGS}
    clean = build_presets()["clean"]
    flags.update({key.upper(): bool(value) for key, value in clean.items()})
    return flags


async def resolve_effective_flags(space: str) -> dict[str, bool]:
    """The effective flags of ``space``, as a new dict.

    Uses a short-lived session of its own instead of the request session, so no
    pooled connection is held while a page renders or while a planted bug sleeps.
    The returned dict is never shared, so a caller may mutate it freely.
    """
    session_factory = get_session_factory()

    if space == DEFAULT_SPACE:
        async with session_factory() as session:
            rows = await session.scalars(select(FeatureFlag))
            flags: dict[str, bool] = {row.key: bool(row.enabled) for row in rows}
    else:
        # Never reads the global rows: keys that exist only in ``default``
        # (an admin PUT there, say) do not appear in any other space.
        flags = baseline_flags()
        async with session_factory() as session:
            rows = await session.scalars(
                select(SpaceFeatureFlag).where(SpaceFeatureFlag.space == space)
            )
            flags.update({row.key: bool(row.enabled) for row in rows})

    # The environment override wins in every space.
    flags.update(settings.feature_flag_overrides)
    return flags


async def get_effective_flags(space: str = Depends(current_space)) -> dict[str, bool]:
    """FastAPI dependency: the effective flags of the request's space.

    **This is the seam.** FastAPI caches the value per request, so several
    dependants of one request share one read and one consistent dict.
    """
    return await resolve_effective_flags(space)


async def set_flags(session: AsyncSession, space: str, updates: Mapping[str, bool]) -> None:
    """Write ``updates`` for ``space`` in a single transaction.

    Keys are upper-cased. In ``default`` the global ``feature_flags`` rows are
    upserted and unknown keys are created, as before spaces existed. Every other
    space upserts its own ``space_feature_flags`` rows with SQLite
    ``INSERT ... ON CONFLICT (space, key) DO UPDATE`` and never touches the
    global table. Exactly one commit is issued, whatever the number of keys.
    """
    normalized = {str(key).upper(): bool(value) for key, value in updates.items()}
    if not normalized:
        return

    if space == DEFAULT_SPACE:
        existing = await session.scalars(
            select(FeatureFlag).where(FeatureFlag.key.in_(normalized))
        )
        by_key = {flag.key: flag for flag in existing}
        for key, enabled in normalized.items():
            flag = by_key.get(key)
            if flag is None:
                session.add(FeatureFlag(key=key, enabled=enabled))
            else:
                flag.enabled = enabled
    else:
        statement = sqlite_insert(SpaceFeatureFlag).values(
            [
                {"space": space, "key": key, "enabled": enabled}
                for key, enabled in normalized.items()
            ]
        )
        statement = statement.on_conflict_do_update(
            index_elements=["space", "key"],
            set_={"enabled": statement.excluded.enabled},
        )
        await session.execute(statement)

    await session.commit()


async def clear_space_flags(session: AsyncSession, space: str) -> None:
    """Drop every flag value ``space`` has set, so it falls back to the baseline.

    Used by the space reset (design D7). Only the rows of that one space are
    removed; the global table and the rows of other spaces are untouched.
    """
    await session.execute(delete(SpaceFeatureFlag).where(SpaceFeatureFlag.space == space))
    await session.commit()

