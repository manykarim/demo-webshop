"""Space resolution and the space cookie (tasks 3.2 and 3.3, design D1/D2).

The resolved space is observed through ``GET /api/workshop/status``, which task
3.2 gave a ``space`` field next to ``version``. It is a real route on the real
application, so it reaches the space through the same ``Depends(current_space)``
that every handler uses; the temporary probe route this module registered while
that field did not exist yet is gone.
"""
from __future__ import annotations

import re

import pytest

from backend.app.core.spaces import DEFAULT_SPACE, SPACE_COOKIE, SPACE_FORMAT_MESSAGE
from backend.tests.spaces.helpers import sqlite_rows

#: The route that reports the space a request was handled in.
STATUS_PATH = "/api/workshop/status"

#: The exact cookie the response hook appends for a query-parameter switch.
EXPECTED_COOKIE_TEMPLATE = "{name}={space}; Path=/; Max-Age=2592000; SameSite=Lax; HttpOnly"

#: An identifier that fails the format check in every source.
BAD_SPACE = "-bad--name-"

#: ``href`` of the stylesheet that the layout links; read from a real page so
#: this test keeps working when ``drift-coverage`` moves the file to /assets/.
_STYLESHEET_PATTERN = re.compile(r'<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"')


def resolved_space(client, **kwargs) -> str:
    """The space in which ``client`` handles a request."""
    response = client.get(STATUS_PATH, **kwargs)
    assert response.status_code == 200, response.text
    return response.json()["space"]


def set_space_cookie(client, value: str) -> None:
    """Store a space cookie the way a response of the test server stores it.

    Domain and path match the jar entry that a ``Set-Cookie`` from ``testserver``
    creates (``http.cookiejar`` files a dotless host under ``<host>.local``), so
    the cookie is sent with every request and an expiring cookie from the
    application removes this one instead of leaving it next to a second entry.
    """
    client.cookies.set(SPACE_COOKIE, value, domain="testserver.local", path="/")


def space_cookies(response) -> list[str]:
    """Every ``Set-Cookie`` header of ``response`` that carries the space cookie."""
    return [
        value
        for value in response.headers.get_list("set-cookie")
        if value.startswith(f"{SPACE_COOKIE}=")
    ]


# ---------------------------------------------------------------------------
# Task 3.2 - resolution order and the requests that stay outside it
# ---------------------------------------------------------------------------


def test_header_wins_over_cookie(app_client) -> None:
    set_space_cookie(app_client, "hubot")

    assert resolved_space(app_client, headers={"X-Workshop-Space": "octocat"}) == "octocat"


def test_no_space_given_is_the_default_space(app_client) -> None:
    assert resolved_space(app_client) == DEFAULT_SPACE


def test_mixed_case_handle_is_lowercased(app_client) -> None:
    assert resolved_space(app_client, headers={"X-Workshop-Space": "OctoCat"}) == "octocat"


@pytest.mark.parametrize("path", ["/", "/api/workshop/status"])
def test_invalid_identifier_is_rejected_on_pages_and_api(app_client, path: str) -> None:
    response = app_client.get(path, headers={"X-Workshop-Space": BAD_SPACE})

    assert response.status_code == 400
    assert response.json()["detail"] == SPACE_FORMAT_MESSAGE
    assert "1-39" in response.text


def test_invalid_header_is_not_rescued_by_a_valid_cookie(app_client) -> None:
    set_space_cookie(app_client, "octocat")

    response = app_client.get("/", headers={"X-Workshop-Space": BAD_SPACE})

    assert response.status_code == 400


def test_valid_header_is_not_broken_by_an_invalid_query_parameter(app_client) -> None:
    response = app_client.get(
        STATUS_PATH,
        params={"space": "-bad-"},
        headers={"X-Workshop-Space": "octocat"},
    )

    assert response.status_code == 200
    assert response.json()["space"] == "octocat"


def test_empty_header_falls_through_to_query_parameter_and_cookie(app_client) -> None:
    empty_header = {"X-Workshop-Space": ""}

    from_query = app_client.get(STATUS_PATH, params={"space": "octocat"}, headers=empty_header)
    assert from_query.json()["space"] == "octocat"

    app_client.cookies.clear()
    set_space_cookie(app_client, "hubot")
    from_cookie = app_client.get(STATUS_PATH, headers=empty_header)
    assert from_cookie.json()["space"] == "hubot"


def test_router_added_by_configure_routes_rejects_an_invalid_header(app_client) -> None:
    response = app_client.get("/api/cart/", headers={"X-Workshop-Space": BAD_SPACE})

    assert response.status_code == 400
    assert response.json()["detail"] == SPACE_FORMAT_MESSAGE


