"""The space indicator is part of the stable contract (task 15.2).

``workshop-spaces`` renders the active space in the site header, and on a
shared instance it adds a hint next to it. Both are produced outside the drift
mapping - no ``drift`` helper, no covered class, no flag - so a locator built on
``[data-workshop-space]`` or on the hint's text keeps working in every stage.

That is what this module pins down from the contract side:

* the indicator element rendered with ``X-Workshop-Space: alice`` is *identical*
  in stages 1, 2 and 4 on every covered page, attributes and text included;
* the shared-mode hint, rendered with ``shared_mode`` and ``admin_token``
  switched on and no space at all, is identical in the same three stages;
* the documented stable contract names both hooks, so
  ``docs/WORKSHOP-FEATURES.md`` cannot drift away from the markup.

Stage 3 renames nothing at all, so stages 1, 2 and 4 are the three distinct
class mappings and the three distinct stylesheets - checking those three is
checking every mapping the shop has.

The renders go through the package ``render`` fixture, which overrides the flag
seam for the duration of one request. The space therefore comes purely from the
header, which the application-level dependency resolves; the stage comes purely
from the override. Neither writes anything, so no other contract test is
affected.
"""
from __future__ import annotations

import re

import pytest
from pydantic import SecretStr

from backend.app.core.spaces import SPACE_HEADER

from .hooks import soup_of
from .test_docs_sync import DOC_PATH

#: The participant space every indicator render below is made in.
SPACE = "alice"

#: The stages compared. Stage 3 renames nothing, so these three are the three
#: distinct class mappings of the shop.
CONTRACT_STAGES: tuple[int, ...] = (1, 2, 4)

#: The effective flags that select those stages, spelled out here so this module
#: does not depend on a helper of the matrix conftest.
STAGE_FLAGS_BY_STAGE = {1: {}, 2: {"LOCATOR_V2": True}, 4: {"LOCATOR_V4": True}}

#: The pages the indicator has to be identical on: the layout-heavy home page,
#: the listing, a detail page, the cart and the checkout.
PAGES: tuple[str, ...] = ("/", "/products", "/products/3", "/cart", "/checkout")

#: The indicator and its hint sibling, as rendered by ``base.html``.
INDICATOR = re.compile(r'<p class="workshop-space"[^>]*>.*?</p>', re.DOTALL)
HINT = re.compile(r'<p class="workshop-space-hint"[^>]*>.*?</p>', re.DOTALL)

#: The visible text of each element, with the entities of the template resolved.
INDICATOR_TEXT = f"Space: {SPACE}"
HINT_TEXT = (
    "Shared baseline. Use your own space: add ?space=<github-handle> to the URL "
    "or send the header X-Workshop-Space."
)

#: A facilitator token, only so that shared mode is configured as it is in
#: production; no request below sends it.
FACILITATOR_TOKEN = "contract-facilitator-token"


def element(pattern: re.Pattern[str], html: str, what: str) -> str:
    """The one element ``pattern`` matches, or a readable failure."""
    found = pattern.findall(html)
    assert len(found) == 1, f"expected one {what}, found {len(found)}"
    return found[0]


def text_of(markup: str) -> str:
    """The visible text of a rendered element, whitespace-normalised."""
    return " ".join(soup_of(markup).get_text().split())


@pytest.fixture
def shared_mode(monkeypatch: pytest.MonkeyPatch) -> str:
    """Run the shop as a shared instance for the duration of one test."""
    from backend.app.core.config import settings

    monkeypatch.setattr(settings, "shared_mode", True)
    monkeypatch.setattr(settings, "admin_token", SecretStr(FACILITATOR_TOKEN))
    return FACILITATOR_TOKEN


@pytest.mark.parametrize("path", PAGES)
def test_the_space_indicator_is_identical_in_every_stage(render, path: str) -> None:
    """``[data-workshop-space]`` does not drift, on any covered page."""
    rendered = {
        stage: element(
            INDICATOR,
            render(
                path,
                STAGE_FLAGS_BY_STAGE[stage],
                f"space-indicator-{stage}",
                extra_headers={SPACE_HEADER: SPACE},
            ).text,
            "space indicator",
        )
        for stage in CONTRACT_STAGES
    }

    assert len(set(rendered.values())) == 1, rendered
    only = rendered[CONTRACT_STAGES[0]]
    assert f'data-workshop-space="{SPACE}"' in only
    assert text_of(only) == INDICATOR_TEXT


@pytest.mark.parametrize("path", PAGES)
def test_the_shared_mode_hint_is_identical_in_every_stage(
    render, shared_mode: str, path: str
) -> None:
    """The hint of the `default` space does not drift either."""
    rendered = {
        stage: element(
            HINT,
            render(path, STAGE_FLAGS_BY_STAGE[stage], f"space-hint-{stage}").text,
            "shared-mode hint",
        )
        for stage in CONTRACT_STAGES
    }

    assert len(set(rendered.values())) == 1, rendered
    assert text_of(rendered[CONTRACT_STAGES[0]]) == HINT_TEXT


def test_without_shared_mode_the_default_space_shows_neither(render) -> None:
    """A guard: the hint test above would be vacuous on a local instance."""
    html = render("/", STAGE_FLAGS_BY_STAGE[2], "space-local").text

    assert INDICATOR.search(html) is None
    assert HINT.search(html) is None


def test_the_stable_contract_documents_both_hooks() -> None:
    """Both hooks are named in the `## Stable contract` section (task 15.2)."""
    lines = DOC_PATH.read_text(encoding="utf-8").splitlines()
    start = lines.index("## Stable contract")
    end = next(
        index
        for index, line in enumerate(lines[start + 1 :], start=start + 1)
        if line.startswith("## ")
    )
    section = "\n".join(lines[start:end])

    assert "data-workshop-space" in section
    assert "workshop-space-hint" in section
    assert "Space: <space>" in section
    assert "Shared baseline." in section
