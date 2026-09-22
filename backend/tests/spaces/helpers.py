"""Plain helper functions for the ``spaces`` suite (design D12).

No fixtures and no environment handling live here: the suite reuses the shared
harness of ``backend/tests/harness.py`` and the canonical fixtures of the root
``backend/tests/conftest.py`` by their exact names.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any

#: Class name that the product card renders for locator stage 2.
_STAGE_2_BLOCK = "item-card"
#: Class name that the product card renders for locator stage 4.
_STAGE_4_BLOCK = "product-tile"
#: Test hook that stages 1 and 2 render and stages 3 and 4 drop.
_PRODUCT_CARD_TEST_HOOK = 'data-test="product-card"'


def _database_path() -> Path:
    """The SQLite file that ``settings.database_url`` points at right now.

    Read at call time, so the helper follows the temporary database that the
    harness patches in for the running test rather than the one that existed
    when this module was imported.
    """
    from backend.app.core.config import settings

    url = settings.database_url
    _, _, location = url.partition(":///")
    if not location:
        raise ValueError(f"not a file-backed SQLite URL: {url!r}")
    return Path(location.split("?", 1)[0])


def sqlite_rows(sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
    """Run ``sql`` against the active harness database and return plain tuples.

    Uses stdlib ``sqlite3`` on the database file directly, so a query sees the
    committed state without going through the application's async engine.
    """
    connection = sqlite3.connect(_database_path())
    try:
        return [tuple(row) for row in connection.execute(sql, tuple(params)).fetchall()]
    finally:
        connection.close()


def rendered_stage(html: str) -> str:
    """The locator stage that ``html`` was rendered in.

    Stage 2 and stage 4 are recognised by the block class of the product card,
    stage 3 by the missing ``data-test`` hook, and everything else is stage 1.
    Only the product-card names fixed by ``drift-coverage`` Decision 1 are used.
    """
    if _STAGE_2_BLOCK in html:
        return "v2"
    if _STAGE_4_BLOCK in html:
        return "v4"
    if _PRODUCT_CARD_TEST_HOOK not in html:
        return "v3"
    return "v1"