def test_static_assets_are_served_with_an_invalid_identifier(app_client) -> None:
    page = app_client.get("/")
    assert page.status_code == 200
    match = _STYLESHEET_PATTERN.search(page.text)
    assert match is not None, "the layout links no stylesheet"
    stylesheet_url = match.group(1)

    bad_header = {"X-Workshop-Space": BAD_SPACE}
    for url in ("/static/app.js", stylesheet_url):
        response = app_client.get(url, headers=bad_header)
        assert response.status_code == 200, f"{url} answered {response.status_code}"


def test_openapi_is_served_and_declares_no_space_inputs(app_client) -> None:
    response = app_client.get("/openapi.json", headers={"X-Workshop-Space": BAD_SPACE})

    assert response.status_code == 200
    schema = response.json()
    declared = {
        parameter.get("name")
        for path_item in schema["paths"].values()
        for operation in path_item.values()
        if isinstance(operation, dict)
        for parameter in operation.get("parameters", [])
    }
    assert declared.isdisjoint({"X-Workshop-Space", "space", "workshop_space"})
    assert "X-Workshop-Space" not in response.text


@pytest.mark.parametrize(("path", "status_code"), [("/no-such-path", 404), ("/docs", 200)])
def test_requests_outside_space_resolution_are_unchanged(app_client, path: str, status_code: int) -> None:
    plain = app_client.get(path)
    with_bad_space = app_client.get(path, headers={"X-Workshop-Space": BAD_SPACE})

    assert plain.status_code == status_code
    assert with_bad_space.status_code == status_code
    assert with_bad_space.content == plain.content
    assert space_cookies(plain) == []
    assert space_cookies(with_bad_space) == []


# ---------------------------------------------------------------------------
# Task 3.3 - the cookie hook
# ---------------------------------------------------------------------------


def test_query_parameter_sets_the_cookie_and_sticks(app_client) -> None:
    response = app_client.get("/", params={"space": "octocat"})

    assert response.status_code == 200
    assert space_cookies(response) == [
        EXPECTED_COOKIE_TEMPLATE.format(name=SPACE_COOKIE, space="octocat")
    ]
    # The client stored the cookie, so the next request stays in the space.
    assert resolved_space(app_client) == "octocat"


def test_cookie_is_set_on_an_error_response(app_client) -> None:
    response = app_client.get("/products/99999", params={"space": "octocat"})

    assert response.status_code == 404
    assert space_cookies(response) == [
        EXPECTED_COOKIE_TEMPLATE.format(name=SPACE_COOKIE, space="octocat")
    ]


def test_default_space_can_be_selected_explicitly(app_client) -> None:
    response = app_client.get("/", params={"space": DEFAULT_SPACE})

    assert space_cookies(response) == [
        EXPECTED_COOKIE_TEMPLATE.format(name=SPACE_COOKIE, space=DEFAULT_SPACE)
    ]
    assert resolved_space(app_client) == DEFAULT_SPACE


def test_invalid_cookie_is_expired_and_the_next_request_is_default(app_client) -> None:
    set_space_cookie(app_client, "-bad-")

    response = app_client.get("/")

    assert response.status_code == 400
    assert response.json()["detail"] == SPACE_FORMAT_MESSAGE
    expiring = space_cookies(response)
    assert len(expiring) == 1
    assert expiring[0].startswith(f"{SPACE_COOKIE}=;")
    assert "Max-Age=0" in expiring[0]
    # The client dropped the cookie, so it cannot lock the browser out.
    assert app_client.cookies.get(SPACE_COOKIE) is None
    assert resolved_space(app_client) == DEFAULT_SPACE


def test_header_or_cookie_alone_sets_no_cookie(app_client) -> None:
    from_header = app_client.get(STATUS_PATH, headers={"X-Workshop-Space": "octocat"})
    assert from_header.json()["space"] == "octocat"
    assert space_cookies(from_header) == []

    set_space_cookie(app_client, "hubot")
    from_cookie = app_client.get(STATUS_PATH)
    assert from_cookie.json()["space"] == "hubot"
    assert space_cookies(from_cookie) == []


def test_header_beats_query_parameter_and_sets_no_cookie(app_client) -> None:
    response = app_client.get(
        STATUS_PATH,
        params={"space": "hubot"},
        headers={"X-Workshop-Space": "octocat"},
    )

    assert response.json()["space"] == "octocat"
    assert space_cookies(response) == []


def test_file_response_keeps_its_body_and_gains_the_cookie(seeded_app_client, fake_weasyprint) -> None:
    rows = sqlite_rows("SELECT id FROM orders ORDER BY id LIMIT 1")
    assert rows, "the seeded database holds no order"
    url = f"/api/docs/orders/{rows[0][0]}/invoice.pdf"

    # Plain request first: the second one stores the cookie this one must not have.
    plain = seeded_app_client.get(url)
    assert plain.status_code == 200
    assert space_cookies(plain) == []

    switched = seeded_app_client.get(url, params={"space": "octocat"})

    assert switched.status_code == 200
    assert switched.content == plain.content
    assert space_cookies(switched) == [
        EXPECTED_COOKIE_TEMPLATE.format(name=SPACE_COOKIE, space="octocat")
    ]
