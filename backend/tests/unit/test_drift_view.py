"""The request seam, the drift view and the Jinja globals (tasks 2.1, 2.4, 2.6).

Three things are checked here:

* ``get_effective_flags`` is the one seam a route reads flags through, so a test
  can hand a route any flag set through ``app.dependency_overrides`` (task 2.1);
* :class:`DriftView` resolves hooks for exactly one stage (task 2.4);
* the ``workshop_view`` dependency publishes that view for the request only, and
  the ``drift`` and ``bugs`` globals raise outside a request (tasks 2.6, 3.1).
"""
from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi import Depends, FastAPI
from starlette.requests import Request
from starlette.testclient import TestClient

from backend.app.core.feature_flags import get_effective_flags
from backend.app.core.workshop import (
    STAGES,
    BugView,
    DriftView,
    UnknownHook,
    WorkshopView,
    _current_view,
    current_workshop_view,
    workshop_view,
)

#: A page that renders product cards, so the inline drift of the current
#: templates is visible in the response body.
DRIFTING_PAGE = "/products"


@contextmanager
def overridden_flags(flags: dict[str, bool]) -> Iterator[None]:
    """Make every route of the real app see ``flags`` (design Decision 7)."""
    from backend.app.main import app

    app.dependency_overrides[get_effective_flags] = lambda: dict(flags)
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_effective_flags, None)


def rendered_view(response) -> WorkshopView:
    """The workshop view the page route built for ``response``."""
    return response.context["request"].state.workshop_view


def make_request(path: str = "/") -> Request:
    """A bare ``Request``, enough for the dependency's ``request.state``."""
    return Request({"type": "http", "method": "GET", "path": path, "headers": [], "state": {}})


def jinja_env():
    """The application's Jinja environment, with the globals registered."""
    from backend.app.main import app

    return app.state.templates.env


# ---------------------------------------------------------------------------
# Task 2.1 - the one flag seam
# ---------------------------------------------------------------------------


def test_a_route_sees_the_flags_supplied_through_the_seam() -> None:
    """``app.dependency_overrides[get_effective_flags]`` decides the flags.

    This is how the contract tests set a stage without touching the database,
    and it is the reason nothing outside ``core/feature_flags.py`` queries the
    flag tables.
    """
    app = FastAPI()

    @app.get("/flags")
    async def read_flags(flags: dict = Depends(get_effective_flags)) -> dict:
        return flags

    app.dependency_overrides[get_effective_flags] = lambda: {"LOCATOR_V3": True}
    with TestClient(app) as client:
        assert client.get("/flags").json() == {"LOCATOR_V3": True}


# ---------------------------------------------------------------------------
# Task 2.4 - the drift view of one stage
# ---------------------------------------------------------------------------


class TestDriftView:
    """One stage, resolved through the mapping and nothing else."""

    def test_a_block_rename_carries_its_elements_and_modifiers(self):
        """One table row renames ``block``, ``block__*`` and ``block--*``."""
        assert DriftView(2).cls("product-card__media") == "item-card__media"
        assert DriftView(2).cls("product-card--compact") == "item-card--compact"
        assert DriftView(4).cls("product-card__footer") == "product-tile__footer"
        assert DriftView(4).cls("product-card--mini") == "product-tile--mini"

    def test_an_exact_override_wins_over_the_block_rule(self):
        """``product-card__title`` is ``item-title``, not ``item-card__title``."""
        assert DriftView(2).cls("product-card__title") == "item-title"
        assert DriftView(2).cls("product-card__add") == "btn-main"

    def test_several_tokens_are_resolved_one_by_one(self):
        assert DriftView(2).cls("product-card product-card__title") == "item-card item-title"

    def test_a_stage_without_a_rename_answers_the_stage_one_name(self):
        """Stage 3 keeps every class, which is what makes it a different lesson."""
        assert DriftView(3).cls("product-card__title") == "product-card__title"

    @pytest.mark.parametrize("stage", STAGES)
    def test_an_unknown_key_raises(self, stage):
        drift = DriftView(stage)
        with pytest.raises(UnknownHook):
            drift.cls("not-a-covered-class")
        with pytest.raises(UnknownHook):
            drift.id("not-a-covered-id")
        with pytest.raises(UnknownHook):
            drift.test("not-a-covered-hook")
        with pytest.raises(UnknownHook):
            drift.layout("not-a-component")

    @pytest.mark.parametrize("stage", [3, 4])
    def test_test_renders_nothing_in_stages_three_and_four(self, stage):
        assert DriftView(stage).test("add-to-cart-btn") == ""

    def test_only_stage_four_restructures_a_component(self):
        assert DriftView(4).layout("product-card") == "wrapped"
        for stage in (1, 2, 3):
            assert DriftView(stage).layout("product-card") == ""

    def test_every_declared_component_has_a_stage_four_variant(self):
        """Group 5 filled the table: the three components of Decision 3."""
        assert DriftView(4).layout("product-hero-actions") == "wrapped"
        assert DriftView(4).layout("checkout-field") == "grouped"
        for stage in (1, 2, 3):
            assert DriftView(stage).layout("checkout-field") == ""

    def test_two_instances_of_a_stage_render_the_same(self):
        """The view is derived from the tables, so it carries no state."""
        for stage in STAGES:
            first, second = DriftView(stage), DriftView(stage)
            assert first == second
            assert first.cls("product-card product-card__title") == second.cls(
                "product-card product-card__title"
            )
            assert first.test("product-card") == second.test("product-card")
            assert first.layout("product-card") == second.layout("product-card")
            assert first.stylesheet_href == second.stylesheet_href

    def test_the_stylesheet_href_is_a_usable_link(self):
        """A placeholder until group 6 serves one variant per stage."""
        assert DriftView(1).stylesheet_href.startswith("/")

    def test_an_unknown_stage_is_refused(self):
        with pytest.raises(ValueError):
            DriftView(5)


