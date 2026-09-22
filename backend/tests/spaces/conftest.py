"""Suite conftest for the ``spaces`` tests (design D12).

The shared harness owns the environment and the canonical fixtures: this file
sets no environment variables, resets no engine globals and redefines none of
``temp_database``, ``app_client``, ``seeded_app_client``, ``pdf_unavailable`` or
``fake_weasyprint``. ``backend.app`` is imported only inside fixture bodies, so
collecting this suite does not import the application.
"""
from __future__ import annotations

from collections.abc import Iterator

import pytest

#: The admin token that every shared-mode test in this suite uses.
SHARED_MODE_TOKEN = "test-token"


@pytest.fixture
def shared_mode(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Turn shared mode on for one test and yield its admin token.

    The process environment pins ``WORKSHOP_SHARED_MODE=false`` for the whole
    session, so shared mode is switched on by patching the live ``settings``
    object rather than by rebuilding it. Both values are set together, which is
    the only combination the settings validator accepts.
    """
    from pydantic import SecretStr

    from backend.app.core.config import settings

    monkeypatch.setattr(settings, "shared_mode", True)
    monkeypatch.setattr(settings, "admin_token", SecretStr(SHARED_MODE_TOKEN))
    yield SHARED_MODE_TOKEN
