"""Deterministic drift (task 14.6, spec "Deterministic drift").

For a given stage the rendered hooks of a page are identical across requests,
sessions and restarts. Two of those three are checked here:

* **sessions** - the same page, in the same stage, requested with two different
  `x-session-id` values, carries the same ids, the same classes, the same
  `data-test` values and the same tag structure. Nothing about a session may
  leak into a locator.
* **restarts** - a *fresh interpreter* imports the application again, renders
  the same pages against the same temporary database (the `subprocess_env`
  fixture) and produces the same hook sets and the same stylesheet digests. A
  mapping built from a set iteration order, a `hash()` seed or a module-level
  random value would differ here and nowhere else, because a Python process
  randomises `hash()` per interpreter.

"Repeated requests" within one process is what the whole matrix of
`test_stage_contract.py` already relies on - every cell is rendered once and
compared with another cell - so it is not restated as a test of its own; the
session check below covers the repetition explicitly.

* **spaces** - the third dimension, added in task 15.3: a stage applied in
  two different workshop spaces through `POST /api/workshop/preset` renders
  the same hooks in both, and leaves the `default` space on stage 1.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from bs4 import Tag

from backend.app.core.spaces import SPACE_HEADER
from backend.app.core.workshop import STAGES

from .conftest import STAGE_FLAGS
from .hooks import extract_hooks, soup_of

#: The pages the determinism check renders. One layout-heavy page, the listing
#: with its cards, and the checkout with its form.
DETERMINISM_PATHS: tuple[str, ...] = ("/", "/products", "/checkout")

#: The drifted stages. Stage 1 renders no replacement at all, so it cannot show
#: a non-deterministic one.
DRIFT_STAGES: tuple[int, ...] = tuple(stage for stage in STAGES if stage != 1)

#: The repository root, which the fresh interpreter runs in.
REPO_ROOT: Path = Path(__file__).resolve().parents[3]

#: The per-stage stylesheet the page links (design Decision 5).
_STYLESHEET = re.compile(r'href="(/assets/styles\.[0-9a-f]+\.css)"')

#: What the fresh interpreter runs. It imports the application itself - a real
#: restart, not a re-render - overrides the flag seam exactly as the in-process
#: renderer does, and prints one JSON document on stdout.
_FRESH_INTERPRETER = """
import json, sys

from starlette.testclient import TestClient

from backend.app.core.feature_flags import get_effective_flags
from backend.app.main import app

flags = json.loads(sys.argv[1])
paths = json.loads(sys.argv[2])


async def _effective_flags():
    return dict(flags)


app.dependency_overrides[get_effective_flags] = _effective_flags
rendered = {}
with TestClient(app) as client:
    for path in paths:
        response = client.get(path, headers={"x-session-id": "determinism-restart"})
        assert response.status_code == 200, (path, response.status_code)
        rendered[path] = response.text