# ---------------------------------------------------------------------------
# Tasks 2.6 and 3.1 - the request-scoped globals
# ---------------------------------------------------------------------------


def test_the_drift_global_raises_outside_a_request() -> None:
    """HTML that needs ``drift`` can only be rendered from a page route."""
    template = jinja_env().from_string("{{ drift.cls('product-card') }}")

    with pytest.raises(RuntimeError, match="workshop view"):
        template.render()


def test_the_bugs_global_raises_outside_a_request() -> None:
    """Same for ``bugs``: a global exception handler must not render cards."""
    template = jinja_env().from_string("{{ bugs.card_href(product) }}")

    with pytest.raises(RuntimeError, match="workshop view"):
        template.render(product={"id": 4, "price": 10.0})


def test_the_globals_render_while_a_view_is_active() -> None:
    """The proxies forward to the view of the current request."""
    template = jinja_env().from_string(
        "{{ drift.cls('product-card') }}|{{ drift.test('product-card') }}"
        "|{{ bugs.card_href(product) }}"
    )
    view = WorkshopView.from_flags({"LOCATOR_V2": True, "BUG_BROKEN_LINKS": True})

    token = _current_view.set(view)
    try:
        rendered = template.render(product={"id": 4, "price": 10.0})
    finally:
        _current_view.reset(token)

    assert rendered == 'item-card|data-test="product-card"|/products/invalid-4'


def test_the_dependency_publishes_the_view_and_takes_it_back() -> None:
    """The ``ContextVar`` is set for the request and reset afterwards."""

    async def exercise() -> None:
        request = make_request(DRIFTING_PAGE)
        assert _current_view.get() is None

        dependency = workshop_view(request, {"LOCATOR_V4": True, "BUG_WRONG_PRICE": True})
        view = await dependency.__anext__()

        assert _current_view.get() is view
        assert current_workshop_view() is view
        assert request.state.workshop_view is view
        assert view.stage == 4
        assert view.drift == DriftView(4)
        assert view.bugs == BugView.from_flags({"BUG_WRONG_PRICE": True})

        with pytest.raises(StopAsyncIteration):
            await dependency.__anext__()

        assert _current_view.get() is None
        with pytest.raises(RuntimeError):
            current_workshop_view()

    asyncio.run(exercise())


def test_consecutive_requests_each_render_their_own_stage(app_client) -> None:
    """Two requests in a row, two different stages, no leak between them."""
    with overridden_flags({"LOCATOR_V2": True}):
        stage_two = app_client.get(DRIFTING_PAGE)
    with overridden_flags({"LOCATOR_V4": True}):
        stage_four = app_client.get(DRIFTING_PAGE)
    with overridden_flags({}):
        stage_one = app_client.get(DRIFTING_PAGE)

    assert [response.status_code for response in (stage_one, stage_two, stage_four)] == [200] * 3
    assert rendered_view(stage_two).stage == 2
    assert rendered_view(stage_four).stage == 4
    assert rendered_view(stage_one).stage == 1
    assert rendered_view(stage_two).drift.cls("product-card") == "item-card"
    assert rendered_view(stage_four).drift.cls("product-card") == "product-tile"


def test_the_view_is_gone_once_the_response_is_rendered(app_client) -> None:
    """Nothing keeps the view alive between requests, in either thread."""
    with overridden_flags({"LOCATOR_V2": True}):
        app_client.get(DRIFTING_PAGE)

    assert _current_view.get() is None
    assert app_client.portal.call(_current_view.get) is None


def test_the_templates_drift_through_the_view_and_not_through_the_flags(app_client) -> None:
    """Group 5 converted the templates, so the stage reaches them as a view.

    Stage 2 still shows up as ``item-card`` in the markup, but the page context
    no longer carries the workshop flags (task 5.10): a template that cannot
    read them cannot leak them.
    """
    with overridden_flags({"LOCATOR_V2": True}):
        response = app_client.get(DRIFTING_PAGE)

    assert "item-card" in response.text
    assert set(response.context["feature_flags"]) == {"NEW_CART_UI", "MOBILE_UI_V1"}
