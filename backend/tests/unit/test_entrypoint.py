"""The container entrypoint (task 5.1, design D4/D5).

``tools/entrypoint.py`` is the only thing between a started container and
uvicorn, so all four of its outcomes are covered here: a storage directory the
user cannot write, the happy path, a failing seed, and a missing command.
"""
from __future__ import annotations

import os
import sqlite3
import stat
from contextlib import closing
from pathlib import Path

import pytest

from backend.app.core.config import settings
from backend.app.seeds import seed_data
from tools import entrypoint


def product_count(database_path: Path) -> int:
    with closing(sqlite3.connect(database_path)) as connection:
        return connection.execute("SELECT COUNT(*) FROM products").fetchone()[0]


@pytest.fixture
def no_exec(monkeypatch):
    """Record the arguments of ``os.execvp`` instead of replacing the process."""
    calls: list[tuple] = []
    monkeypatch.setattr(os, "execvp", lambda file, args: calls.append((file, list(args))))
    return calls


# ---------------------------------------------------------------------------
# Deriving the database directory
# ---------------------------------------------------------------------------


def test_database_directory_handles_both_sqlite_spellings(tmp_path):
    absolute = tmp_path / "data" / "workshop.db"
    assert entrypoint.database_directory(f"sqlite+aiosqlite:///{absolute}") == tmp_path / "data"
    assert entrypoint.database_directory("sqlite+aiosqlite:///./workshop.db") == Path.cwd()


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+asyncpg://user:pass@db:5432/shop",
        "sqlite+aiosqlite:///:memory:",
    ],
)
def test_database_directory_skips_storage_it_does_not_own(database_url):
    assert entrypoint.database_directory(database_url) is None


# ---------------------------------------------------------------------------
# The four outcomes of ``main()``
# ---------------------------------------------------------------------------


@pytest.mark.skipif(os.getuid() == 0, reason="root writes any directory, so the check cannot fail")
def test_an_unwritable_database_directory_exits_with_an_actionable_message(
    temp_database, monkeypatch, capsys, no_exec
):
    locked = temp_database.parent / "locked"
    locked.mkdir()
    database_url = f"sqlite+aiosqlite:///{locked / 'workshop.db'}"
    monkeypatch.setattr(settings, "database_url", database_url)
    locked.chmod(0o500)
    try:
        exit_code = entrypoint.main(["uvicorn", "backend.app.main:app"])
    finally:
        locked.chmod(stat.S_IRWXU)

    assert exit_code != 0
    stderr = capsys.readouterr().err
    assert str(locked) in stderr
    assert database_url in stderr
    assert "chown" in stderr
    assert str(os.getuid()) in stderr
    assert no_exec == []


def test_the_happy_path_seeds_and_hands_over_to_the_command(temp_database, no_exec):
    command = ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "9090"]

    exit_code = entrypoint.main(command)

    assert exit_code == 0
    assert product_count(temp_database) == 12
    assert no_exec == [("uvicorn", command)]
    assert Path(settings.pdf_output_dir).is_dir()


def test_a_missing_database_directory_is_created(tmp_path, monkeypatch, no_exec):
    from backend.app.core import db as db_module

    data_dir = tmp_path / "data"
    pdf_dir = tmp_path / "data" / "pdfs"
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{data_dir / 'workshop.db'}")
    monkeypatch.setattr(settings, "pdf_output_dir", str(pdf_dir))
    monkeypatch.setattr(db_module, "async_engine", None)
    monkeypatch.setattr(db_module, "async_session_factory", None)

    assert entrypoint.main(["true"]) == 0

    assert (data_dir / "workshop.db").is_file()
    assert pdf_dir.is_dir()
    assert list(pdf_dir.iterdir()) == [], "seeding renders no document"
    assert no_exec == [("true", ["true"])]


def test_a_failing_seed_exits_non_zero_and_never_starts_the_command(
    temp_database, monkeypatch, no_exec
):
    async def explode() -> None:
        raise RuntimeError("seeding is broken")

    monkeypatch.setattr(seed_data, "main", explode)

    exit_code = entrypoint.main(["uvicorn", "backend.app.main:app"])

    assert exit_code != 0
    assert no_exec == []


def test_without_a_command_the_usage_is_printed(temp_database, capsys, no_exec):
    exit_code = entrypoint.main([])

    assert exit_code != 0
    assert entrypoint.USAGE in capsys.readouterr().err
    assert no_exec == []
