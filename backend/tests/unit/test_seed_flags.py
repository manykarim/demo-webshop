"""The seeded flag rows are generated from the bug registry (task 3.2).

``FEATURE_FLAGS`` used to list the bug rows by hand, so a new planted bug had to
be added in two places and ``BUG_CHECKOUT_TOTAL`` could ship without a row at
all. The rows now come from ``PLANTED_BUGS``; these tests hold that link and the
one precondition the checkout bug needs - a tax that is visible in cents.
"""
from __future__ import annotations

import asyncio
import inspect
import sqlite3
from contextlib import closing
from pathlib import Path

from backend.app.core.workshop import BUG_FLAGS, PLANTED_BUGS
from backend.app.seeds import seed_data
from backend.app.services.order_service import calculate_totals

#: The flag row that only the registry-generated list contains.
NEW_BUG_FLAG = "BUG_CHECKOUT_TOTAL"


def default_tax_rate() -> float:
    """The tax rate ``OrderService`` and the checkout summary both use."""
    return float(inspect.signature(calculate_totals).parameters["tax_rate"].default)


def flag_rows(database_path: Path) -> dict[str, int]:
    """The ``feature_flags`` table, read outside SQLAlchemy."""
    with closing(sqlite3.connect(database_path)) as connection:
        return dict(connection.execute("SELECT key, enabled FROM feature_flags").fetchall())


def test_every_registered_bug_has_exactly_one_seeded_row() -> None:
    """A bug added to the registry cannot be forgotten in the seed data."""
    keys = [flag["key"] for flag in seed_data.FEATURE_FLAGS]

    for flag in BUG_FLAGS:
        assert keys.count(flag) == 1, flag


def test_no_bug_row_is_seeded_enabled() -> None:
    """Planted bugs are disabled by default (spec "Bug registry")."""
    by_key = {flag["key"]: flag for flag in seed_data.FEATURE_FLAGS}

    for bug in PLANTED_BUGS:
        assert by_key[bug.flag]["enabled"] is False
        assert by_key[bug.flag]["description"]


def test_the_checkout_bug_is_visible_on_the_cheapest_product() -> None:
    """``BUG_CHECKOUT_TOTAL`` needs a tax of at least a cent to be observable.

    Its trigger is "any non-empty cart", so the smallest possible cart - one
    unit of the cheapest seeded product - must already show a total that differs
    from subtotal plus tax (design Decision 10).
    """
    cheapest = min(product["price"] for product in seed_data.PRODUCT_FIXTURES)

    assert round(cheapest * default_tax_rate(), 2) >= 0.01


def test_seeding_adds_the_new_bug_row_and_keeps_existing_values(temp_database) -> None:
    """An existing database gains the row without losing a toggled flag."""

    async def seed_over_an_older_database() -> None:
        from backend.app.core.db import get_session_factory, init_db, shutdown_db

        await init_db()
        session_factory = get_session_factory()
        try:
            async with session_factory() as session:
                # The state of a database seeded before this change: the older
                # bug rows exist, one of them switched on by a facilitator, and
                # BUG_CHECKOUT_TOTAL does not exist yet.
                await session.execute(
                    seed_data.FeatureFlag.__table__.insert(),
                    [
                        {"key": "BUG_WRONG_PRICE", "description": "older row", "enabled": True},
                        {"key": "BUG_MISSING_BUTTON", "description": "older row", "enabled": False},
                    ],
                )
                await session.commit()
                await seed_data.seed_feature_flags(session)
        finally:
            await shutdown_db()

    asyncio.run(seed_over_an_older_database())

    rows = flag_rows(temp_database)
    assert rows[NEW_BUG_FLAG] == 0
    assert rows["BUG_WRONG_PRICE"] == 1, "an existing value is never overwritten"
    assert set(BUG_FLAGS) <= set(rows)
