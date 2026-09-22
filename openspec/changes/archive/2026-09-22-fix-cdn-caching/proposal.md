## Why

`demoshop.makrocode.de`, the shared Coolify instance, sits behind Cloudflare. While task 3.3 of `workshop-rollout` was being verified, an order created in space `smoke-a` had its invoice (`/api/docs/orders/4/invoice.pdf`) served with HTTP 200 to space `smoke-b`. The origin answers that request with 404, as the `workshop-spaces` requirement "Space-scoped carts and orders" demands. Cloudflare, however, caches `.pdf` responses by extension (`cf-cache-status: HIT`, `Cache-Control: max-age=14400`), and the `X-Workshop-Space` header and the `workshop_space` cookie are not part of its cache key. Every invoice and order summary, with a customer's name, email and address, is therefore served to every space for four hours after its first request. The shop sends no `Cache-Control` of its own, so any shared cache is free to do this.

A related, latent problem: `/static/app.js` is cached for four hours under a fixed URL. After a deployment that changes the script, visitors can get the new pages with the old script, whose hooks no longer match. The per-stage stylesheet avoids this with a content digest in its URL.

## What Changes

- Every response that is not a static or per-stage asset carries `Cache-Control: private, no-store`, unless the route sets its own. That covers pages, JSON APIs and the order documents, so no shared cache (CDN or proxy) stores a response that depends on the space, the session or the signed-in user. `/static/*` and `/assets/*` keep their current caching.
- The page links the client script as `/static/app.js?v=<content digest>`, so a cache keyed by URL can never pair a new page with an old script.
- Tests pin both: headers on pages, APIs and every order-document response (200, 404, 503), no header forced on static assets, and a script URL that follows the script's content.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
None. `.openspec.yaml` sets `skip_specs: true`. The change restores the isolation that `workshop-spaces` ("Space-scoped carts and orders") already requires behind any shared cache; no requirement changes.

## Impact

- **Code**: `backend/app/core/caching.py` (new, a small pure ASGI middleware and the script digest), `backend/app/main.py` (register the middleware and a Jinja global), `backend/app/templates/base.html` (script URL).
- **Tests**: new `backend/tests/integration/test_cache_headers.py`.
- **Operations**: responses already cached by Cloudflare stay there until their four-hour TTL expires, or until the zone cache for `demoshop.makrocode.de` is purged. The shop cannot purge them. The load test's `leak:order` check (`workshop-rollout` 3.4) fails until then, because runtime order ids restart after a redeploy.
- **Rollout**: `workshop-rollout` 3.3 is re-verified through Cloudflare after the redeploy.
