"""Workshop API endpoints for managing self-healing locator testing features."""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.db import get_session
from ..core.feature_flags import (
    baseline_flags,
    clear_space_flags,
    get_effective_flags,
    resolve_effective_flags,
    set_flags,
)
from ..core.spaces import (
    CART_KEY_SEPARATOR,
    DEFAULT_SPACE,
    current_space,
    require_workshop_write_access,
)
from ..core.workshop import PLANTED_BUGS, build_presets, effective_stage
from ..models.cart import CartItem
from ..models.order import Order, OrderItem

router = APIRouter()


class WorkshopStatus(BaseModel):
    """Current workshop feature status of the requesting space."""
    version: str
    #: The space this request was handled in; never any other space (design D6).
    space: str
    locator_stage: Optional[str]
    active_bugs: List[str]
    ai_mode: str
    all_flags: Dict[str, bool]


class WorkshopPreset(BaseModel):
    """Apply a workshop preset configuration."""
    preset: str  # "clean", "stage1", "stage2", "stage3", "stage4", "buggy", "ai_chaos"


class BulkFlagUpdate(BaseModel):
    """Update multiple flags at once."""
    flags: Dict[str, bool]


class WorkshopReset(BaseModel):
    """What a reset removed from the requesting space, and its state now."""

    #: The space the reset acted on; never any other space (design D6).
    space: str
    removed_flags: int = Field(
        ...,
        description=(
            "Flag values the reset undid: the rows the space had set outside "
            "`default`, and inside `default` the global rows whose value was "
            "restored to the baseline."
        ),
    )
    removed_cart_items: int
    removed_orders: int
    locator_stage: Optional[str]
    active_bugs: List[str]
    ai_mode: str


#: The workshop presets, built once from the registries in ``core/workshop.py``
#: (design Decision 12). Presets are absolute for the flag groups they own, so
#: applying one never depends on what ran before it, and ``stage1`` to ``stage4``
#: leave the planted bugs alone. ``core/feature_flags.baseline_flags()`` builds
#: the space baseline from ``build_presets()["clean"]`` itself (task 15.1), so
#: this module is not on the import path of the flag seam.
PRESETS = build_presets()


#: Row count of a space's own flag values, for the reset response only.
#: The flag *values* of every endpoint still come from the seam
#: (``core/feature_flags.py``); this statement counts rows without importing the
#: flag models, which stay inside the seam (design D4, ``test_flag_seam.py``).
_COUNT_SPACE_FLAG_ROWS = text("SELECT COUNT(*) FROM space_feature_flags WHERE space = :space")


def _remove_order_documents(order_numbers: Sequence[str]) -> None:
    """Delete the rendered documents of ``order_numbers`` (design D7).

    Runs after the commit, never inside the transaction: a document is a file,
    so removing it cannot be rolled back. Missing files are ignored, because a
    checkout on a host without the native PDF libraries stores an order and no
    document at all (``reproducible-image`` D8).
    """
    output_dir = Path(settings.pdf_output_dir)
    for order_number in order_numbers:
        for name in (f"invoice_{order_number}.pdf", f"summary_{order_number}.pdf"):
            (output_dir / name).unlink(missing_ok=True)


def _get_active_bugs(flags: Dict[str, bool]) -> List[str]:
    """The active planted bugs, in registry order (design Decision 9).

    Read from ``PLANTED_BUGS`` rather than from a list of its own, so a bug
    added to the registry is reported here without a second edit.
    """
    return [bug.flag for bug in PLANTED_BUGS if flags.get(bug.flag)]


def _get_ai_mode(flags: Dict[str, bool]) -> str:
    """Determine AI mode."""
    if flags.get("AI_DETERMINISTIC"):
        mode = "deterministic"
    else:
        mode = "live"

    modifiers = []
    if flags.get("AI_RANDOM_DELAYS"):
        modifiers.append("delayed")
    if flags.get("AI_VARIED_RESPONSES"):
        modifiers.append("varied")

    if modifiers:
        return f"{mode} ({', '.join(modifiers)})"
    return mode


@router.get("/status", response_model=WorkshopStatus)
async def get_workshop_status(
    space: str = Depends(current_space),
    flags: Dict[str, bool] = Depends(get_effective_flags),
) -> WorkshopStatus:
    """Get the workshop feature status of the requesting space."""
    return WorkshopStatus(
        version=settings.app_version,
        space=space,
        locator_stage=f"v{effective_stage(flags)}",
        active_bugs=_get_active_bugs(flags),
        ai_mode=_get_ai_mode(flags),
        all_flags=flags,
    )


@router.post("/preset", dependencies=[Depends(require_workshop_write_access)])
async def apply_preset(
    body: WorkshopPreset,
    session: AsyncSession = Depends(get_session),
    space: str = Depends(current_space),
) -> Dict:
    """Apply a workshop preset configuration to the requesting space."""
    preset_name = body.preset.lower()

    if preset_name not in PRESETS:
        return {
            "status": "error",
            "message": f"Unknown preset: {preset_name}",
            "available_presets": list(PRESETS.keys()),
        }

    preset_flags = PRESETS[preset_name]

    # One write, one commit, whatever the number of flags in the preset.
    await set_flags(session, space, preset_flags)

    # Resolved again rather than read from the request-cached dependency, which
    # still holds the values from before this write.
    flags = await resolve_effective_flags(space)

    return {
        "status": "success",
        "preset": preset_name,
        "applied_flags": preset_flags,
        "current_status": {
            "locator_stage": f"v{effective_stage(flags)}",
            "active_bugs": _get_active_bugs(flags),
            "ai_mode": _get_ai_mode(flags),
        },
    }


