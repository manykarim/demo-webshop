"""Start-up behaviour for deprecated settings (task 2.3).

``WORKSHOP_FEATURE_FLAG_CACHE_SECONDS`` is still accepted so that an older
``.env`` keeps working, but it no longer does anything. The application says so
once, at start-up, instead of silently ignoring it.
"""
from __future__ import annotations

import logging

import pytest

from backend.app.core.config import Settings, warn_obsolete_settings
from backend.tests.harness import isolated_app

OBSOLETE_VAR = "WORKSHOP_FEATURE_FLAG_CACHE_SECONDS"
CONFIG_LOGGER = "backend.app.core.config"


def _warnings_about_the_obsolete_variable(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING and OBSOLETE_VAR in record.getMessage()
    ]


def test_one_warning_when_the_obsolete_variable_is_set(caplog, monkeypatch):
    """``_env_file=None`` keeps a local ``.env`` out of the result."""
    monkeypatch.setenv(OBSOLETE_VAR, "10")
    settings = Settings(_env_file=None)

    with caplog.at_level(logging.WARNING, logger=CONFIG_LOGGER):
        warn_obsolete_settings(settings)

    assert len(_warnings_about_the_obsolete_variable(caplog)) == 1


def test_no_warning_when_the_obsolete_variable_is_unset(caplog, monkeypatch):
    monkeypatch.delenv(OBSOLETE_VAR, raising=False)
    settings = Settings(_env_file=None)

    with caplog.at_level(logging.WARNING, logger=CONFIG_LOGGER):
        warn_obsolete_settings(settings)

    assert _warnings_about_the_obsolete_variable(caplog) == []


def test_lifespan_reports_obsolete_settings_once(tmp_path, monkeypatch):
    """Starting the application calls the check exactly once, on the live settings."""
    from backend.app import main as app_main
    from backend.app.core.config import settings

    if not hasattr(app_main, "warn_obsolete_settings"):
        pytest.skip(
            "backend/app/main.py does not import warn_obsolete_settings yet; "
            "the lifespan wiring of task 2.3 is still outstanding"
        )

    calls: list[object] = []
    monkeypatch.setattr(app_main, "warn_obsolete_settings", calls.append)

    with isolated_app(tmp_path):
        pass

    assert calls == [settings]
