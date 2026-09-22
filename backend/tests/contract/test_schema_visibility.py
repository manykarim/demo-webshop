"""The control endpoints are hidden, not removed (drift-coverage task 12.1).

The spec's "Workshop controls not advertised" requirement: nothing under
`/api/workshop/` or `/api/admin/` may appear in the published schema or the
interactive documentation, and everything there must keep working. The shop's
own API stays listed, because agents legitimately explore it.

Task 15.4 adds the space reset of `workshop-spaces` to both halves: it is a
control endpoint, so it is hidden, and it has to stay callable like the rest.
The second half is checked from the routing table rather than from the schema -
`app.routes` still carries every hidden route - which is also how the
no-enumeration test of `backend/tests/spaces/test_shared_mode.py` finds the
control endpoints it calls.
"""
from __future__ import annotations

import pytest

from backend.app.core.spaces import SPACE_HEADER

#: Control paths that must stay reachable although the schema hides them.
REQUIRED_GET_PATHS: tuple[str, ...] = (
    "/api/workshop/status",
    "/api/workshop/presets",
    "/api/admin/flags",
    "/search/results",
)

#: The space `POST /api/workshop/reset` is exercised in. Never `default`: a
#: reset there would empty the carts the package matrix filled, and this space
#: owns nothing else, so the call is free of side effects for the rest of the
#: package.
RESET_PROBE_SPACE = "reset-probe"


def api_routes(router, prefix: str = ""):
    """Every ``APIRoute`` reachable from ``router``, with its full path.

    FastAPI does not flatten an included router into ``app.routes`` - it appends
    one router entry per ``include_router`` call - so the hidden control routers
    are found by descending into those entries and prepending the prefix they
    were included under. A ``Mount`` such as `/assets` carries no ``routes`` and
    is skipped.
    """
    from fastapi.routing import APIRoute

    for route in getattr(router, "routes", []):
        if isinstance(route, APIRoute):
            yield prefix + route.path, route
            continue
        nested = getattr(route, "original_router", None) or getattr(route, "app", None)
        if nested is None or not hasattr(nested, "routes"):
            continue
        context = getattr(route, "include_context", None)
        nested_prefix = getattr(context, "prefix", None) or getattr(route, "path", "") or ""
        yield from api_routes(nested, prefix + nested_prefix)


def parameterless_get_paths() -> set[str]:
    """The GET paths of the routing table that take no path parameter."""
    from backend.app.main import app

    return {
        path
        for path, route in api_routes(app)
        if "GET" in (route.methods or set()) and "{" not in path
    }

#: Prefixes that must not appear in the published schema: the workshop and admin
#: controls, the search-results fragment and the per-stage stylesheet mount.
HIDDEN_PREFIXES: tuple[str, ...] = ("/api/workshop/", "/api/admin/", "/search/results", "/assets/")


@pytest.fixture(scope="module")
def openapi(contract_client) -> dict:
    response = contract_client.get("/openapi.json")
    assert response.status_code == 200
    return response.json()


def test_the_shop_api_is_still_published(openapi: dict) -> None:
    """A guard: an empty schema would make the exclusions below vacuous."""
    assert "/api/products/" in openapi["paths"]


@pytest.mark.parametrize("prefix", HIDDEN_PREFIXES)
def test_no_control_path_is_published(openapi: dict, prefix: str) -> None:
    listed = sorted(path for path in openapi["paths"] if path.startswith(prefix))

    assert listed == []


def test_the_interactive_documentation_still_loads(contract_client) -> None:
    assert contract_client.get("/docs").status_code == 200


def test_a_facilitator_can_still_apply_a_preset(contract_client) -> None:
    """The spec scenario "Facilitator applies a preset"."""
    applied = contract_client.post("/api/workshop/preset", json={"preset": "stage2"})
    assert applied.status_code == 200
    assert applied.json()["status"] == "success"

    status = contract_client.get("/api/workshop/status")
    assert status.status_code == 200
    assert status.json()["locator_stage"] == "v2"

    # Leave the shared package client on stage 1 again, so no later test in the
    # package inherits a stage from this one.
    reset = contract_client.post("/api/workshop/preset", json={"preset": "stage1"})
    assert reset.status_code == 200
    assert contract_client.get("/api/workshop/status").json()["locator_stage"] == "v1"


def test_the_flag_administration_is_still_callable(contract_client) -> None:
    response = contract_client.get("/api/admin/flags")

    assert response.status_code == 200
    assert "LOCATOR_V2" in response.json()


def test_the_space_reset_is_not_published(openapi: dict) -> None:
    """`workshop-spaces`' reset is a control endpoint like the others."""
    assert "/api/workshop/reset" not in openapi["paths"]


def test_the_space_reset_is_still_callable(contract_client) -> None:
    """It answers in a space of its own, which owns nothing to remove."""
    response = contract_client.post(
        "/api/workshop/reset", headers={SPACE_HEADER: RESET_PROBE_SPACE}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["space"] == RESET_PROBE_SPACE
    assert body["locator_stage"] == "v1"
    assert (body["removed_cart_items"], body["removed_orders"]) == (0, 0)


def test_the_hidden_control_routes_are_still_in_the_routing_table() -> None:
    """The schema hides them; `app.routes` still has every one of them."""
    paths = parameterless_get_paths()

    assert set(REQUIRED_GET_PATHS) <= paths, sorted(set(REQUIRED_GET_PATHS) - paths)


def test_the_search_fragment_is_hidden_but_answers(contract_client) -> None:
    """`/search/results` is the fragment `app.js` inserts (Decision 6)."""
    response = contract_client.get("/search/results?query=desk")

    assert response.status_code == 200, response.text
