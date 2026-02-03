"""Workshop API endpoints for managing self-healing locator testing features."""
from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.feature_flags import list_feature_flags, set_feature_flag

router = APIRouter()


class WorkshopStatus(BaseModel):
    """Current workshop feature status."""
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


# Workshop presets for quick configuration
PRESETS = {
    "clean": {
        "LOCATOR_V2": False,
        "LOCATOR_V3": False,
        "LOCATOR_V4": False,
        "BUG_MISSING_BUTTON": False,
        "BUG_WRONG_PRICE": False,
        "BUG_BROKEN_LINKS": False,
        "BUG_SLOW_RESPONSE": False,
        "AI_DETERMINISTIC": True,
        "AI_RANDOM_DELAYS": False,
        "AI_VARIED_RESPONSES": False,
    },
    "stage1": {
        # Stage 1: Clean slate - all workshop features off
        "LOCATOR_V2": False,
        "LOCATOR_V3": False,
        "LOCATOR_V4": False,
        "BUG_MISSING_BUTTON": False,
        "BUG_WRONG_PRICE": False,
        "BUG_BROKEN_LINKS": False,
    },
    "stage2": {
        # Stage 2: Changed element IDs and classes
        "LOCATOR_V2": True,
        "LOCATOR_V3": False,
        "LOCATOR_V4": False,
    },
    "stage3": {
        # Stage 3: Removed data-test attributes
        "LOCATOR_V2": False,
        "LOCATOR_V3": True,
        "LOCATOR_V4": False,
    },
    "stage4": {
        # Stage 4: Restructured DOM
        "LOCATOR_V2": False,
        "LOCATOR_V3": False,
        "LOCATOR_V4": True,
    },
    "buggy": {
        # Enable all intentional bugs
        "BUG_MISSING_BUTTON": True,
        "BUG_WRONG_PRICE": True,
        "BUG_BROKEN_LINKS": True,
        "BUG_SLOW_RESPONSE": True,
    },
    "ai_chaos": {
        # AI with maximum variation
        "AI_DETERMINISTIC": False,
        "AI_RANDOM_DELAYS": True,
        "AI_VARIED_RESPONSES": True,
    },
}


def _get_locator_stage(flags: Dict[str, bool]) -> Optional[str]:
    """Determine active locator stage."""
    if flags.get("LOCATOR_V4"):
        return "v4"
    if flags.get("LOCATOR_V3"):
        return "v3"
    if flags.get("LOCATOR_V2"):
        return "v2"
    return "v1"


def _get_active_bugs(flags: Dict[str, bool]) -> List[str]:
    """List active bug flags."""
    bug_flags = ["BUG_MISSING_BUTTON", "BUG_WRONG_PRICE", "BUG_BROKEN_LINKS", "BUG_SLOW_RESPONSE"]
    return [f for f in bug_flags if flags.get(f)]


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
async def get_workshop_status(session: AsyncSession = Depends(get_session)) -> WorkshopStatus:
    """Get current workshop feature status."""
    flags = await list_feature_flags(session)

    return WorkshopStatus(
        locator_stage=_get_locator_stage(flags),
        active_bugs=_get_active_bugs(flags),
        ai_mode=_get_ai_mode(flags),
        all_flags=flags,
    )


@router.post("/preset")
async def apply_preset(
    body: WorkshopPreset,
    session: AsyncSession = Depends(get_session),
) -> Dict:
    """Apply a workshop preset configuration."""
    preset_name = body.preset.lower()

    if preset_name not in PRESETS:
        return {
            "status": "error",
            "message": f"Unknown preset: {preset_name}",
            "available_presets": list(PRESETS.keys()),
        }

    preset_flags = PRESETS[preset_name]

    for key, enabled in preset_flags.items():
        await set_feature_flag(session, key, enabled)

    flags = await list_feature_flags(session)

    return {
        "status": "success",
        "preset": preset_name,
        "applied_flags": preset_flags,
        "current_status": {
            "locator_stage": _get_locator_stage(flags),
            "active_bugs": _get_active_bugs(flags),
            "ai_mode": _get_ai_mode(flags),
        },
    }


@router.post("/flags")
async def update_flags(
    body: BulkFlagUpdate,
    session: AsyncSession = Depends(get_session),
) -> Dict:
    """Update multiple workshop flags at once."""
    updated = {}

    for key, enabled in body.flags.items():
        await set_feature_flag(session, key, enabled)
        updated[key] = enabled

    flags = await list_feature_flags(session)

    return {
        "status": "success",
        "updated_flags": updated,
        "current_status": {
            "locator_stage": _get_locator_stage(flags),
            "active_bugs": _get_active_bugs(flags),
            "ai_mode": _get_ai_mode(flags),
        },
    }


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
        "ai_chaos": "AI with random delays and varied responses",
    }
    return descriptions.get(name, "No description")
