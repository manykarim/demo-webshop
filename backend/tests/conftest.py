"""Root conftest for every suite under ``backend/tests`` (design D11).

pytest loads this file before it collects any test below ``backend/tests``, so
the environment is pinned here - at module top, before any application import -
and the canonical fixtures live here. ``backend.app`` is imported only inside
fixture bodies, so a live test run of a later change does not import the app at
collection time.

Later changes add their fixtures to this file (``pdf_unavailable``,
``fake_weasyprint``, ``seeded_app_client``) and their suite-specific helpers to
a conftest of their own test subdirectory. They never create a second
root-level conftest and never set environment variables themselves.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

import pytest

from backend.tests.harness import isolated_app, isolated_database, pin_test_environment

#: Storage for tests that import the app outside the harness. Pinned before the
#: first application import, so ``Settings`` never points into the repository.
_SESSION_TMP_DIR = tempfile.mkdtemp(prefix="workshop-tests-")
pin_test_environment(os.environ, _SESSION_TMP_DIR)


def pytest_unconfigure(config: pytest.Config) -> None:
    shutil.rmtree(_SESSION_TMP_DIR, ignore_errors=True)


@pytest.fixture
def temp_database(tmp_path: Path) -> Iterator[Path]:
    """Patched settings and engine globals on an empty temporary database.

    No client and no seeding. Yields the database file path.
    """
    with isolated_database(tmp_path) as database_path:
        yield database_path


@pytest.fixture
def app_client(tmp_path: Path):
    """A ``TestClient`` on a private database with products and flags seeded.

    No users are seeded, so no PDF rendering is involved.
    """
    with isolated_app(tmp_path) as client:
        yield client


@pytest.fixture
def seeded_app_client(tmp_path: Path):
    """A ``TestClient`` on a private database with the full demo data seeded.

    Products, feature flags and the demo users ``jamie@flowlinesupply.com`` and
    ``alex.productlead@example.com`` with their addresses, payment methods and
    order history. Seeding renders no document (design D4), so the temporary PDF
    directory stays empty until a document endpoint is called.

    This is the fixture to use wherever seeded users or seeded orders are needed.
    """
    with isolated_app(tmp_path, seed_users=True) as client:
        yield client


@contextmanager
def _patched_weasyprint(replacement: ModuleType | None) -> Iterator[None]:
    """Install ``replacement`` as ``sys.modules['weasyprint']`` for one test.

    The loader memo of ``pdf_service`` is cleared on the way in and on the way
    out, so neither a result from an earlier test leaks in nor this one leaks
    out, and the previous ``sys.modules`` entry is restored.
    """
    from backend.app.services import pdf_service

    missing = object()
    previous = sys.modules.get("weasyprint", missing)

    pdf_service._load_weasyprint.cache_clear()
    sys.modules["weasyprint"] = replacement  # type: ignore[assignment]
    try:
        yield
    finally:
        if previous is missing:
            sys.modules.pop("weasyprint", None)
        else:
            sys.modules["weasyprint"] = previous  # type: ignore[assignment]
        pdf_service._load_weasyprint.cache_clear()


@pytest.fixture
def pdf_unavailable() -> Iterator[None]:
    """Make WeasyPrint unimportable, as on a machine without Pango.

    ``sys.modules['weasyprint'] = None`` makes ``import weasyprint`` raise
    ``ImportError``, which is exactly what the loader treats as "rendering is
    unavailable here".
    """
    with _patched_weasyprint(None):
        yield


@pytest.fixture
def fake_weasyprint() -> Iterator[list[str]]:
    """Render PDFs without native libraries and record the HTML.

    Yields the list of HTML strings handed to ``weasyprint.HTML``, in render
    order, so a test can assert on a document's content. ``write_pdf`` writes a
    short ``%PDF-`` file, so the served response is a plausible PDF.
    """
    rendered_html: list[str] = []
    module = ModuleType("weasyprint")

    class HTML:
        def __init__(self, string: str, base_url: str | None = None) -> None:
            self.string = string
            self.base_url = base_url
            rendered_html.append(string)

        def write_pdf(self, target) -> None:
            Path(target).write_bytes(b"%PDF-1.7 fake document\n")

    module.HTML = HTML  # type: ignore[attr-defined]

    with _patched_weasyprint(module):
        yield rendered_html
