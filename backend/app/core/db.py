from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator, Final

from sqlalchemy import event, make_url, text
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .config import settings
from .spaces import DEFAULT_SPACE
from ..models.base import Base
from ..models import cart  # noqa: F401  # ensure model registration
from ..models import feature_flag  # noqa: F401
from ..models import order  # noqa: F401
from ..models import product  # noqa: F401
from ..models import user  # noqa: F401

logger = logging.getLogger(__name__)

async_engine: AsyncEngine | None = None
async_session_factory: async_sessionmaker[AsyncSession] | None = None

#: How long a writer waits for a concurrent writer's lock, in milliseconds,
#: before SQLite gives up with ``database is locked`` (design D9).
SQLITE_BUSY_TIMEOUT_MS: Final[int] = 5000

#: Connections kept open, and extra ones a burst may open on top of them. The
#: SQLAlchemy defaults (5 + 10) are below the workshop target of 40 concurrent
#: spaces. Task 14.2 tunes these values and task 14.4 confirms them.
SQLITE_POOL_SIZE: Final[int] = 20
SQLITE_MAX_OVERFLOW: Final[int] = 20

#: The PRAGMAs every new file-backed SQLite connection runs (design D9). WAL
#: lets readers work while one writer commits, the busy timeout turns a
#: momentary writer collision into a short wait instead of an error, and
#: ``synchronous=NORMAL`` is safe enough for disposable workshop data.
SQLITE_PRAGMAS: Final[tuple[str, ...]] = (
    "journal_mode=WAL",
    f"busy_timeout={SQLITE_BUSY_TIMEOUT_MS}",
    "synchronous=NORMAL",
)


def _is_file_sqlite(url: str) -> bool:
    """Whether ``url`` is a SQLite database that lives in a file.

    ``:memory:`` - and a URL with no database at all, which SQLite also treats
    as in-memory - is excluded: such a database is never shared between
    connections, gets a ``StaticPool`` that accepts no ``pool_size``, and
    cannot use WAL.
    """
    try:
        parsed = make_url(url)
    except (ArgumentError, ValueError):
        return False
    if parsed.get_backend_name() != "sqlite":
        return False
    database = parsed.database
    return bool(database) and database != ":memory:"


def _apply_sqlite_pragmas(dbapi_connection, connection_record) -> None:
    """Run :data:`SQLITE_PRAGMAS` on a freshly opened connection (design D9).

    Registered for the ``connect`` event of the *sync* engine, which is where
    SQLAlchemy emits it even for the async driver, so the plain DBAPI cursor
    below is the documented way to send PRAGMAs with ``aiosqlite``.

    ``journal_mode`` is the only one that can quietly refuse - a database on a
    filesystem without shared memory stays in ``delete`` mode. The shop then
    logs a warning and carries on with the slower journal rather than failing
    to start.
    """
    cursor = dbapi_connection.cursor()
    try:
        journal_mode = None
        for pragma in SQLITE_PRAGMAS:
            cursor.execute(f"PRAGMA {pragma}")
            # Each of these PRAGMAs answers with its new value; the rows are
            # drained so the cursor can be reused for the next statement.
            rows = cursor.fetchall()
            if pragma.startswith("journal_mode") and rows:
                journal_mode = rows[0][0]
    finally:
        cursor.close()

    if str(journal_mode).lower() != "wal":
        logger.warning(
            "SQLite write-ahead logging is not active (journal_mode=%s); "
            "concurrent workshop spaces may see lock contention.",
            journal_mode,
        )


def get_engine() -> AsyncEngine:
    global async_engine
    if async_engine is None:
        database_url = settings.database_url
        if _is_file_sqlite(database_url):
            async_engine = create_async_engine(
                database_url,
                echo=False,
                pool_size=SQLITE_POOL_SIZE,
                max_overflow=SQLITE_MAX_OVERFLOW,
            )
            event.listen(async_engine.sync_engine, "connect", _apply_sqlite_pragmas)
        else:
            async_engine = create_async_engine(database_url, echo=False)
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


#: Index that keeps the per-space order queries cheap. The name is the one
#: ``index=True`` on ``Order.space`` generates, so ``CREATE INDEX IF NOT EXISTS``
#: below is a no-op on a database that ``create_all`` has just built.
ORDER_SPACE_INDEX = "ix_orders_space"


async def ensure_product_columns(session) -> None:
    """Add product columns that an older database file does not have yet."""
    result = await session.execute(text("PRAGMA table_info(products)"))
    columns = {row[1] for row in result.fetchall()}
    if "rating" not in columns:
        await session.execute(text("ALTER TABLE products ADD COLUMN rating FLOAT"))
    if "review_count" not in columns:
        await session.execute(text("ALTER TABLE products ADD COLUMN review_count INTEGER DEFAULT 0"))
    await session.commit()


async def ensure_order_columns(session) -> None:
    """Bring an older ``orders`` table up to the current schema (design D3).

    Adds the columns a persisted database may be missing, then - on *every* call,
    not only the one that adds the column - scopes the orders that belong to no
    user and no space to ``default``. Those can only be runtime checkouts from
    before this change, or ones written by an older image after a rollback:
    seeded demo orders always have a user and keep ``space IS NULL``, so they
    stay visible in every space. The update is idempotent.
    """
    result = await session.execute(text("PRAGMA table_info(orders)"))
    columns = {row[1] for row in result.fetchall()}
    alterations = []
    if "user_id" not in columns:
        alterations.append("ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE SET NULL")
    if "shipping_address_id" not in columns:
        alterations.append("ADD COLUMN shipping_address_id INTEGER REFERENCES addresses(id) ON DELETE SET NULL")
    if "billing_address_id" not in columns:
        alterations.append("ADD COLUMN billing_address_id INTEGER REFERENCES addresses(id) ON DELETE SET NULL")
    if "payment_method_id" not in columns:
        alterations.append("ADD COLUMN payment_method_id INTEGER REFERENCES payment_methods(id) ON DELETE SET NULL")
    if "space" not in columns:
        alterations.append("ADD COLUMN space VARCHAR(39)")
    for clause in alterations:
        await session.execute(text(f"ALTER TABLE orders {clause}"))

    await session.execute(
        text("UPDATE orders SET space = :space WHERE space IS NULL AND user_id IS NULL"),
        {"space": DEFAULT_SPACE},
    )
    await session.execute(
        text(f"CREATE INDEX IF NOT EXISTS {ORDER_SPACE_INDEX} ON orders (space)")
    )
    await session.commit()


async def init_db() -> None:
    """Create missing tables and upgrade an existing database file.

    The schema helpers run here rather than in the seeder, so a plain
    ``uvicorn`` start, a test on a persisted database and the container
    entrypoint (which seeds before the app starts) all get the upgrade.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = get_session_factory()
    async with session_factory() as session:
        await ensure_product_columns(session)
        await ensure_order_columns(session)


async def shutdown_db() -> None:
    global async_engine
    if async_engine is not None:
        await async_engine.dispose()
        async_engine = None
        await asyncio.sleep(0)
