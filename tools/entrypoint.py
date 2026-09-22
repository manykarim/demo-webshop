"""Container entrypoint: check storage, seed, then hand over to the command.

Wired as ``ENTRYPOINT ["python", "-m", "tools.entrypoint"]`` with the uvicorn
command in ``CMD`` (design D4/D5). Run directly it behaves the same::

    python -m tools.entrypoint uvicorn backend.app.main:app --host 0.0.0.0 --port 9090

In order it:

1. makes sure the SQLite directory and the PDF output directory exist and are
   writable by the current user, and exits with an actionable message otherwise,
   so a misconfigured database URL can be told apart from a bind mount owned by
   the wrong uid;
2. runs the idempotent seed routine and disposes the engine, exiting non-zero
   before the port ever opens if seeding fails;
3. replaces itself with the given command through :func:`os.execvp`, so that
   process becomes PID 1 and receives the container's stop signals directly.

Because seeding lives here rather than in the image build or the application
lifespan, an overridden command (a Coolify custom start command, a one-off shell)
still gets a seeded database, and an empty mounted volume is seeded on first
start.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from backend.app.core import db as db_module
from backend.app.core.config import settings
from backend.app.seeds import seed_data

logger = logging.getLogger("workshop.entrypoint")

USAGE = "usage: python -m tools.entrypoint <command> [args...]"

#: The uid the image runs as, named in the fix suggested for a bind mount.
IMAGE_UID = 1000
IMAGE_GID = 1000


def database_directory(database_url: str) -> Path | None:
    """The directory holding the SQLite file of ``database_url``.

    Handles both SQLAlchemy spellings, ``sqlite+aiosqlite:///relative/path.db``
    and ``sqlite+aiosqlite:////absolute/path.db``. Returns ``None`` for anything
    whose storage this process does not own - a non-SQLite URL (a server the
    container only connects to) or an in-memory database - so the writability
    check is skipped rather than guessed.
    """
    scheme, separator, rest = database_url.partition("://")
    if not separator or scheme.split("+", 1)[0].lower() != "sqlite":
        return None

    # One leading slash separates the (always empty) host from the path, so
    # ``///x.db`` is relative and ``////x.db`` is absolute.
    location = rest.split("?", 1)[0].removeprefix("/")
    if not location or location == ":memory:":
        return None

    return Path(location).expanduser().resolve().parent


def _unwritable_message(directory: Path, reason: OSError) -> str:
    """An actionable message for a directory this process cannot write."""
    return (
        f"Cannot write the directory {directory} ({reason.strerror or reason}).\n"
        f"  effective database URL: {settings.database_url}\n"
        f"  PDF output directory:   {settings.pdf_output_dir}\n"
        f"  running as uid {os.getuid()}, gid {os.getgid()}\n"
        f"Fix: for a bind mount, run 'chown -R {IMAGE_UID}:{IMAGE_GID} {directory}' on the host; "
        f"otherwise start the container with '--user <uid>:<gid>' matching the directory's owner, "
        f"or point the database URL at a directory this user owns."
    )


def ensure_writable_directory(directory: Path) -> str | None:
    """Create ``directory`` if missing and prove it is writable.

    Returns ``None`` when the directory is usable, or the error message to print
    otherwise. Writability is proved by creating and removing a probe file rather
    than by :func:`os.access`, which reports the permission bits instead of what
    the filesystem actually allows (a read-only mount, for example).
    """
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return _unwritable_message(directory, exc)

    probe = directory / f".workshop-write-probe-{os.getpid()}"
    try:
        probe.touch()
    except OSError as exc:
        return _unwritable_message(directory, exc)
    finally:
        try:
            probe.unlink()
        except OSError:
            pass

    return None


def prepare_storage() -> str | None:
    """Check every directory the shop writes to. Returns an error message or ``None``."""
    directories = [Path(settings.pdf_output_dir).expanduser()]

    db_dir = database_directory(settings.database_url)
    if db_dir is not None:
        # Checked first: a wrong database URL is the more confusing failure.
        directories.insert(0, db_dir)
    else:
        logger.info("Database URL %s is not a local SQLite file; skipping the directory check", settings.database_url)

    for directory in directories:
        message = ensure_writable_directory(directory)
        if message is not None:
            return message
        logger.info("Storage directory ready: %s", directory)

    return None


async def _seed() -> None:
    """Seed and dispose the engine inside one event loop.

    The engine belongs to the loop that created it, so it has to be disposed
    before :func:`os.execvp` and before any other loop is started.
    """
    try:
        await seed_data.main()
    finally:
        try:
            await db_module.shutdown_db()
        except Exception:  # pragma: no cover - best effort; the process is leaving
            logger.warning("Disposing the database engine failed", exc_info=True)


def main(argv: list[str] | None = None) -> int:
    """Run the entrypoint. Returns the exit code; normally it never returns."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    command = list(sys.argv[1:] if argv is None else argv)
    if not command:
        # Checked before any work, so a usage mistake is not preceded by a seed
        # run whose output would bury the message.
        print(USAGE, file=sys.stderr)
        return 2

    message = prepare_storage()
    if message is not None:
        print(message, file=sys.stderr)
        return 1

    try:
        asyncio.run(_seed())
    except Exception:
        logger.exception("Seeding failed; not starting %s", command[0])
        return 1

    logger.info("Starting %s", " ".join(command))
    try:
        os.execvp(command[0], command)
    except OSError as exc:
        print(f"Cannot execute {command[0]!r}: {exc}", file=sys.stderr)
        return 127

    return 0  # pragma: no cover - execvp replaces this process


if __name__ == "__main__":
    sys.exit(main())
