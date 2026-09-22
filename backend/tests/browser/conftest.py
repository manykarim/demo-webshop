"""The browser smoke harness (drift-coverage Decision 8, task 7.2).

The suite is a drift-proof reference suite: it finds everything by role, label
and text, and it is the only suite in this repository that needs a browser and a
running shop. It therefore carries the marker ``browser`` and is deselected by
``addopts`` in ``pyproject.toml``; ``uv run pytest -m browser`` asks for it.

**Where it points.** The only target selector is pytest-base-url's
``--base-url`` option, whose default that plugin itself fills from its own
environment variable. Nothing else in this repository points a suite at a
server: ``base_url`` is not set in the ini file, and this file reads no
environment variable of its own - a project-specific one would be a second,
undocumented way to aim the suite at a server.

* With ``--base-url`` the session-scoped ``base_url`` fixture below returns that
  value unchanged, and every test runs against that server - the candidate image
  in CI, for example.
* Without it, the fixture seeds a temporary database in a subprocess
  (``python -m tools.seed_db``), starts uvicorn from source on a free port with
  ``WORKSHOP_DATABASE_URL`` and ``WORKSHOP_PDF_OUTPUT_DIR`` passed explicitly in
  that subprocess environment, waits for ``/health`` and stops the server when
  the session ends. Nothing is ever written inside the repository.

**Which workshop space it browses in** (task 15.5). Every browser context of
this suite carries an ``X-Workshop-Space`` header, and the space is derived from
the stage the test is parametrized with: ``stage2`` browses in ``drift-stage2``.
So the presets of one parametrization never reach another one, the ``default``
space keeps the state the server started with, and the writes stay allowed on a
shared instance, where ``workshop-spaces`` guards only ``default``. The space is
resolved from the test's own parameters rather than from the ``stage`` fixture,
so the two tests that use ``page`` without a stage still get a space of their
own (``drift-probe``) instead of being parametrized four times.

The application is never imported here - not at collection time and not in a
fixture body - because the shop runs in its own process. No fixture of this file
uses a canonical harness name (``temp_database``, ``app_client``,
``seeded_app_client``, ``pdf_unavailable``, ``fake_weasyprint``).
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

#: The repository root: ``backend/tests/browser/conftest.py`` -> four levels up.
REPO_ROOT = Path(__file__).resolve().parents[3]

#: The stage presets every smoke flow is parametrized over.
STAGE_PRESETS: tuple[str, ...] = ("stage1", "stage2", "stage3", "stage4")

#: The preset the stage fixture leaves behind.
TEARDOWN_PRESET = "clean"

#: How long a server started from source gets to answer ``/health``.
STARTUP_TIMEOUT_SECONDS = 90.0

#: The request header that puts a request into a workshop space.
SPACE_HEADER = "X-Workshop-Space"

#: The space the server serves when no header, query parameter or cookie names
#: one. This suite never browses in it.
DEFAULT_SPACE = "default"

#: Prefix of every space this suite browses in. With the stage appended the
#: result is a valid space identifier (``workshop-spaces`` design D2: lower-case
#: letters, digits and single hyphens).
SPACE_PREFIX = "drift-"

#: The space of a test that is not parametrized over the stages: the two
#: negative checks of task 9.5, which apply ``stage1`` themselves.
PROBE_SPACE = f"{SPACE_PREFIX}probe"


def stage_number(preset: str) -> int:
    """``"stage3"`` -> ``3``."""
    return int(preset.removeprefix("stage"))


def space_of(preset: str) -> str:
    """``"stage3"`` -> ``"drift-stage3"``: the space that stage browses in."""
    return f"{SPACE_PREFIX}{preset}"


def apply_preset(page, preset: str) -> None:
    """Apply a workshop preset from the page's own browser context.

    ``page.request`` carries the context's headers and cookies, so the preset
    lands in the space that context browses in - which is what keeps the
    cross-stage comparisons of task 7.4 inside one space.
    """
    response = page.request.post("/api/workshop/preset", data={"preset": preset})
    assert response.ok, f"{preset}: {response.status} {response.text()}"
    body = response.json()
    assert body["status"] == "success", body


def workshop_status(page) -> dict:
    """The workshop status as the page's own context sees it."""
    response = page.request.get("/api/workshop/status")
    assert response.ok, response.text()
    return response.json()


