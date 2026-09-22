"""Schema on start-up: space flag table, order space column (tasks 4.1, 4.2).

Every test runs on the ``temp_database`` fixture, so ``init_db()`` works on an
empty file that only this test owns. Pre-change databases are built with stdlib
``sqlite3`` - the DDL below is the schema as it was before this change - and are
then handed to ``init_db()``, which is what a persisted local database gets on
the next start (design D3).
"""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from backend.app.core.db import ORDER_SPACE_INDEX
from backend.tests.spaces.helpers import sqlite_rows

#: ``orders`` exactly as the schema before this change created it: user and
#: document columns present, no ``space``.
PRE_CHANGE_ORDERS_DDL = """
CREATE TABLE orders (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    order_number VARCHAR(32) NOT NULL UNIQUE,
    user_id INTEGER,
    customer_name VARCHAR(120) NOT NULL,
    customer_email VARCHAR(120) NOT NULL,
    customer_address VARCHAR(255) NOT NULL,
    subtotal FLOAT NOT NULL,
    tax FLOAT NOT NULL,
    total FLOAT NOT NULL,
    status VARCHAR(32),
    created_at DATETIME,
    shipping_address_id INTEGER,
    billing_address_id INTEGER,
    payment_method_id INTEGER
)
"""

#: A second pre-change table, so ``create_all`` really meets an existing file.
PRE_CHANGE_FEATURE_FLAGS_DDL = """
CREATE TABLE feature_flags (
    id INTEGER NOT NULL PRIMARY KEY,
    key VARCHAR(64) NOT NULL UNIQUE,
    description TEXT,
    enabled BOOLEAN NOT NULL
)
"""

INSERT_ORDER = """
INSERT INTO orders (
    order_number, user_id, customer_name, customer_email, customer_address,
    subtotal, tax, total, status, created_at
) VALUES (?, ?, 'Demo Person', 'demo@example.com', '1 Demo Street',
          10.0, 1.0, 11.0, 'processing', '2024-01-01 00:00:00')
"""


def run_init_db() -> None:
    """Run ``init_db()`` in its own event loop, as a fresh process start does."""

    async def _run() -> None:
        from backend.app.core.db import init_db, shutdown_db

        await init_db()
        await shutdown_db()

    asyncio.run(_run())


def run_seed_main() -> None:
    """Run the seed entrypoint (which calls ``init_db()`` itself)."""

    async def _run() -> None:
        from backend.app.core.db import shutdown_db
        from backend.app.seeds import seed_data

        await seed_data.main()
        await shutdown_db()

    asyncio.run(_run())


def write_pre_change_database(database_path: Path, *, orders: bool = True) -> None:
    """Create a database file holding only the pre-change tables."""
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(PRE_CHANGE_FEATURE_FLAGS_DDL)
        if orders:
            connection.execute(PRE_CHANGE_ORDERS_DDL)
            connection.execute(INSERT_ORDER, ("ORD-USER", 1))
            connection.execute(INSERT_ORDER, ("ORD-RUNTIME", None))
        connection.commit()
    finally:
        connection.close()


def insert_legacy_runtime_order(database_path: Path, order_number: str) -> None:
    """Write an order the way an older image writes it: no user, no space."""
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(INSERT_ORDER, (order_number, None))
        connection.commit()
    finally:
        connection.close()


def order_spaces() -> dict[str, str | None]:
    """``order_number -> space`` for every order in the active database."""
    return dict(sqlite_rows("SELECT order_number, space FROM orders ORDER BY id"))


# ---------------------------------------------------------------------------
# Task 4.1 - the space flag table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pre_change_file", [False, True], ids=["fresh", "pre-change"])
def test_space_feature_flags_table_is_created(temp_database: Path, pre_change_file: bool) -> None:
    if pre_change_file:
        write_pre_change_database(temp_database)

    run_init_db()

    columns = {row[1]: row for row in sqlite_rows("PRAGMA table_info(space_feature_flags)")}
    assert set(columns) == {"space", "key", "enabled"}
    assert columns["space"][2] == "VARCHAR(39)"
    assert columns["key"][2] == "VARCHAR(64)"
    assert columns["enabled"][3] == 1, "enabled must be NOT NULL"
    # ``pk`` is the 1-based position inside the primary key.
    assert columns["space"][5] == 1
    assert columns["key"][5] == 2


# ---------------------------------------------------------------------------
# Task 4.2 - the order space column, its index and the backfill
# ---------------------------------------------------------------------------


def test_pre_change_orders_gain_space_column_index_and_backfill(temp_database: Path) -> None:
    write_pre_change_database(temp_database)

    run_init_db()

    columns = {row[1]: row for row in sqlite_rows("PRAGMA table_info(orders)")}
    assert "space" in columns
    assert columns["space"][2] == "VARCHAR(39)"
    indexes = {row[1] for row in sqlite_rows("PRAGMA index_list(orders)")}
    assert ORDER_SPACE_INDEX in indexes
    # The order without a user is a runtime checkout and becomes scoped; the
    # order of a user is seeded history and stays visible in every space.
    assert order_spaces() == {"ORD-USER": None, "ORD-RUNTIME": "default"}


def test_backfill_runs_on_every_start_and_is_idempotent(temp_database: Path) -> None:
    write_pre_change_database(temp_database)
    run_init_db()

    # An older image after a rollback writes an order with no user and no space.
    insert_legacy_runtime_order(temp_database, "ORD-ROLLBACK")
    assert order_spaces()["ORD-ROLLBACK"] is None

    run_init_db()
    assert order_spaces() == {
        "ORD-USER": None,
        "ORD-RUNTIME": "default",
        "ORD-ROLLBACK": "default",
    }

    before = sqlite_rows("SELECT id, order_number, user_id, space FROM orders ORDER BY id")
    run_init_db()
    assert sqlite_rows("SELECT id, order_number, user_id, space FROM orders ORDER BY id") == before


def test_seeded_orders_keep_no_space(temp_database: Path) -> None:
    run_seed_main()

    spaces = order_spaces()
    assert spaces, "seeding wrote no order history"
    assert set(spaces.values()) == {None}
