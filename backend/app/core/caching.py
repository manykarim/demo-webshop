"""Cache headers for a shop that runs behind shared caches (change fix-cdn-caching).

The shared Coolify instance sits behind Cloudflare, which caches responses by
file extension and ignores the space header and cookie when it builds its
cache key. Without an explicit ``Cache-Control``, an order invoice requested in
one space was served from the CDN to every other space.
"""
from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

#: Paths whose content does not depend on the space, the session or the user.
#: Everything else is private to its requester.
CACHEABLE_PREFIXES = ("/static/", "/assets/")

#: Forbids shared caches (CDN, proxies) from storing the response, and keeps
#: browsers from reusing a page after the shopper switches space (design D1).
NO_SHARED_CACHE = b"private, no-store"

APP_JS = Path(__file__).resolve().parent.parent / "static" / "app.js"


class DefaultCacheControlMiddleware:
    """Adds ``Cache-Control: private, no-store`` unless the route set its own.

    A pure ASGI middleware, like ``WorkshopSpaceCookieMiddleware``, so file and
    streaming responses pass through untouched apart from the header.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path", "").startswith(CACHEABLE_PREFIXES):
            await self.app(scope, receive, send)
            return

        async def send_with_default(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                if not any(name.lower() == b"cache-control" for name, _ in headers):
                    headers.append((b"cache-control", NO_SHARED_CACHE))
                    message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_default)


@lru_cache(maxsize=1)
def app_js_version() -> str:
    """The first 16 hex characters of the client script's SHA-256 (design D2).

    Pages link ``/static/app.js?v=<this>``, so a cache keyed by URL can never
    pair a new page with an old script after a deployment.
    """
    return hashlib.sha256(APP_JS.read_bytes()).hexdigest()[:16]
