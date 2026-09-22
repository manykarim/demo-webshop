"""The SQLite engine is tuned for concurrent spaces (task 10.1, design D9).

Forty participants hit one SQLite file at the same time. Without write-ahead
logging a reader blocks the one writer, without a busy timeout a momentary
collision surfaces as ``database is locked``, and with SQLAlchemy's default
pool (5 + 10) the connections run out before the spaces do.

The PRAGMAs are asserted on a connection that comes out of ``get_engine()``,
not on one this test opens itself, so the listener really is registered on the
engine the application uses.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from sqlalchemy import text

from backend.app.core.db import (
    SQLITE_BUSY_TIMEOUT_MS,
    SQLITE_MAX_OVERFLOW,
    SQLITE_POOL_SIZE,
    _apply_sqlite_pragmas,
    get_engine,
    shutdown_db,
)


def pragmas_of_a_pooled_connection() -> dict[str, object]:
    """``journal_mode``, ``busy_timeout`` and ``synchronous`` as the app sees them."""

    async def read() -> dict[str, object]:
        engine = get_engine()
        try:
            async with engine.connect() as connection:
                return {
                    name: (await connection.execute(text(f"PRAGMA {name}"))).scalar()
                    for name in ("journal_mode", "busy_timeout", "synchronous")
                }
        finally:
            await shutdown_db()

    return asyncio.run(read())


def test_a_pooled_connection_is_in_wal_mode(temp_database: Path) -> None:
    """*Concurrent spaces*: readers and the one writer no longer block each other."""
    assert pragmas_of_a_pooled_connection()["journal_mode"] == "wal"


def test_a_pooled_connection_waits_for_a_busy_writer(temp_database: Path) -> None:
    """A collision between two spaces becomes a short wait, not an error."""
    assert pragmas_of_a_pooled_connection()["busy_timeout"] == SQLITE_BUSY_TIMEOUT_MS


def test_a_pooled_connection_syncs_normally(temp_database: Path) -> None:
    """``synchronous=NORMAL`` is PRAGMA value 1; the data is disposable."""
    assert pragmas_of_a_pooled_connection()["synchronous"] == 1


def test_the_pool_is_sized_for_the_workshop(temp_database: Path) -> None:
    """The pool is set explicitly, well above SQLAlchemy's default of five."""
    engine = get_engine()
    try:
        assert engine.pool.size() == SQLITE_POOL_SIZE
        assert engine.pool._max_overflow == SQLITE_MAX_OVERFLOW
    finally:
        asyncio.run(shutdown_db())


def test_a_journal_mode_that_is_not_wal_is_only_a_warning(
    temp_database: Path, caplog
) -> None:
    """*WAL cannot be enabled*: the shop warns and keeps running (design D9).

    The listener is driven directly with a stub connection that reports
    ``delete``, because a filesystem without shared memory cannot be arranged
    inside a test.
    """

    class Cursor:
        def execute(self, statement: str) -> None:
            self.statement = statement

        def fetchall(self) -> list[tuple[str]]:
            return [("delete",)] if "journal_mode" in self.statement else [("0",)]

        def close(self) -> None:
            self.closed = True

    class Connection:
        def cursor(self) -> Cursor:
            return Cursor()

    with caplog.at_level(logging.WARNING, logger="backend.app.core.db"):
        _apply_sqlite_pragmas(Connection(), None)

    assert "write-ahead logging is not active" in caplog.text
    assert "delete" in caplog.text
