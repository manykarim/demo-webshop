"""The one shared test harness for every suite under ``backend/tests`` (design D11).

This is a plain module: it declares no fixtures and imports nothing from
``backend.app`` at module level, so that ``backend/tests/conftest.py`` can pin
the process environment *before* the application - and with it the process-wide
``Settings`` instance and the engine globals - is imported for the first time.

Test suites added by later changes reuse :func:`isolated_app` and the fixtures of
the root ``conftest.py`` by their exact names instead of building their own
harness. A setting that must be neutral in every test gets an entry in the
environment declarations below rather than environment code in a conftest.
"""
from __future__ import annotations

import asyncio
from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Process-wide test environment
# ---------------------------------------------------------------------------

#: Variables removed from the environment before the app is imported, because a
#: developer or CI value would change what the tests observe.
SCRUBBED_ENV_VARS: tuple[str, ...] = ("WORKSHOP_APP_VERSION", "WORKSHOP_ADMIN_TOKEN")

#: Whole families of variables removed for the same reason.
SCRUBBED_ENV_PREFIXES: tuple[str, ...] = ("WORKSHOP_FLAG_",)

#: Variables pinned to a fixed value for the whole test session.
PINNED_ENV_VARS: dict[str, str] = {"WORKSHOP_SHARED_MODE": "false"}


def _database_url(database_path: Path) -> str:
    """The async SQLite URL for ``database_path``."""
    return f"sqlite+aiosqlite:///{database_path}"


def pin_test_environment(environ: MutableMapping[str, str], tmp_dir) -> None:
    """Make ``environ`` neutral for tests and point storage into ``tmp_dir``.

    Removes :data:`SCRUBBED_ENV_VARS` and everything matching
    :data:`SCRUBBED_ENV_PREFIXES`, applies :data:`PINNED_ENV_VARS`, and points
    ``WORKSHOP_DATABASE_URL`` and ``WORKSHOP_PDF_OUTPUT_DIR`` into ``tmp_dir``, so
    that a test which imports the app outside :func:`isolated_app` can never
    write ``./workshop.db`` or into ``backend/app/static/pdfs``.
    """
    for name in SCRUBBED_ENV_VARS:
        environ.pop(name, None)

    for prefix in SCRUBBED_ENV_PREFIXES:
        for name in [key for key in environ if key.startswith(prefix)]:
            environ.pop(name, None)

    for name, value in PINNED_ENV_VARS.items():
        environ[name] = value

    tmp_path = Path(tmp_dir).resolve()
    environ["WORKSHOP_DATABASE_URL"] = _database_url(tmp_path / "workshop.db")
    environ["WORKSHOP_PDF_OUTPUT_DIR"] = str(tmp_path / "pdfs")


# ---------------------------------------------------------------------------
# Isolated database and application
# ---------------------------------------------------------------------------


def _clear_feature_flag_cache() -> None:
    """Empty the process-local feature flag cache, while that module has one.

    The cache outlives a test's database and would otherwise hand one test's
    flag values to the next.
    """
    from backend.app.core import feature_flags

    cache = getattr(feature_flags, "_cache", None)
    if cache is not None:
        cache.clear()


def _reset_engine_globals() -> None:
    """Dispose the current engine, if any, and forget the engine globals."""
    from backend.app.core import db as db_module

    engine = db_module.async_engine
    db_module.async_engine = None
    db_module.async_session_factory = None
    if engine is None:
        return
    try:
        asyncio.run(engine.dispose())
    except Exception:  # pragma: no cover - best effort cleanup
        # The engine's own event loop is gone; the SQLite files are temporary
        # and are removed with the test's directory anyway.
        pass


@contextmanager
def isolated_database(tmp_dir) -> Iterator[Path]:
    """Point settings and the engine globals at a SQLite file in ``tmp_dir``.

    Yields the database file path. Nothing is created and nothing is seeded, so
    the caller decides when (and whether) the schema comes into existence. This
    is the shared core of :func:`isolated_app` and of the ``temp_database``
    fixture.
    """
    from backend.app.core import db as db_module
    from backend.app.core.config import settings

    tmp_path = Path(tmp_dir)
    database_path = tmp_path / "workshop.db"
    pdf_output_dir = tmp_path / "pdfs"
    pdf_output_dir.mkdir(parents=True, exist_ok=True)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(settings, "database_url", _database_url(database_path))
        monkeypatch.setattr(settings, "pdf_output_dir", str(pdf_output_dir))
        monkeypatch.setattr(db_module, "async_engine", None)
        monkeypatch.setattr(db_module, "async_session_factory", None)
        _clear_feature_flag_cache()
        try:
            yield database_path
        finally:
            _reset_engine_globals()
            _clear_feature_flag_cache()


async def _prepare_database(seed_users: bool) -> None:
    """Create the schema, seed it and dispose the engine, in one event loop."""
    from backend.app.core.db import get_session_factory, init_db, shutdown_db
    from backend.app.seeds import seed_data

    if seed_users:
        # Products, flags, demo users with addresses, payment methods and order
        # history. ``main()`` runs ``init_db()`` itself.
        await seed_data.main()
    else:
        await init_db()
        session_factory = get_session_factory()
        async with session_factory() as session:
            await seed_data.seed_products(session)
            await seed_data.seed_feature_flags(session)

    await shutdown_db()


@contextmanager
def isolated_app(tmp_dir, *, seed_users: bool = False):
    """Yield a ``TestClient`` for the app on a private database in ``tmp_dir``.

    The client is entered as a context manager, so the application lifespan runs.
    Settings and the engine globals are patched for the duration and restored
    afterwards, the feature flag cache is cleared on enter and on exit, and
    ``app.dependency_overrides`` is cleared on exit.

    ``seed_users=True`` additionally seeds the demo users and their order
    history. The helper is scope-agnostic: function-, package- and
    session-scoped fixtures can all use it.
    """
    from starlette.testclient import TestClient

    from backend.app.core import db as db_module

    with isolated_database(tmp_dir):
        asyncio.run(_prepare_database(seed_users))
        # The seeding loop is closed; the app builds its own engine on startup.
        db_module.async_engine = None
        db_module.async_session_factory = None

        from backend.app.main import app

        try:
            with TestClient(app) as client:
                yield client
        finally:
            app.dependency_overrides.clear()
