"""The browser harness itself (task 7.2).

Proves the two halves of design Decision 8's "Target server": the shop the suite
talks to is up and answers, and the stage fixture really switches the stage of
that server. With ``--base-url`` the same tests run against whatever that option
points at, and one test asserts that the option is what the fixture returned.
"""
from __future__ import annotations

import pytest

from .conftest import stage_number, workshop_status

pytestmark = pytest.mark.browser


def test_health_answers_ok(page) -> None:
    """The target server is up, whether it was started here or given."""
    response = page.request.get("/health")

    assert response.ok, response.text()
    assert response.json()["status"] == "ok"


def test_the_stage_fixture_switches_the_stage(page, stage: str) -> None:
    """`stage1` to `stage4` report `v1` to `v4` on the same server."""
    status = workshop_status(page)

    assert status["locator_stage"] == f"v{stage_number(stage)}"


def test_the_base_url_option_selects_the_target(
    base_url: str, pytestconfig: pytest.Config
) -> None:
    """`--base-url` is the only target selector (design Decision 8)."""
    option = pytestconfig.getoption("--base-url")
    if not option:
        pytest.skip("no --base-url given: the fixture started the shop from source")

    assert base_url == option
