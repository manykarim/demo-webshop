"""Integration tests for the shared test harness itself (design D11)."""
from __future__ import annotations

import os
from pathlib import Path

from backend.tests.harness import isolated_app

REPO_ROOT = Path(__file__).resolve().parents[3]

#: Database paths seen by ``temp_database``, to prove tests do not share one.
_SEEN_DATABASES: list[Path] = []


def test_app_client_serves_health(app_client):
    response = app_client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_app_client_seeds_the_catalog(app_client):
    response = app_client.get("/api/products/")

    assert response.status_code == 200
    assert len(response.json()["items"]) == 12


def test_temp_database_is_inside_tmp_path(temp_database, tmp_path):
    from backend.app.core.config import settings

    assert temp_database.parent == tmp_path
    assert settings.database_url.endswith(str(temp_database))
    _SEEN_DATABASES.append(temp_database)


def test_temp_database_differs_between_tests(temp_database):
    # Runs after the test above, which recorded its own database file.
    assert temp_database not in _SEEN_DATABASES
    _SEEN_DATABASES.append(temp_database)


def test_flag_cache_does_not_leak_between_isolated_apps(tmp_path):
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()

    with isolated_app(first_dir) as client:
        response = client.put("/api/admin/flags/NEW_CART_UI", json={"enabled": True})
        assert response.status_code == 200
        assert client.get("/api/admin/flags").json()["NEW_CART_UI"] is True

    # Entered immediately afterwards, well within feature_flag_cache_seconds.
    with isolated_app(second_dir) as client:
        assert client.get("/api/admin/flags").json()["NEW_CART_UI"] is False


def test_isolated_app_restores_settings(tmp_path):
    from backend.app.core.config import settings

    before = (settings.database_url, settings.pdf_output_dir)

    with isolated_app(tmp_path) as client:
        assert client.get("/health").status_code == 200
        assert settings.database_url != before[0]
        assert settings.pdf_output_dir != before[1]

    assert (settings.database_url, settings.pdf_output_dir) == before


def test_app_client_leaves_settings_pointing_outside_the_repository(app_client):
    """Companion of the next test, which runs after this one used the fixture."""
    assert app_client.get("/health").status_code == 200


def test_settings_are_restored_after_the_app_client_fixture():
    from backend.app.core.config import settings

    assert settings.database_url == os.environ["WORKSHOP_DATABASE_URL"]
    assert settings.pdf_output_dir == os.environ["WORKSHOP_PDF_OUTPUT_DIR"]
    assert REPO_ROOT not in Path(settings.pdf_output_dir).parents
    assert str(REPO_ROOT) not in settings.database_url
