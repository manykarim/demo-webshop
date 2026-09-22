"""Unit tests for the process-wide test environment declared in the harness."""
from __future__ import annotations

from pathlib import Path

from backend.tests import harness
from backend.tests.harness import pin_test_environment


def _database_path(environ: dict[str, str]) -> Path:
    url = environ["WORKSHOP_DATABASE_URL"]
    assert url.startswith("sqlite+aiosqlite:///")
    return Path(url.removeprefix("sqlite+aiosqlite:///"))


def test_pin_test_environment_scrubs_and_points_storage_at_tmp_dir(tmp_path):
    environ = {
        "WORKSHOP_APP_VERSION": "workshop-2026-10",
        "WORKSHOP_FLAG_LOCATOR_V2": "1",
        "WORKSHOP_AI_PROVIDER": "mock",
    }

    pin_test_environment(environ, tmp_path)

    assert "WORKSHOP_APP_VERSION" not in environ
    assert "WORKSHOP_FLAG_LOCATOR_V2" not in environ
    assert environ["WORKSHOP_AI_PROVIDER"] == "mock"
    assert _database_path(environ) == (tmp_path / "workshop.db").resolve()
    assert Path(environ["WORKSHOP_PDF_OUTPUT_DIR"]) == (tmp_path / "pdfs").resolve()


def test_pin_test_environment_applies_pinned_variables(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "PINNED_ENV_VARS", {"WORKSHOP_EXAMPLE": "x"})
    environ: dict[str, str] = {}

    pin_test_environment(environ, tmp_path)

    assert environ["WORKSHOP_EXAMPLE"] == "x"
    assert _database_path(environ) == (tmp_path / "workshop.db").resolve()
    assert Path(environ["WORKSHOP_PDF_OUTPUT_DIR"]) == (tmp_path / "pdfs").resolve()