def _free_port() -> int:
    """A port that is free right now, for the server started from source."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_for_health(url: str, process: subprocess.Popen) -> None:
    """Block until ``/health`` answers ``ok``, or fail with what happened."""
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"the shop exited with code {process.returncode}")
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=2) as response:
                payload = json.loads(response.read().decode())
            if payload.get("status") == "ok":
                return
        except (urllib.error.URLError, OSError, ValueError) as error:  # not up yet
            last_error = error
        time.sleep(0.2)
    raise RuntimeError(f"{url}/health did not answer in time: {last_error}")


@pytest.fixture(scope="session")
def base_url(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """The shop the browser suite talks to (design Decision 8).

    Overrides pytest-base-url's fixture of the same name for this directory
    only, so pytest-playwright's browser context is built with this base URL and
    the tests can navigate with relative paths.
    """
    option = request.config.getoption("--base-url")
    if option:
        yield option
        return

    storage = tmp_path_factory.mktemp("browser")
    database = storage / "workshop.db"
    documents = storage / "documents"
    documents.mkdir()

    environment = dict(os.environ)
    environment["WORKSHOP_DATABASE_URL"] = f"sqlite+aiosqlite:///{database}"
    environment["WORKSHOP_PDF_OUTPUT_DIR"] = str(documents)

    seeded = subprocess.run(
        [sys.executable, "-m", "tools.seed_db"],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert seeded.returncode == 0, f"seeding failed:\n{seeded.stdout}\n{seeded.stderr}"

    port = _free_port()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=REPO_ROOT,
        env=environment,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        _wait_for_health(url, process)
        yield url
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:  # pragma: no cover - a stuck worker
            process.kill()
            process.wait(timeout=15)


@pytest.fixture
def workshop_space(request: pytest.FixtureRequest) -> str:
    """The workshop space this test browses in (task 15.5).

    Read from the test's own parameters instead of from the ``stage`` fixture,
    because the browser context is built before any fixture the test body uses:
    asking ``stage`` here would be a cycle, and parametrizing this fixture would
    parametrize every test that only needs a ``page``.
    """
    callspec = getattr(request.node, "callspec", None)
    preset = getattr(callspec, "params", {}).get("stage") if callspec else None
    return space_of(preset) if preset else PROBE_SPACE


@pytest.fixture
def browser_context_args(browser_context_args: dict, workshop_space: str) -> dict:
    """pytest-playwright's context arguments, with the space header added.

    ``extra_http_headers`` is carried by every navigation of the page *and* by
    ``page.request``, so the preset calls, the API calls and the server-rendered
    HTML the live-DOM check re-fetches all happen in the same space.
    """
    return {
        **browser_context_args,
        "extra_http_headers": {
            **(browser_context_args.get("extra_http_headers") or {}),
            SPACE_HEADER: workshop_space,
        },
    }


@pytest.fixture(params=STAGE_PRESETS)
def stage(request: pytest.FixtureRequest, page) -> Iterator[str]:
    """One locator stage, applied through the workshop preset endpoint.

    Applied from the page's own context - and therefore inside that context's
    own space (task 15.5) - and followed by ``clean``, which is the only preset
    that also clears the planted bugs and the AI flags, so a failing flow cannot
    leave a stage behind for the next test.
    """
    preset: str = request.param
    apply_preset(page, preset)
    try:
        yield preset
    finally:
        apply_preset(page, TEARDOWN_PRESET)