sys.stdout.write(json.dumps(rendered))
"""


def tag_structure(html: str) -> tuple[tuple[int, str], ...]:
    """The document's tag tree: every element's depth and tag name, in order.

    Depth plus tag name is what a structural locator walks. It changes when a
    wrapper is added or removed and stays put when a name drifts, so comparing
    it between two renders of the *same* stage catches a tree that is not
    reproducible without also reacting to the drift the stage declares.
    """
    structure: list[tuple[int, str]] = []
    for element in soup_of(html).find_all(True):
        depth = 0
        parent = element.parent
        while isinstance(parent, Tag) and parent.name != "[document]":
            depth += 1
            parent = parent.parent
        structure.append((depth, element.name))
    return tuple(structure)


def stylesheet_of(html: str) -> str:
    """The stylesheet variant this render links."""
    found = _STYLESHEET.findall(html)
    assert len(set(found)) == 1, f"expected one stylesheet link, found {found}"
    return found[0]


@pytest.mark.parametrize("path", DETERMINISM_PATHS)
@pytest.mark.parametrize("stage", DRIFT_STAGES)
def test_two_sessions_render_the_same_hooks(render, path: str, stage: int) -> None:
    """Spec scenario "Repeated requests": different sessions, same locators."""
    first = render(path, STAGE_FLAGS[stage], "determinism-session-a").text
    second = render(path, STAGE_FLAGS[stage], "determinism-session-b").text

    assert extract_hooks(first) == extract_hooks(second)
    assert tag_structure(first) == tag_structure(second)
    assert stylesheet_of(first) == stylesheet_of(second)


@pytest.fixture(scope="module")
def fresh_interpreter_renders(subprocess_env) -> dict[int, dict[str, str]]:
    """The pages, rendered once per stage by a freshly started interpreter.

    One subprocess per stage, each importing the application from source and
    talking to the same temporary database and PDF directory as
    `contract_client` (`subprocess_env`), so nothing is written into the
    repository.
    """
    renders: dict[int, dict[str, str]] = {}
    for stage in DRIFT_STAGES:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                _FRESH_INTERPRETER,
                json.dumps(dict(STAGE_FLAGS[stage])),
                json.dumps(list(DETERMINISM_PATHS)),
            ],
            cwd=REPO_ROOT,
            env=subprocess_env,
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert completed.returncode == 0, completed.stderr[-4000:]
        renders[stage] = json.loads(completed.stdout)
    return renders


@pytest.mark.parametrize("path", DETERMINISM_PATHS)
@pytest.mark.parametrize("stage", DRIFT_STAGES)
def test_a_restart_renders_the_same_hooks(
    render, fresh_interpreter_renders, path: str, stage: int
) -> None:
    """A fresh interpreter produces the same hooks and the same stylesheet."""
    in_process = render(path, STAGE_FLAGS[stage], "determinism-restart").text
    restarted = fresh_interpreter_renders[stage][path]

    assert extract_hooks(restarted) == extract_hooks(in_process)
    assert stylesheet_of(restarted) == stylesheet_of(in_process)


def test_the_stages_link_the_variants_the_mapping_implies(render) -> None:
    """Stages 1 and 3 share a stylesheet; stages 2 and 4 have their own.

    Stage 3 renames no class, so its variant is byte for byte stage 1's and
    carries the same digest (design Decision 5). A digest that moved between
    two runs would break this as well.
    """
    digests = {stage: stylesheet_of(render("/", STAGE_FLAGS[stage]).text) for stage in STAGES}

    assert digests[1] == digests[3]
    assert len({digests[1], digests[2], digests[4]}) == 3, digests


# ---------------------------------------------------------------------------
# The space dimension (task 15.3)
# ---------------------------------------------------------------------------

#: The two participant spaces the stage is applied in. Neither is `default`, so
#: the writes below land in `space_feature_flags` and touch no global row.
DETERMINISM_SPACES: tuple[str, str] = ("alice", "bob")

#: The pages compared across spaces: the listing with its cards and the
#: checkout with its form.
SPACE_PATHS: tuple[str, ...] = ("/products", "/checkout")

#: The stage both spaces are put into.
SPACE_STAGE = 2


@pytest.fixture(scope="module")
def stage_two_in_two_spaces(contract_client) -> Iterator[dict[str, dict[str, str]]]:
    """`stage2` applied in both spaces, and the pages each of them renders.

    The preset is written the way a participant writes it - through the public
    control endpoint with an `X-Workshop-Space` header - so this check goes
    through the real flag resolution instead of through the seam override the
    rest of this module uses. Each space is restored to `clean` afterwards;
    `POST /api/workshop/reset` is never used here, because it would empty the
    carts the package matrix filled.
    """
    rendered: dict[str, dict[str, str]] = {}
    try:
        for space in DETERMINISM_SPACES:
            applied = contract_client.post(
                "/api/workshop/preset",
                json={"preset": f"stage{SPACE_STAGE}"},
                headers={SPACE_HEADER: space},
            )
            assert applied.status_code == 200, applied.text
            assert applied.json()["current_status"]["locator_stage"] == f"v{SPACE_STAGE}"

            pages: dict[str, str] = {}
            for path in SPACE_PATHS:
                response = contract_client.get(
                    path,
                    headers={SPACE_HEADER: space, "x-session-id": f"determinism-{space}"},
                )
                assert response.status_code == 200, response.text
                pages[path] = response.text
            rendered[space] = pages
        yield rendered
    finally:
        for space in DETERMINISM_SPACES:
            contract_client.post(
                "/api/workshop/preset",
                json={"preset": "clean"},
                headers={SPACE_HEADER: space},
            )


@pytest.mark.parametrize("path", SPACE_PATHS)
def test_two_spaces_render_the_same_hooks(stage_two_in_two_spaces, path: str) -> None:
    """Spec "Deterministic drift": the same stage, two spaces, same locators."""
    alice, bob = (stage_two_in_two_spaces[space][path] for space in DETERMINISM_SPACES)

    assert extract_hooks(alice) == extract_hooks(bob)
    assert tag_structure(alice) == tag_structure(bob)
    assert stylesheet_of(alice) == stylesheet_of(bob)


@pytest.mark.parametrize("path", SPACE_PATHS)
def test_a_space_renders_the_stage_it_applied(
    stage_two_in_two_spaces, render, path: str
) -> None:
    """A guard: an ignored space header would make the check above vacuous.

    The indicator of `workshop-spaces` is rendered in a participant space and
    not in `default`, so only the hooks the mapping owns are compared here.
    """
    expected = extract_hooks(render(path, STAGE_FLAGS[SPACE_STAGE])).covered_classes

    for space in DETERMINISM_SPACES:
        found = extract_hooks(stage_two_in_two_spaces[space][path]).covered_classes
        assert found == expected, space


@pytest.mark.parametrize("path", SPACE_PATHS)
def test_the_default_space_still_renders_stage_one(
    stage_two_in_two_spaces, contract_client, render, path: str
) -> None:
    """Nothing the two spaces wrote reaches the global flag rows."""
    status = contract_client.get("/api/workshop/status")
    assert status.status_code == 200, status.text
    assert status.json()["locator_stage"] == "v1"

    response = contract_client.get(
        path, headers={"x-session-id": "determinism-default"}
    )
    assert response.status_code == 200, response.text

    assert extract_hooks(response.text) == extract_hooks(render(path, STAGE_FLAGS[1]))
