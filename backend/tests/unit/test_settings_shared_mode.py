"""Shared-mode settings: the validator and the misconfigured start (D6).

Every settings object here is built with ``_env_file=None`` and both shared-mode
variables are removed from the process environment first, so neither a
developer's ``.env`` nor the ambient environment can change the outcome.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.core.config import Settings

#: Repository root: ``backend/tests/unit/<this file>``.
REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _no_shared_mode_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both shared-mode variables are absent from the process environment."""
    monkeypatch.delenv("WORKSHOP_SHARED_MODE", raising=False)
    monkeypatch.delenv("WORKSHOP_ADMIN_TOKEN", raising=False)


def test_shared_mode_is_off_and_token_unset_by_default():
    settings = Settings(_env_file=None)

    assert settings.shared_mode is False
    assert settings.admin_token is None


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({"shared_mode": True}, id="no-token"),
        pytest.param({"shared_mode": True, "admin_token": ""}, id="empty-token"),
    ],
)
def test_shared_mode_without_a_token_is_rejected(kwargs):
    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None, **kwargs)

    assert "WORKSHOP_ADMIN_TOKEN" in str(excinfo.value)


def test_shared_mode_with_a_token_is_accepted():
    settings = Settings(_env_file=None, shared_mode=True, admin_token="x")

    assert settings.shared_mode is True
    assert settings.admin_token is not None
    assert settings.admin_token.get_secret_value() == "x"


def test_admin_token_is_not_shown_in_repr():
    settings = Settings(_env_file=None, shared_mode=True, admin_token="s3cr3t-token")

    assert "s3cr3t-token" not in repr(settings)


def test_dotenv_token_does_not_rescue_shared_mode(tmp_path, monkeypatch):
    """``_env_file=None`` ignores a ``.env`` in the working directory."""
    (tmp_path / ".env").write_text("WORKSHOP_ADMIN_TOKEN=x\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None, shared_mode=True)

    assert "WORKSHOP_ADMIN_TOKEN" in str(excinfo.value)


def test_import_fails_when_shared_mode_has_no_token():
    """Scenario *Misconfigured start*: the process dies before it serves.

    ``settings`` is built while ``backend.app.main`` is imported, so importing
    the module is what uvicorn does before it binds its port. The empty token is
    passed in the environment, which wins over any value in a local ``.env``.
    """
    env = dict(os.environ)
    env["WORKSHOP_SHARED_MODE"] = "true"
    env["WORKSHOP_ADMIN_TOKEN"] = ""

    completed = subprocess.run(
        [sys.executable, "-c", "import backend.app.main"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "WORKSHOP_ADMIN_TOKEN" in completed.stderr
