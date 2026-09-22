"""Workshop space resolution and the space cookie (design D1 and D2).

A *space* is the isolated workshop sandbox a request belongs to. Every page and
API route of the application is handled in exactly one space; static assets, the
generated API documentation and unknown paths are the same in every space and
never reach :func:`resolve_workshop_space`.

The module has four parts:

* :func:`resolve_workshop_space` - registered once as an application-level
  dependency, so it runs for every route, including the routers that
  ``configure_routes()`` adds later. It reads header, query parameter and cookie
  straight off the ``Request`` instead of declaring ``Header``/``Query``/
  ``Cookie`` parameters, so ``/openapi.json`` stays free of space parameters.
* :class:`WorkshopSpaceCookieMiddleware` - a pure ASGI middleware that appends
  the ``workshop_space`` cookie to the outgoing response when the dependency
  asked for it. It is deliberately not a ``BaseHTTPMiddleware``: it only touches
  the response headers and never wraps the body, so a ``FileResponse`` (the
  order PDFs) is streamed untouched.
* :func:`require_workshop_write_access` - the shared-mode guard of the workshop
  control operations (design D6).
* :func:`cart_session_id` and :func:`cart_storage_key` - the cart keys that keep
  identical session ids apart between spaces (design D3).
"""
from __future__ import annotations

import re
import secrets
from typing import Final

from fastapi import Depends, HTTPException, Request
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import settings

#: The space every request falls back to, and the one the global tables hold.
DEFAULT_SPACE: Final[str] = "default"

#: Request header with the highest precedence (used by the workshop tooling).
SPACE_HEADER: Final[str] = "X-Workshop-Space"
#: Query parameter a human uses to switch space in the browser.
SPACE_QUERY_PARAM: Final[str] = "space"
#: Cookie that keeps a browser in its space after the query parameter is gone.
SPACE_COOKIE: Final[str] = "workshop_space"

#: GitHub username format: 1-39 characters, single inner hyphens only.
SPACE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9](?:[a-z0-9]|-(?=[a-z0-9])){0,38}$")

#: The one message shown for every invalid identifier, whatever its source.
SPACE_FORMAT_MESSAGE: Final[str] = (
    "Invalid workshop space. Use your GitHub handle: 1-39 characters, letters, "
    "digits and single hyphens, and it may not start or end with a hyphen."
)

#: Lifetime of the space cookie, matching the ``session_id`` cookie in app.js.
SPACE_COOKIE_MAX_AGE: Final[int] = 2592000

#: ``request.state`` attribute holding the resolved space of the request.
SPACE_STATE_ATTR: Final[str] = "workshop_space"
#: Marker attribute: the response must store this space in the cookie.
COOKIE_SET_STATE_ATTR: Final[str] = "workshop_space_set_cookie"
#: Marker attribute: the response must expire an unusable space cookie.
COOKIE_EXPIRE_STATE_ATTR: Final[str] = "workshop_space_expire_cookie"

#: Paths that are identical in every space. They are served by mounts today and
#: never run the dependency; the guard keeps an invalid space header harmless if
#: an asset is ever served by an API route instead of a mount (design D1).
SPACELESS_PATH_PREFIXES: Final[tuple[str, ...]] = ("/static/", "/assets/")

#: Cart session id used when a caller sends no ``X-Session-ID`` and carries no
#: ``session_id`` cookie. The same value in every space (design D3), so the
#: ``session`` an API response reports never depends on the space.
CART_FALLBACK_SESSION_ID: Final[str] = "workshop-demo"

#: Separator between the space and the cart session id in a storage key. The
#: identifier alphabet (design D2) excludes it, so ``octo`` never prefixes
#: ``octocat:...`` and ``LIKE '<space>:%'`` needs no escaping (design D7).
CART_KEY_SEPARATOR: Final[str] = ":"

#: The 401 body of :func:`require_workshop_write_access` (design D6). It names
#: both ways into a personal space, because the usual cause is a participant
#: whose tooling forgot to send the space.
WORKSHOP_WRITE_DENIED_MESSAGE: Final[str] = (
    "This is a shared workshop instance. Changing the default space needs the "
    "facilitator token. Use your own space: add `?space=<github-handle>` to the "
    "URL or send the header `X-Workshop-Space: <github-handle>`."
)


def normalize_space(raw: str | None) -> str | None:
    """Return the canonical space identifier of ``raw``.

    Trims the value and returns ``None`` when nothing is left, so a blank
    profile variable or an empty ``?space=`` counts as "not provided". Otherwise
    the value is lower-cased (identifiers are case-insensitive) and validated
    against :data:`SPACE_PATTERN`.

    Raises:
        ValueError: with :data:`SPACE_FORMAT_MESSAGE` if the value is invalid.
    """
    if raw is None:
        return None

    candidate = raw.strip()
    if not candidate:
        return None

    candidate = candidate.lower()
    if not SPACE_PATTERN.fullmatch(candidate):
        raise ValueError(SPACE_FORMAT_MESSAGE)
    return candidate


def _reject(exc: ValueError) -> HTTPException:
    """The HTTP 400 that an invalid identifier produces on any route."""
    return HTTPException(status_code=400, detail=str(exc))


