"""The per-stage stylesheet mount (task 6.2, design Decision 5).

Task 15.6 re-runs a repository-wide grep for `static/styles.css` and expects to
find it in exactly one assertion: the one that pins the old URL as gone. That
assertion lives here, together with the rest of what task 6.2 asks of the mount:

* the `href` each stage links answers 200, as `text/css` and cacheable
  `immutable`, and carries that stage's own card class;
* an unknown digest is a 404, so the mount serves memory and not the filesystem;
* `/static/styles.css`, the URL before the move to `backend/app/assets/`, is a
  404 - no page, test or tool may still be pointing at it.

The mount is a plain Starlette sub-application, so it runs no FastAPI app-level
dependency: it is outside the space resolution of `workshop-spaces` and answers
the same bytes in every space.
"""
from __future__ import annotations

import re

import pytest

from backend.app.core.workshop import STAGES

from .conftest import STAGE_FLAGS

#: The URL the stylesheet had before it moved out of `backend/app/static/`.
RETIRED_STYLESHEET_URL = "/static/styles.css"

#: The stylesheet link of a rendered page.
STYLESHEET = re.compile(r'<link[^>]*rel="stylesheet"[^>]*href="([^"]+)"')

#: The product-card block class each stage renames the rules to. Stages 1 and 3
#: rename nothing, so they share the stage-1 name and the stage-1 variant.
CARD_CLASS_BY_STAGE = {1: "product-card", 2: "item-card", 3: "product-card", 4: "product-tile"}


def linked_stylesheet(render, stage: int) -> str:
    """The stylesheet URL the home page links in ``stage``."""
    found = STYLESHEET.findall(render("/", STAGE_FLAGS[stage]).text)
    assert len(set(found)) == 1, found
    return found[0]


@pytest.mark.parametrize("stage", STAGES)
def test_the_linked_stylesheet_is_served_with_the_stage_names(
    render, contract_client, stage: int
) -> None:
    href = linked_stylesheet(render, stage)
    response = contract_client.get(href)

    assert response.status_code == 200, href
    assert response.headers["content-type"].startswith("text/css")
    assert "immutable" in response.headers["cache-control"]
    assert f".{CARD_CLASS_BY_STAGE[stage]}" in response.text


def test_an_unknown_digest_is_not_served(contract_client) -> None:
    """The mount answers from memory, so an unknown name is a 404."""
    assert contract_client.get("/assets/styles.0123456789abcdef.css").status_code == 404


def test_the_retired_stylesheet_url_is_gone(contract_client) -> None:
    """`/static/styles.css` no longer exists (task 6.2, re-checked by 15.6)."""
    assert contract_client.get(RETIRED_STYLESHEET_URL).status_code == 404