@router.post("/flags", dependencies=[Depends(require_workshop_write_access)])
async def update_flags(
    body: BulkFlagUpdate,
    session: AsyncSession = Depends(get_session),
    space: str = Depends(current_space),
) -> Dict:
    """Update multiple workshop flags of the requesting space at once."""
    updated = dict(body.flags)

    # One write, one commit, whatever the number of keys.
    await set_flags(session, space, updated)

    # Resolved again: the request-cached dependency predates this write.
    flags = await resolve_effective_flags(space)

    return {
        "status": "success",
        "updated_flags": updated,
        "current_status": {
            "locator_stage": f"v{effective_stage(flags)}",
            "active_bugs": _get_active_bugs(flags),
            "ai_mode": _get_ai_mode(flags),
        },
    }


@router.post(
    "/reset",
    response_model=WorkshopReset,
    dependencies=[Depends(require_workshop_write_access)],
)
async def reset_space(
    session: AsyncSession = Depends(get_session),
    space: str = Depends(current_space),
) -> WorkshopReset:
    """Remove everything the requesting space created (design D7).

    Outside ``default`` the space's own flag values are dropped, so the space
    falls back to :func:`baseline_flags`; in ``default`` the global rows are
    written back to that same baseline. Both branches then empty the space's
    carts and delete the orders its checkouts created. Seeded orders carry no
    space and are never matched, no seeder runs, and no other space is touched.

    Every database change is one transaction: the deletes are executed on this
    session without committing, and the flag write - ``clear_space_flags``
    outside ``default``, ``set_flags`` inside it - issues the single commit that
    makes all of them visible. The documents of the deleted orders are removed
    afterwards, once the rows are really gone.
    """
    is_default = space == DEFAULT_SPACE

    # Reads first, while nothing is deleted yet.
    baseline: Dict[str, bool] = baseline_flags() if is_default else {}
    if is_default:
        # No row is removed in ``default``; the count reports the global rows
        # whose value this reset writes back. Read through the seam, on its own
        # short-lived session, as everywhere else.
        before = await resolve_effective_flags(DEFAULT_SPACE)
        removed_flags = sum(1 for key, value in baseline.items() if before.get(key) != value)
    else:
        removed_flags = int(
            (await session.execute(_COUNT_SPACE_FLAG_ROWS, {"space": space})).scalar_one()
        )

    # A runtime checkout always stores its space, including "default"; seeded
    # demo history has none, so ``space IS NULL`` is never matched here.
    order_rows = (
        await session.execute(
            select(Order.id, Order.order_number).where(Order.space == space)
        )
    ).all()
    order_ids = [row.id for row in order_rows]
    order_numbers = [str(row.order_number) for row in order_rows]

    if is_default:
        # Keys of the ``default`` space carry no ``<space>:`` prefix (design D3).
        cart_scope = CartItem.session_key.not_like(f"%{CART_KEY_SEPARATOR}%")
    else:
        # The separator is outside the identifier alphabet (design D2), so
        # ``octo`` never matches ``octocat:...`` and the pattern needs no
        # escaping: ``%`` and ``_`` cannot occur in a space identifier.
        cart_scope = CartItem.session_key.like(f"{space}{CART_KEY_SEPARATOR}%")

    removed_cart_items = (
        await session.execute(
            delete(CartItem).where(cart_scope).execution_options(synchronize_session=False)
        )
    ).rowcount

    if order_ids:
        # Explicit: SQLite runs with foreign keys off, so no cascade fires.
        await session.execute(
            delete(OrderItem)
            .where(OrderItem.order_id.in_(order_ids))
            .execution_options(synchronize_session=False)
        )
        await session.execute(
            delete(Order)
            .where(Order.id.in_(order_ids))
            .execution_options(synchronize_session=False)
        )

    # The single commit of this reset, covering the deletes above.
    if is_default:
        await set_flags(session, DEFAULT_SPACE, baseline)
    else:
        await clear_space_flags(session, space)

    _remove_order_documents(order_numbers)

    # Resolved after the commit: the request-cached dependency predates it.
    flags = await resolve_effective_flags(space)

    return WorkshopReset(
        space=space,
        removed_flags=removed_flags,
        removed_cart_items=int(removed_cart_items or 0),
        removed_orders=len(order_ids),
        locator_stage=f"v{effective_stage(flags)}",
        active_bugs=_get_active_bugs(flags),
        ai_mode=_get_ai_mode(flags),
    )


@router.get("/presets")
async def list_presets() -> Dict:
    """List available workshop presets."""
    return {
        "presets": {
            name: {
                "description": _preset_description(name),
                "flags": flags,
            }
            for name, flags in PRESETS.items()
        }
    }


def _preset_description(name: str) -> str:
    """Get description for a preset."""
    descriptions = {
        "clean": "Reset all workshop features to defaults",
        "stage1": "Stage 1: Clean slate with standard locators",
        "stage2": "Stage 2: Changed element IDs and CSS classes",
        "stage3": "Stage 3: Removed data-test attributes",
        "stage4": "Stage 4: Restructured DOM hierarchy",
        "buggy": "Enable all intentional bugs for testing",
        "drift_and_bug": (
            "Stage 4 drift plus the wrong card price and the inconsistent "
            "checkout total: heal the locators and still report the bugs"
        ),
        "ai_chaos": "AI with random delays and varied responses",
    }
    return descriptions.get(name, "No description")
