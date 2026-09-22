"""Integration tests for version reporting on /health and /api/workshop/status."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
VERSION = "workshop-2026-10"
PRINT_APP_VERSION = "from backend.app.main import app; print(app.version)"


def _app_version_in_subprocess(app_version: str | None) -> str:
    """Print ``app.version`` from a fresh interpreter, with storage pinned."""
    env = dict(os.environ)
    env.pop("WORKSHOP_APP_VERSION", None)
    if app_version is not None:
        env["WORKSHOP_APP_VERSION"] = app_version

    result = subprocess.run(
        [sys.executable, "-c", PRINT_APP_VERSION],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def test_health_reports_the_default_version(app_client):
    response = app_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "dev"}


def test_workshop_status_reports_the_default_version(app_client):
    response = app_client.get("/api/workshop/status")

    assert response.status_code == 200
    assert response.json()["version"] == "dev"


def test_both_endpoints_report_the_configured_version(app_client, monkeypatch):
    from backend.app.core.config import settings

    monkeypatch.setattr(settings, "app_version", VERSION)

    assert app_client.get("/health").json() == {"status": "ok", "version": VERSION}
    assert app_client.get("/api/workshop/status").json()["version"] == VERSION


def test_openapi_version_follows_the_environment():
    assert _app_version_in_subprocess(VERSION) == VERSION
    assert _app_version_in_subprocess(None) == "dev"
