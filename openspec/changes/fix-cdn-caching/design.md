## Context

See proposal.md, Why. Cloudflare in front of the shared instance serves `/api/docs/orders/{id}/*.pdf` from its cache to every space. The shop sets no `Cache-Control` except on `/assets/styles.<digest>.css` (`public, max-age=31536000, immutable`). Pages and JSON responses are currently `DYNAMIC` at Cloudflare only because of its default rules, not because of anything the shop says.

## Goals / Non-Goals

**Goals:** no shared cache ever stores a space-, session- or user-dependent response; a script URL that changes with the script.

**Non-Goals:** configuring Cloudflare (the shop must be safe behind any CDN and any rule set); changing the stylesheet mechanism, which already works.

## Decisions

### D1. A default `Cache-Control: private, no-store`, set by middleware

A pure ASGI middleware adds `Cache-Control: private, no-store` to every response whose route did not set `Cache-Control`, except under `/static/` and `/assets/`. `private` forbids shared caches, which is the property that matters. `no-store` also keeps browsers from reusing a page after a space switch. Alternatives considered:
- **Set the header only on the document routes.** Rejected: any future route, or a "cache everything" CDN rule, would reopen the leak, and pages depend on the space too.
- **`Vary: X-Workshop-Space, Cookie`.** Rejected: Cloudflare ignores `Vary` for caching (except `Accept-Encoding`), so it would look right and change nothing.

It is a pure ASGI middleware, like `WorkshopSpaceCookieMiddleware`, so streaming and file responses are untouched.

### D2. Content-addressed script URL

At start-up the app hashes `static/app.js` once (the first 16 hex characters of SHA-256) and exposes it to templates. `base.html` links `/static/app.js?v=<digest>`. Cloudflare's default cache key includes the query string, so every script version gets its own cache entry. Alternative considered: `Cache-Control: no-cache` on the script. Rejected, because every page view would revalidate it. The digest keeps it cacheable for four hours and still correct.

## Risks / Trade-offs

- **[Already cached entries]** Responses Cloudflare stored before this fix stay cached until their TTL (four hours) expires, or until someone purges the zone. → Documented in the proposal's Impact. The rollout waits for expiry, or for a purge, before the load test.
- **[`no-store` on every page]** Browsers can't use back/forward cache for pages. → Irrelevant for a demo shop; correctness of spaces matters more.
