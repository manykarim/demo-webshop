## 1. Fix

- [x] 1.1 Add `backend/app/core/caching.py` (new) with a pure ASGI middleware that adds `Cache-Control: private, no-store` to every HTTP response whose headers carry no `Cache-Control` and whose path does not start with `/static/` or `/assets/` (design D1), and register it in `backend/app/main.py`. Verify with `backend/tests/integration/test_cache_headers.py` (new): `/`, `/products`, `/cart`, `/checkout`, `/api/products/`, `/api/workshop/status`, `/api/cart/` and `/search/results?query=desk` carry `private, no-store`; an order's `invoice.pdf` and `summary.pdf` carry it on 200, on 404 (a missing order) and on 503 (`pdf_unavailable`); `/static/app.js` gets no forced header; `/assets/styles.<digest>.css` keeps `public, max-age=31536000, immutable`.
- [x] 1.2 Expose the script's content digest (design D2) as the Jinja global `app_js_version` and link `/static/app.js?v={{ app_js_version }}` in `backend/app/templates/base.html`. Verify in `test_cache_headers.py` that the rendered `src` equals `/static/app.js?v=` plus the first 16 hex characters of the SHA-256 of `backend/app/static/app.js`, and that `uv run pytest backend/tests/unit/test_template_scan.py` passes.

## 2. Verification and rollout

- [x] 2.1 Run `uv run pytest backend/tests` and `uv run pytest -m browser`, and verify that both are green.
- [ ] 2.2 Open a pull request, confirm `check` and `build` are green, merge it, and confirm that the next `main` run passes `test`, both `conformance` legs and `publish`.
- [ ] 2.3 Redeploy the shared instance by that run's `build` digest. Once the Cloudflare cache has been purged or its four-hour TTL has passed, verify through Cloudflare that an order's `invoice.pdf` answers `cf-cache-status` other than `HIT` together with `Cache-Control: private, no-store`, and 404 from another space.
- [ ] 2.4 Archive this change with `openspec archive fix-cdn-caching -y`, and verify that `openspec/specs/` is unchanged.
