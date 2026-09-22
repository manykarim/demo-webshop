"""The ``spaces`` suite runs on the shared harness (design D12).

These tests check the wiring itself: the two environment declarations this
change adds to ``backend/tests/harness.py``, the suite helpers, and the suite's
only fixture, ``shared_mode``.
"""
from __future__ import annotations

import os

import pytest

from backend.tests.harness import pin_test_environment
from backend.tests.spaces.helpers import rendered_stage, sqlite_rows


def test_pin_test_environment_neutralises_shared_mode(tmp_path):
    """A developer's shared-mode environment is pinned off and stripped."""
    environ = {"WORKSHOP_SHARED_MODE": "true", "WORKSHOP_ADMIN_TOKEN": "x"}

    pin_test_environment(environ, tmp_path)

    assert environ["WORKSHOP_SHARED_MODE"] == "false"
    assert "WORKSHOP_ADMIN_TOKEN" not in environ


def test_process_environment_is_pinned_for_the_session():
    """The root conftest applied the declarations before the first app import."""
    assert os.environ["WORKSHOP_SHARED_MODE"] == "false"
    assert "WORKSHOP_ADMIN_TOKEN" not in os.environ


def test_seeded_app_client_serves_the_seeded_database(seeded_app_client):
    """``sqlite_rows`` reads the very database the seeded client runs on."""
    assert seeded_app_client.get("/health").status_code == 200
    assert sqlite_rows("select count(*) from products") == [(12,)]
    assert sqlite_rows(
        "select email from users where email = ?", ("jamie@flowlinesupply.com",)
    ) == [("jamie@flowlinesupply.com",)]


@pytest.mark.parametrize(
    ("flag_key", "expected_stage"),
    [
        (None, "v1"),
        ("LOCATOR_V2", "v2"),
        ("LOCATOR_V3", "v3"),
        ("LOCATOR_V4", "v4"),
    ],
)
def test_rendered_stage_reads_the_product_listing(app_client, flag_key, expected_stage):
    """Each locator flag alone puts ``/products`` in its own stage."""
    if flag_key is not None:
        response = app_client.put(f"/api/admin/flags/{flag_key}", json={"enabled": True})
        assert response.status_code == 200

    listing = app_client.get("/products")
    assert listing.status_code == 200
    assert rendered_stage(listing.text) == expected_stage


# --- the suite fixture ``shared_mode`` (task 2.1) ---------------------------
# The order of these three tests is the assertion: the fixture must not leak
# into the tests around it.


def test_shared_mode_is_off_without_the_fixture():
    from backend.app.core.config import settings

    assert settings.shared_mode is False


def test_shared_mode_fixture_turns_shared_mode_on(shared_mode):
    from backend.app.core.config import settings

    assert settings.shared_mode is True
    assert settings.admin_token is not None
    assert settings.admin_token.get_secret_value() == shared_mode


def test_shared_mode_is_off_again_afterwards():
    from backend.app.core.config import settings

    assert settings.shared_mode is False
