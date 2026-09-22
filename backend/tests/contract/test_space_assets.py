"""A space switched through the URL still gets its assets (task 15.6 (e)).

`?space=octocat` is the way a human enters a workshop space in a browser
(`workshop-spaces` design D1): the query parameter decides the space *and* pins
the browser to it with the `workshop_space` cookie. The page it answers links
the per-stage stylesheet of `drift-coverage` (Decision 5) from `/assets/`, which
is mounted outside the space machinery - so this is the one place where the two
changes meet in a single request.

The check is therefore end to end: the page answers 200 and sets the cookie, the
`href` it links is read from that very response, and that URL answers 200 with a
CSS content type.

The cookie is removed from the package client again, because `contract_client`
is shared with the whole matrix and a left-over cookie would silently move every
later render into `octocat`.
"""
from __future__ import annotations

import re
from collections.abc import Iterator

import pytest

from backend.app.core.spaces import SPACE_COOKIE

#: The space the browser switches into.
SPACE = "octocat"

#: The stylesheet `base.html` links, read from the response rather than built
#: from a digest, so this follows the file wherever it is served from.
STYLESHEET = re.compile(r'<link[^>]*rel="stylesheet"[^>]*href="([^"]+)"')


@pytest.fixture
def no_leftover_space_cookie(contract_client) -> Iterator[None]:
    """Leave the package client in the `default` space, whatever happens."""
    try:
        yield
    finally:
        contract_client.cookies.delete(SPACE_COOKIE)


def test_the_query_parameter_sets_the_cookie_and_links_a_served_stylesheet(
    contract_client, no_leftover_space_cookie
) -> None:
    page = contract_client.get(f"/?space={SPACE}")

    assert page.status_code == 200, page.text
    assert page.cookies.get(SPACE_COOKIE) == SPACE
    assert f'data-workshop-space="{SPACE}"' in page.text

    hrefs = STYLESHEET.findall(page.text)
    assert len(set(hrefs)) == 1, hrefs
    href = hrefs[0]
    assert href.startswith("/assets/styles."), href

    stylesheet = contract_client.get(href)

    assert stylesheet.status_code == 200, href
    assert stylesheet.headers["content-type"].startswith("text/css")
    assert ".workshop-space" in stylesheet.text