async def resolve_workshop_space(request: Request) -> str:
    """Determine the space of ``request`` and remember it on ``request.state``.

    Precedence (design D1): the ``X-Workshop-Space`` header, then the ``space``
    query parameter, then the ``workshop_space`` cookie, then
    :data:`DEFAULT_SPACE`. The first source with a non-empty value decides;
    lower sources are never consulted, so an invalid header is not rescued by a
    valid cookie and a valid header wins over an invalid ``?space=``.

    Only the query parameter sets the cookie. An invalid *cookie* additionally
    marks the cookie for expiry, so a tampered cookie cannot lock a browser out.
    """
    if request.url.path.startswith(SPACELESS_PATH_PREFIXES):
        request.state.workshop_space = DEFAULT_SPACE
        return DEFAULT_SPACE

    try:
        space = normalize_space(request.headers.get(SPACE_HEADER))
    except ValueError as exc:
        raise _reject(exc) from exc
    if space is not None:
        request.state.workshop_space = space
        return space

    try:
        space = normalize_space(request.query_params.get(SPACE_QUERY_PARAM))
    except ValueError as exc:
        raise _reject(exc) from exc
    if space is not None:
        request.state.workshop_space = space
        # A human switched space through the URL: keep the browser there.
        setattr(request.state, COOKIE_SET_STATE_ATTR, space)
        return space

    try:
        space = normalize_space(request.cookies.get(SPACE_COOKIE))
    except ValueError as exc:
        setattr(request.state, COOKIE_EXPIRE_STATE_ATTR, True)
        raise _reject(exc) from exc
    if space is not None:
        request.state.workshop_space = space
        return space

    request.state.workshop_space = DEFAULT_SPACE
    return DEFAULT_SPACE


async def current_space(request: Request) -> str:
    """Accessor dependency: the space that :func:`resolve_workshop_space` set.

    Falls back to :data:`DEFAULT_SPACE` so a handler used outside the
    application dependency (a direct call in a test) still has a space.
    """
    return getattr(request.state, SPACE_STATE_ATTR, DEFAULT_SPACE)


async def require_workshop_write_access(
    request: Request, space: str = Depends(current_space)
) -> None:
    """Guard the workshop control operations on a shared instance (design D6).

    Shared mode protects the *baseline*, not individual spaces, so the request
    is allowed when

    * shared mode is off - a local run behaves exactly as before spaces
      existed, with no credentials anywhere; or
    * the request is handled in a space of its own - a participant never needs
      a token; or
    * it carries ``Authorization: Bearer <WORKSHOP_ADMIN_TOKEN>``, compared with
      :func:`secrets.compare_digest` so the comparison takes constant time.

    Otherwise it answers 401 with ``WWW-Authenticate: Bearer`` and
    :data:`WORKSHOP_WRITE_DENIED_MESSAGE`, which tells a participant who forgot
    the space how to get one. Reads and shop behaviour (carts, checkout) are
    never guarded.
    """
    if not settings.shared_mode:
        return
    if space != DEFAULT_SPACE:
        return

    token = settings.admin_token.get_secret_value() if settings.admin_token else ""
    scheme, _, credentials = (request.headers.get("Authorization") or "").partition(" ")
    if token and scheme.lower() == "bearer" and secrets.compare_digest(credentials.strip(), token):
        return

    raise HTTPException(
        status_code=401,
        detail=WORKSHOP_WRITE_DENIED_MESSAGE,
        headers={"WWW-Authenticate": "Bearer"},
    )


def cart_session_id(session_id: str | None) -> str:
    """The caller-facing cart session id, the same in every space (design D3).

    This is the value cart API responses report as ``session``: the
    ``X-Session-ID`` the caller sent, or :data:`CART_FALLBACK_SESSION_ID` when
    it sent none. It never carries a space prefix, so a test that compares the
    reported session with the id it sent passes in every space.
    """
    return session_id or CART_FALLBACK_SESSION_ID


def cart_storage_key(space: str, session_id: str | None) -> str:
    """The ``cart_items.session_key`` that ``session_id`` uses inside ``space``.

    In :data:`DEFAULT_SPACE` this is the plain session id, so local databases
    keep their existing keys unchanged. Every other space prefixes it with
    ``<space>:``, which isolates identical session ids - including the shared
    fallback - between participants.
    """
    resolved = cart_session_id(session_id)
    if space == DEFAULT_SPACE:
        return resolved
    return f"{space}{CART_KEY_SEPARATOR}{resolved}"


def _space_cookie_header(space: str) -> str:
    """The ``Set-Cookie`` value that pins a browser to ``space``."""
    return (
        f"{SPACE_COOKIE}={space}; Path=/; Max-Age={SPACE_COOKIE_MAX_AGE}; "
        "SameSite=Lax; HttpOnly"
    )


def _expired_space_cookie_header() -> str:
    """The ``Set-Cookie`` value that removes an unusable space cookie."""
    return (
        f"{SPACE_COOKIE}=; Path=/; Max-Age=0; "
        "Expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax; HttpOnly"
    )


class WorkshopSpaceCookieMiddleware:
    """Append the ``workshop_space`` cookie asked for by the dependency.

    A pure ASGI middleware (design D1): it wraps ``send`` and only edits the
    headers of ``http.response.start``, so response bodies - including the
    streamed ``FileResponse`` of the order documents - are passed through
    untouched, and error responses of a route carry the cookie as well.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_space_cookie(message: Message) -> None:
            if message["type"] == "http.response.start":
                # Read at send time: the dependency writes into the same
                # ``scope["state"]`` mapping that ``request.state`` exposes.
                state = scope.get("state") or {}
                cookie = None
                space = state.get(COOKIE_SET_STATE_ATTR)
                if space:
                    cookie = _space_cookie_header(space)
                elif state.get(COOKIE_EXPIRE_STATE_ATTR):
                    cookie = _expired_space_cookie_header()
                if cookie is not None:
                    MutableHeaders(scope=message).append("set-cookie", cookie)
            await send(message)

        await self.app(scope, receive, send_with_space_cookie)
