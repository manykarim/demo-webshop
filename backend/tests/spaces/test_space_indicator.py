"""The active space is visible in the layout (task 9.2, design D8).

The indicator lives in ``base.html``, so it is on every page of the shop and no
route passes it: the space comes from ``request.state`` and ``settings`` is a
Jinja global. It is deliberately outside drift - no helper and no flag produce
it - which the byte-identical checks below pin down, because ``drift-coverage``
carries exactly this markup and its two CSS rules into every stage variant.
"""
from __future__ import annotations

import re

import pytest

from backend.app.core.spaces import SPACE_HEADER

#: The participant space used throughout this module.
OCTOCAT = "octocat"

#: The six pages of the shop, of which five take no path parameter.
PAGES = ["/", "/products", "/products/1", "/cart", "/checkout"]

#: The presets whose stage or bugs must leave the indicator untouched.
PRESETS = ["stage1", "stage2", "stage3", "stage4", "buggy"]

#: The indicator element and its hint sibling, as rendered.
INDICATOR = re.compile(r'<p class="workshop-space"[^>]*>.*?</p>', re.DOTALL)
HINT = re.compile(r'<p class="workshop-space-hint"[^>]*>.*?</p>', re.DOTALL)

#: The stylesheet the layout links, so the check follows a moved file.
STYLESHEET = re.compile(r'<link[^>]*rel="stylesheet"[^>]*href="([^"]+)"')

#: Each selector as a whole token: ``.workshop-space`` followed by ``{``, ``,``
#: or whitespace, so ``.workshop-space-hint`` never satisfies the first check.
INDICATOR_RULE = re.compile(r"\.workshop-space(?=[\s{,])")
HINT_RULE = re.compile(r"\.workshop-space-hint(?=[\s{,])")


def space_headers(space: str | None) -> dict[str, str]:
    """Headers that put a request into ``space`` (none for ``default``)."""
    return {SPACE_HEADER: space} if space else {}


def bearer(token: str) -> dict[str, str]:
    """The facilitator's ``Authorization`` header."""
    return {"Authorization": f"Bearer {token}"}


def page(client, path: str = "/", space: str | None = None) -> str:
    """The HTML of ``path``, rendered in ``space``."""
    response = client.get(path, headers=space_headers(space))
    assert response.status_code == 200, response.text
    return response.text


def indicator_of(html: str) -> str | None:
    """The rendered indicator element of ``html``, or ``None``."""
    match = INDICATOR.search(html)
    return match.group(0) if match else None


def hint_of(html: str) -> str | None:
    """The rendered hint element of ``html``, or ``None``."""
    match = HINT.search(html)
    return match.group(0) if match else None


def apply_preset(client, preset: str, space: str | None = None, token: str | None = None) -> None:
    """``POST /api/workshop/preset`` in ``space``, asserting it was applied."""
    headers = space_headers(space)
    if token:
        headers.update(bearer(token))
    response = client.post("/api/workshop/preset", json={"preset": preset}, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "success", response.text


# ---------------------------------------------------------------------------
# What each space sees
# ---------------------------------------------------------------------------


def test_a_participant_sees_the_active_space(app_client) -> None:
    """*Participant checks their space*: the id is in the markup and in the text."""
    html = page(app_client, "/", OCTOCAT)

    assert f'data-workshop-space="{OCTOCAT}"' in html
    assert f"Space: {OCTOCAT}" in html
    assert "workshop-space-hint" not in html


def test_the_default_space_shows_nothing_in_local_mode(app_client) -> None:
    """*Default space in local mode*: the page renders, without any indicator."""
    response = app_client.get("/")

    assert response.status_code == 200, response.text
    assert "data-workshop-space" not in response.text
    assert "workshop-space-hint" not in response.text


def test_the_shared_instance_names_the_default_space(app_client, shared_mode) -> None:
    """*Default space on the shared instance*: indicator plus the way out."""
    html = page(app_client)

    assert 'data-workshop-space="default"' in html
    assert "Space: default" in html
    hint = hint_of(html)
    assert hint is not None, html
    assert "?space=" in hint
    assert "X-Workshop-Space" in hint


def test_a_participant_space_needs_no_hint_in_shared_mode(app_client, shared_mode) -> None:
    """The hint is only about the shared baseline, not about a personal space."""
    html = page(app_client, "/", OCTOCAT)

    assert f'data-workshop-space="{OCTOCAT}"' in html
    assert "workshop-space-hint" not in html


@pytest.mark.parametrize("path", PAGES)
def test_every_page_carries_the_indicator(app_client, path: str) -> None:
    """The indicator is in the layout, so no page can be missing it."""
    html = page(app_client, path, OCTOCAT)

    assert indicator_of(html) == (
        f'<p class="workshop-space" data-workshop-space="{OCTOCAT}">Space: {OCTOCAT}</p>'
    )


# ---------------------------------------------------------------------------
# Outside drift: the markup never changes with a stage or a bug
# ---------------------------------------------------------------------------


def test_the_indicator_is_identical_in_every_stage(app_client) -> None:
    """No locator stage and no bug flag touches the indicator of a space."""
    rendered = {}
    for preset in PRESETS:
        apply_preset(app_client, preset, space=OCTOCAT)
        rendered[preset] = indicator_of(page(app_client, "/", OCTOCAT))

    assert None not in rendered.values(), rendered
    assert len(set(rendered.values())) == 1, rendered


def test_the_shared_default_indicator_is_identical_in_every_stage(
    app_client, shared_mode
) -> None:
    """The shared-instance indicator and its hint are stage-independent too."""
    rendered = {}
    for preset in PRESETS:
        apply_preset(app_client, preset, token=shared_mode)
        html = page(app_client)
        rendered[preset] = (indicator_of(html), hint_of(html))

    assert all(all(part for part in pair) for pair in rendered.values()), rendered
    assert len(set(rendered.values())) == 1, rendered


# ---------------------------------------------------------------------------
# Switching space in a browser
# ---------------------------------------------------------------------------


def test_a_url_switch_shows_and_keeps_the_new_space(app_client) -> None:
    """*Human switches space via URL*: the indicator follows the cookie."""
    switched = app_client.get(f"/?space={OCTOCAT}")
    assert switched.status_code == 200, switched.text
    assert f'data-workshop-space="{OCTOCAT}"' in switched.text

    kept = app_client.get("/products")
    assert kept.status_code == 200, kept.text
    assert f'data-workshop-space="{OCTOCAT}"' in kept.text

    back = app_client.get("/?space=default")
    assert back.status_code == 200, back.text
    assert "data-workshop-space" not in back.text


# ---------------------------------------------------------------------------
# The stylesheet the layout links
# ---------------------------------------------------------------------------


def test_the_stylesheet_styles_both_elements(app_client) -> None:
    """Both rules exist in whatever stylesheet the page links right now."""
    href = STYLESHEET.search(page(app_client)).group(1)

    response = app_client.get(href)

    assert response.status_code == 200, href
    css = response.text
    assert INDICATOR_RULE.search(css), f"no .workshop-space rule in {href}"
    assert HINT_RULE.search(css), f"no .workshop-space-hint rule in {href}"
