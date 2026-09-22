## Context

See `proposal.md` (Why) for the motivation and `specs/workshop-spaces/spec.md` for the requirements. This design depends on `reproducible-image`: uv dependency groups, `uv.lock`, version reporting, insert-if-missing seeding on every container start through `tools/entrypoint.py` (its D4), mutable state under `/data` in the image (its D3) and the shared pytest harness (its D11: `backend/tests/harness.py` with `isolated_app` and the environment declarations, and the root `backend/tests/conftest.py` with the fixtures `temp_database`, `app_client`, `seeded_app_client`, `pdf_unavailable` and `fake_weasyprint`). `workshop-spaces` and `drift-coverage` may be developed in parallel after `reproducible-image`. `workshop-spaces` merges first, and `drift-coverage` codes against the `get_effective_flags` seam defined here and then rebases (`drift-coverage` task 15.1).

Current state that shapes the approach. All of it was checked against the code on the base before `reproducible-image`. Where `reproducible-image` changes a fact, the bullet says so.

- **Flag reads are global and cached per process.** `backend/app/core/feature_flags.py` keeps a module-level `TTLCache(maxsize=32, ttl=settings.feature_flag_cache_seconds)` under the single key `"flags"`. `set_feature_flag` commits once per flag and clears only the cache of the process that made the change. The TTL is 30 s in `core/config.py`, but `.env.example` sets `WORKSHOP_FEATURE_FLAG_CACHE_SECONDS=10`. `if cached:` counts an empty dict as a cache miss, and every caller gets the same shared dict object. Environment overrides (`WORKSHOP_FLAG_*`) are collected from `os.environ` in `Settings.model_post_init` and applied last. `cachetools` has one importer: `feature_flags.py`.
- **Flag call sites:** 6 page routes in `backend/app/main.py`; `api/workshop.py` (status, preset, flags; a preset calls `set_feature_flag` once per key, so it makes one commit per flag); `api/admin.py` (GET, PUT); `api/search.py` (`is_enabled(..., "SEARCH_V2")`); `services/ai_service.py` (`_load_flags`, which drives `AI_DETERMINISTIC`, `AI_RANDOM_DELAYS` and `AI_VARIED_RESPONSES`). `configure_routes()` imports every router when `main.py` is imported, so removing a function that any of these modules still imports breaks `import backend.app.main`.
- **Carts are keyed by a session string.** In `main.py`, `resolve_session_key` takes the `x-session-id` header, then the `session_id` cookie, then `"workshop-demo"`. `api/cart.py` and `api/checkout.py` accept only the `X-Session-ID` header, with the same fallback. `static/app.js` creates the `session_id` cookie (UUID, 30 days) and sends it as `X-Session-ID` on cart fetches. `cart_items.session_key` is declared `String(64)` (`models/cart.py`). `CartService.get_cart_state()` reports its storage key as `session` (`services/cart_service.py:69-70`), and `DELETE /api/cart/` returns `cart_service.session_key` (`api/cart.py:54`).
- **Orders have no owner scope.** `models/order.py` has no space or session column. Checkout calls `OrderService.create_order` without `user_id` (`main.py:303`, `api/checkout.py:42`), and seeding always passes `user_id` (`seeds/seed_data.py:408-415`). As a result, runtime orders never appear in login history today: `api/auth.py` loads `User.orders`. `api/docs.py` serves invoice and summary PDFs for any order by its sequential id. Order reads happen only in `api/auth.py`, `api/docs.py` and inside `order_service.py`.
- **PDF location.** PDFs are written to `settings.pdf_output_dir`. Before `reproducible-image` that is `backend/app/static/pdfs` (38 files committed), which the `/static` mount also serves by file name (`invoice_<order_number>.pdf`). `reproducible-image` keeps that default only for local, non-container runs and removes the 36 generated order PDFs from git (only `example_invoice.pdf` and `example_order_summary.pdf` stay tracked). Its maintainer decision (its D3, spec *Order documents in the container*) moves the image's PDFs to `/data/pdfs`, outside the `/static` mount, where they are served only through `/api/docs/orders/{id}/invoice.pdf` and `/summary.pdf`. The shared instance runs the image, so `backend/app/static/pdfs` is never its PDF location. Generated `workshop.db` and `*_ORD-*.pdf` files are gitignored, so stray files are detected with the marker-and-`find` check of `reproducible-image` D11, not with `git status`.
- **Schema evolution:** `core/db.py:init_db` runs `create_all` at start-up, which creates missing tables but not missing columns. The `ensure_product_columns` and `ensure_order_columns` helpers (`PRAGMA table_info` plus `ALTER TABLE`) run only during seeding. After `reproducible-image` they run on every seed, and so on every container start, but still not on plain `uvicorn` runs or in tests. There is no Alembic.
- **Seed idempotency.** Before `reproducible-image` (verified): `seed_products` upserts by SKU; `seed_feature_flags` inserts only missing keys and keeps existing values; `seed_users` is not idempotent (it bulk-deletes and recreates addresses, payment methods and orders with new ids, order numbers and PDFs, leaving `order_items` orphaned because SQLite foreign-key enforcement is off). `reproducible-image` D4 replaces this: seeding inserts only missing SKUs, flags and users, creates order history only together with a new user, and renders no PDFs, so a second run changes no existing rows and runtime orders (`user_id` NULL) survive. This design assumes that state. Foreign-key enforcement stays off, so deletes of orders must remove their `order_items` explicitly.
- **No SQLite tuning.** No PRAGMAs are set. For a file database with aiosqlite, SQLAlchemy 2.0 uses `AsyncAdaptedQueuePool` with its defaults: 5 connections, 10 overflow, 30 s timeout. An `AsyncSession` keeps its connection checked out from the first query until the transaction ends, including during `asyncio.sleep` delays such as `AI_RANDOM_DELAYS`.
- **AI provider:** chosen from `settings.ai_provider` and can be overridden per request by the body field `provider` (`api/ai.py:19`, `ai_service.py:223`).
- **No authentication** on `api/workshop.py` or `api/admin.py`.
- **FastAPI response headers and dependencies:** headers set on an injected `Response` parameter are merged only when the endpoint returns a plain value, not a `Response` object (`fastapi/routing.py`). Every page route returns a `TemplateResponse`, so a dependency alone cannot set a cookie on pages. App-level dependencies (`FastAPI(dependencies=[...])`) also apply to routers included later through `configure_routes()`; I checked this with a scratch app. They do not run for `Mount`s such as `/static`, for FastAPI's own `/openapi.json`, `/docs` and `/redoc` routes (plain Starlette routes), or for requests that match no route.
- **Template context:** `_mount_static_and_templates` in `main.py` builds one `Jinja2Templates` with the filter `currency` and the single global `brand_name`. Each of the six page routes passes its own context dict that starts with `"request": request`, so `request` is available in `base.html` (it already uses `request.url.path`), but `settings` is not available in any template. The PDF templates under `templates/pdf/` are rendered by `PDFService` with their own context and do not extend `base.html`.
- **Settings sources:** `Settings` reads the process environment and a gitignored `.env` in the working directory (`env_file=".env"`), and process environment variables win. A developer's `.env` can therefore change test behavior unless tests pin the relevant variables.
- **External origins:** templates, `app.js` and `styles.css` load no third-party resources. The only external URLs are footer navigation links (`github.com`, `x.com`) and schema.org identifiers in JSON-LD.

## Goals / Non-Goals

**Goals:**
- One place that resolves the request's space and one seam, "effective flags for this request", that every page, API and service uses. No code path can read flags without a space.
- In local mode, the `default` space is byte-for-byte today's behavior: same cart keys, same global flag rows, no credentials needed, no indicator. The only difference is that flag changes take effect immediately. In shared mode, `default` differs only through the 401 on control operations, the forced mock AI and the indicator with its hint.
- Participants on the shared instance are isolated from each other's *accidents* and from changes to the `default` space, and the shared baseline (`default` space) is protected by a facilitator token.
- Capacity is proven on the release commit that `workshop-<id>` is built from: same application code, shared mode, single process, and per instance if participants are split.

**Non-Goals:**
- Ownership or authentication of individual spaces. Anyone who knows a handle can act in that space (see Risks).
- Isolating products, users, addresses or payment methods. These stay global; workshop flows only read them.
- Keeping spaces across redeploys, listing spaces, or an admin UI.
- Horizontal scaling beyond the documented contingency (several independent instances).
- Changing drift stages, planted bugs or preset contents (`drift-coverage`), and changing order-number format or checkout validation (`acceptance-conformance`).
- The workshop repository's `robot.toml` profiles and agent configurations. They are named here only as consumers.

## Decisions

### D1: Resolve the space in an app-level dependency; set the cookie in a response hook

A new module `backend/app/core/spaces.py` provides `resolve_workshop_space(request)`, registered once as `FastAPI(dependencies=[Depends(resolve_workshop_space)])`. It therefore runs for every page and API route, including routers added by `configure_routes()`. Resolution:

1. Check the sources in precedence order: `X-Workshop-Space` header, `space` query parameter, `workshop_space` cookie. The first source whose trimmed value is non-empty wins. Lower sources are never consulted, so an invalid header is not rescued by a valid cookie, and a valid header wins over an invalid `?space=`. Empty values count as "not provided", so a profile variable left blank does not break local runs.
2. Lower-case and validate the value (D2). If it is invalid, raise `HTTPException(400)` with a message that states the format.
3. Store the result as `request.state.workshop_space`. If the source was the query parameter, also store a marker telling the hook to set the cookie. A space taken from the header or a valid cookie sets no cookie, even when a `space` query parameter is also present. If an invalid value came from the cookie, store a marker telling the hook to expire the cookie, so a tampered cookie cannot lock a browser out.
4. If no source is present, use `default`.

Handlers receive the space through a small accessor dependency (`current_space`). The dependency reads header, query and cookie from `request` directly instead of declaring `Header`/`Query`/`Cookie` parameters, so `/openapi.json` does not change. This matches the non-disclosure requirement in `drift-coverage`.

The cookie is set by a small **pure ASGI middleware**. On `http.response.start` it reads the marker from `scope["state"]` and appends `Set-Cookie: workshop_space=<id>; Path=/; Max-Age=2592000; SameSite=Lax; HttpOnly`, or an expiring cookie. It also applies to error responses of a route, so `/products/99999?space=octocat` sticks even when that request fails. The 30-day lifetime matches the `session_id` cookie in `app.js`. `BaseHTTPMiddleware` is avoided because it wraps response bodies (`FileResponse` for PDFs).

Static files under `/static`, mounted asset routes (for example the per-stage stylesheet under `/assets/` that `drift-coverage` adds), FastAPI's generated documentation and requests that match no route do not run the dependency (see Context). They are the same in every space. If an asset route is ever added as an API route instead of a mount, `resolve_workshop_space` returns `default` early for it, so an invalid space header never breaks a stylesheet.

*Alternatives considered:*
- **Subdomain per space:** needs wildcard DNS and TLS on Coolify, and hosts-file entries locally.
- **Path prefix `/s/<space>/`:** changes every absolute link in templates and `app.js` (`/api/cart`, `/checkout`, …) and every test URL, and conflicts with the drift contract that URLs stay stable.
- **Middleware-only resolution:** would work, but bypasses FastAPI exception handling and hides the space from handler signatures.
- **Setting the cookie through an injected `Response`:** dropped for `TemplateResponse` (see Context).

### D2: Space identifier = GitHub handle

The pattern is `^[a-z0-9](?:[a-z0-9]|-(?=[a-z0-9])){0,38}$`, applied after lower-casing. It allows 1-39 characters and single inner hyphens only; I checked it against `octocat`, `-bad--name-`, `a--b`, `a-` and a 40-character string. `default` is the implicit space and is also accepted explicitly: `?space=default` returns a browser to the default space. Participants use their own GitHub handle: it is unique, they already know it, and there is no assignment step. The alphabet excludes `:`, `%` and `_`. That makes the prefixed cart keys (D3) unambiguous and the `LIKE '<space>:%'` patterns (D7) safe without escaping.

*Alternatives considered:*
- **Facilitator-assigned numbers:** need an assignment step, and typos collide silently.
- **Free-form names:** unsafe inside keys, SQL patterns and logs.
- **Random tokens:** unguessable but hard to type, and they must be distributed.

### D3: Data model: separate space flag table, prefixed cart keys, nullable order space

- **Flags:** new table `space_feature_flags(space VARCHAR(39), key VARCHAR(64), enabled BOOLEAN NOT NULL, PRIMARY KEY (space, key))`, with a `SpaceFeatureFlag` model in `models/feature_flag.py`. It holds only non-default spaces. The `default` space is the existing global `feature_flags` table. A separate table is needed because `feature_flags` has a surrogate `id` and a unique `key`, and SQLite cannot change that constraint without rebuilding the table. `create_all` creates the new table on existing databases with no migration code.
- **Carts:** two helpers in `core/spaces.py` are used by pages and APIs:
  - `cart_session_id(session_id)` = `session_id or "workshop-demo"`: the caller-facing session id, the same in every space.
  - `cart_storage_key(space, session_id)`: in `default` it returns `cart_session_id(session_id)`, which is the legacy key, unchanged. In other spaces it returns `f"{space}:{cart_session_id(session_id)}"`.

  Each caller type still resolves `session_id` as today: pages use header, then cookie; APIs use the header only. As today, pages and APIs without a session share one fallback cart per space: `workshop-demo` in `default` and `<space>:workshop-demo` elsewhere. `CartService(session, session_key, session_label=None)` queries by the storage key and reports `session_label` (default: the storage key) as the `session` field of `get_cart_state()`, which `GET /api/cart/` and `POST /api/cart/items` return. `DELETE /api/cart/` returns `cart_service.session_label` instead of `session_key`. `api/cart.py` passes `cart_session_id(session_id)` as the label, so the `session` field is the `X-Session-ID` value, or `workshop-demo` without the header, in every space, and never contains the space prefix. The label is passed in rather than derived by splitting the key on `:`, because a hand-crafted default-space session id may contain `:`. Pages and `api/checkout.py` never expose the field and pass only the storage key. Tests that compare `session` with the `X-Session-ID` they sent pass in both profiles, and `acceptance-conformance` (API-005 AC-1, AC-8, AC-10 and its probe task 1.2) relies on `"session": "workshop-demo"` without the header inside its own space. The `String(64)` declaration is widened to 128 for documentation only. SQLite gives `VARCHAR` text affinity and does not enforce lengths, so no migration is needed. The longest fallback key is 53 characters (a 39-character space id, `:` and the 13-character `workshop-demo`), and a UUID browser session in a 39-character space gives a 76-character key, which is why the declaration is widened past 64.
- **Orders:** new column `orders.space VARCHAR(39) NULL`, indexed. `OrderService.create_order` gains a `space` keyword:
  - Runtime checkouts pass the resolved space, *including* `"default"`.
  - Seeding passes nothing, so seeded orders keep `NULL`.
- **Schema upgrade on every start:** `ensure_order_columns` is extended to add `space` when it is missing and to run `CREATE INDEX IF NOT EXISTS`. On every run it also backfills `UPDATE orders SET space = 'default' WHERE space IS NULL AND user_id IS NULL`. Seeded orders always have a `user_id` (see Context), so rows without user and space can only be runtime checkout orders: legacy ones from before this change, or ones written by an older image after a rollback (Migration Plan step 9). They are never mistaken for seeded history, stay scoped to `default` and can be reset. The update is idempotent. The `ensure_*` helpers move into `core/db.py:init_db()`, right after `create_all`. Both the application lifespan and `seed_data.main()` call `init_db()`, so the helpers cover:
  - plain `uvicorn` runs and TestClient tests on persisted local databases, which never run the entrypoint seeder and would otherwise query a missing `orders.space` column;
  - the container entrypoint, where seeding runs before the app starts and must already see `orders.space`.

  This keeps them the hook that `reproducible-image` D4 names. The explicit helper calls in `seed_products` and `seed_users` become redundant and are removed; `seed_data.main()` has no such call of its own and reaches the helpers through `init_db()`. Running the helpers twice would be harmless.

*Alternatives considered:*
- **A `space` column on `cart_items`:** needs an `ALTER` and changes every cart query.
- **`<space>:api` as the non-default fallback cart (the original brief):** the reported session would be `api` on the shared instance and `workshop-demo` locally, which breaks `acceptance-conformance` and makes participants on the fallback report a defect that exists only there.
- **Reporting the session by splitting the storage key on `:`:** wrong for hand-crafted default-space ids that contain `:`.
- **One SQLite file per space:** strong isolation, but needs an engine and session per request and seeding per space.
- **Alembic:** a new tool and workflow for disposable demo data; rejected in the brief.
- **Storing `NULL` for default-space runtime orders:** they could not be told apart from seeded orders during reset.
- **Backfilling only in the run that adds the column:** orders written later by an older image after a rollback would stay `NULL`, visible in every space and impossible to reset.

### D4: Effective flags resolved per request, no cache (the seam for other changes)

`core/feature_flags.py` becomes the only flag API. **Precedence (the wording other changes quote):** environment override, then the space value (non-default spaces), then the baseline (non-default spaces) or the global value (`default` space).

- `baseline_flags() -> dict[str, bool]` returns a new dict: the seeded `FEATURE_FLAGS` defaults (`seeds/seed_data.py`) with preset `clean` applied on top. Both are imported lazily inside the function to avoid import cycles. After `drift-coverage`, the defaults come from its flag registry and the preset from `build_presets()["clean"]` (its rebase, task 15.1, points `baseline_flags()` there), so new flags such as `BUG_CHECKOUT_TOTAL` are included.
- `resolve_effective_flags(space) -> dict[str, bool]` uses a **short-lived session** from the session factory, so no pooled connection stays held while the page renders or during artificial delays. It returns a fresh dict:
  - `default`: global rows, then environment overrides.
  - Any other space: `baseline_flags()`, then that space's rows, then environment overrides. It never reads the global `feature_flags` rows.
- `get_effective_flags`, a FastAPI dependency, returns `resolve_effective_flags(current_space)`. FastAPI caches it per request. **This is the seam** that `drift-coverage` template helpers, bug toggles and `BUG_SLOW_RESPONSE` must use. They receive the dict and never query flags themselves.
- `set_flags(session, space, updates)` writes all updates in **one transaction**. For `default` it upserts `feature_flags` rows, creating unknown keys as today. For other spaces it upserts `space_feature_flags` with SQLite `INSERT … ON CONFLICT (space, key) DO UPDATE`. Keys are upper-cased as today.
- `clear_space_flags(session, space)` is used by reset (D7).
- **Transitional wrappers:** `list_feature_flags(session)`, `is_enabled(session, key)` and `set_feature_flag(session, key, enabled)` keep their signatures while their call sites move, as uncached wrappers over the `default` space (`resolve_effective_flags("default")` and `set_flags(session, "default", {key: enabled})`). The app stays importable after every task. Once the last caller (admin) has moved to the seam, the wrappers are deleted. From then on all call sites listed in Context use the seam: page routes, workshop status/preset/flags, admin GET/PUT, search, and `AIService`, which receives the flags dict instead of loading it. A unit test makes sure the flag models are not queried outside this module.

**Why non-default spaces fall back to a fixed baseline and not to the live global rows.** On the shared instance a token holder may change `default`, for example for a live drift demo. With a fallback to the global rows, every space that has not set a flag would change with it: a brand-new space, a space that was just reset, and a space that applied only a preset owning other flag groups (`drift-coverage` Decision 12: `buggy` owns only bug flags and would keep the global locator stage). The baseline makes every space start, and reset, to the same known state regardless of `default`. This refines the brief's "space value > global value" for non-default spaces; local mode and the `default` space are unchanged. Keys that exist only as global rows (for example created by an admin PUT in `default`) do not appear in other spaces. Environment overrides still apply to every space.

Removing the cache costs one indexed read of about 15 rows per request (global rows in `default`, the space's rows elsewhere), and fixes staleness across workers and instances. `WORKSHOP_FEATURE_FLAG_CACHE_SECONDS` stays accepted but is ignored, with one deprecation warning at start-up when it is set. It is removed from `.env.example`. `cachetools` and `types-cachetools` are dropped from `pyproject.toml`, and `uv.lock` is regenerated.

*Alternatives considered:*
- **Non-default spaces fall back to the live global rows:** simpler, but any change to `default` leaks into every participant space that has not set that flag, including freshly reset spaces.
- **Writing the `clean` values into a space on reset or on its first write:** more rows, and spaces that never wrote would still follow `default`.
- **Per-space TTL cache with invalidation:** per-process caches go stale across workers and instances and break "effective for the next request".
- **A version counter in the database to validate the cache:** still one read per request, plus invalidation code.
- **Keeping the global cache and adding the space to its key:** same staleness problem.
- **Deleting the old functions first and moving call sites afterwards:** the app cannot be imported between those steps, so no intermediate task can be verified.

### D5: One visibility rule for orders

A shared SQL predicate, `order_visible_in(space)` = `space IS NULL OR space = :space`, is applied wherever orders are read for a client:

- Login history in `api/auth.py`: filtered relationship load, for example `selectinload(User.orders.and_(…))`.
- Document endpoints in `api/docs.py`: `_fetch_order` returns the same 404 as for a missing order when the order is not visible.

Runtime orders are not linked to users today, so the login filter changes nothing now. It still makes the requirement hold if `acceptance-conformance` links checkout orders to signed-in users.

*Alternative considered:* filtering only login history. That leaves other spaces' invoices reachable by guessing sequential ids.

### D6: Shared mode protects the baseline, not individual spaces

- **Settings:** `shared_mode: bool = False` (`WORKSHOP_SHARED_MODE`) and `admin_token: SecretStr | None` (`WORKSHOP_ADMIN_TOKEN`). A settings validator rejects shared mode without a non-empty token. `settings` is created at import, so uvicorn exits non-zero with a message naming `WORKSHOP_ADMIN_TOKEN` before it binds port 9090. The container never turns healthy and Coolify marks the deployment failed.
- **Guard:** a dependency, `require_workshop_write_access`, is attached to the control operations `PUT /api/admin/flags/{key}` and `POST /api/workshop/preset`, `/flags` and `/reset`. It allows the request when shared mode is off, or when the space is not `default`, or when `Authorization: Bearer <token>` matches (checked with `secrets.compare_digest`). Otherwise it answers 401 with `WWW-Authenticate: Bearer` and a message: *"This is a shared workshop instance. Changing the default space needs the facilitator token. Use your own space: add `?space=<github-handle>` to the URL or send the header `X-Workshop-Space: <github-handle>`."*
- **What stays open:** reads (`GET` status, presets, admin flags) show only the caller's space. Carts and checkout in `default` (API and form) are not guarded either. They are shop behavior, and blocking them would make a forgotten header look like a shop defect.
- **AI:** in shared mode `AIService` always uses `MockLLM`. It ignores both `settings.ai_provider` and the per-request `provider` override, so there is no outbound HTTP, no shared API key use, and answers are deterministic.
- **No enumeration:** no endpoint returns any space id other than the caller's. Status adds only `space` (and `version` from `reproducible-image`). Reset reports counts for the caller's space only. No admin listing endpoint is built, because "reset all" is a redeploy (D11).

*Alternatives considered:*
- **Per-participant tokens:** a distribution step, and contradicts "GitHub handle, no assignment".
- **A token on every workshop call:** puts a secret into participants' forks and CI.
- **IP allow-lists:** venue NAT makes them useless.
- **One Coolify instance per participant:** about 40 deployments to operate.

### D7: `POST /api/workshop/reset` removes exactly what a space created

The endpoint is guarded by D6. All database deletes run in one transaction:

- **Non-default space:**
  - delete that space's `space_feature_flags` rows, so the space falls back to `baseline_flags()` (D4) regardless of the `default` space;
  - delete `cart_items` with `session_key LIKE '<space>:%'` (this includes `<space>:workshop-demo`; the trailing colon means `octo` never matches `octocat:*`);
  - delete `order_items` of the space's orders, then the orders. The delete is explicit because foreign-key cascades do not fire (see Context).
- **`default` space:**
  - set global flags to `baseline_flags()`. For workshop flags this equals `clean`, and it also restores `NEW_CART_UI`, `MOBILE_UI_V1` and `SEARCH_V2`, which the admin API can toggle;
  - delete carts whose key contains no `:`;
  - delete runtime orders with `space = 'default'`.

After the commit, `invoice_<order_number>.pdf` and `summary_<order_number>.pdf` of the deleted orders are removed from `pdf_output_dir`; missing files are ignored. Seeded orders (`space IS NULL`), products and users are never touched, and no seeder runs. After `reproducible-image`, seeding is global and insert-only: it cannot remove a space's flags, carts or orders, and it cannot restore changed global flag values, because `seed_feature_flags` keeps existing rows. Reset therefore does its own scoped deletes and flag restore. The response contains the space, counts of removed flags, cart items and orders, and the resulting stage, bugs and AI mode.

*Alternatives considered:*
- **Re-running seeding:** insert-only and global, it removes nothing a space created and leaves changed flag values in place (before `reproducible-image` it also rewrote seeded order history for everyone).
- **Applying preset `clean` only:** leaves carts and orders behind.
- **Deleting a per-space database file:** rejected in D3.

### D8: Space indicator in the layout, outside drift

`base.html` renders `<p class="workshop-space" data-workshop-space="{{ request.state.workshop_space }}">Space: {{ request.state.workshop_space }}</p>` in the site header when the resolved space is not `default`, or when `settings.shared_mode` is on. Both names are readable from the layout without touching any route: every page route already passes `request` into its template context, and `request.state` is backed by `scope["state"]`, which D1's dependency writes, so no route has to pass the space; `settings`, which templates cannot see today, is registered once as a Jinja global in `_mount_static_and_templates` (`backend/app/main.py`), next to the existing `brand_name` global, and stays the module-level object, so `shared_mode` is read at render time and test monkeypatches apply (task 9.2). In shared mode in the `default` space, a sibling element follows it: `<p class="workshop-space-hint">Shared baseline. Use your own space: add ?space=&lt;github-handle&gt; to the URL or send the header X-Workshop-Space.</p>`. The hint is a sibling, not a child, so the `[data-workshop-space]` element and its `Space: <id>` text are identical in form in every space.

The reason for showing `default` in shared mode: agents and new browser contexts (an rf-mcp session or an ad-hoc Playwright context opened by a coding agent) carry no header or cookie, and agents are told not to call control endpoints. Without a visible indicator they would inspect the clean `default` page instead of the participant's drifted space and could propose wrong heals or report "cannot reproduce".

The elements are never produced by drift helpers or bug toggles. `drift-coverage` lists `[data-workshop-space]` and its text as stable in its drift contract. Each is styled by its own rule — one `.workshop-space` rule and one `.workshop-space-hint` rule, both required — using no selector other than those two and `[data-workshop-space]`, which are not drift-covered names. When `drift-coverage` moves the stylesheet to `backend/app/assets/styles.css` and generates per-stage variants, these rules move with it and stay unchanged in every variant. The page `<title>` is left unchanged because acceptance stories may assert it. Local mode in `default` shows no indicator, as today.

*Alternatives considered:*
- **Title suffix:** breaks title assertions and is invisible in page content.
- **Inside the "Workshop Mode Active" banner:** today it exists only on the home and product listing pages and only while locator or bug flags are active, and `drift-coverage` removes it (its Decision 3), because it changes visible text between stages and discloses active bugs.
- **Response header only:** humans and agents looking at the page cannot see it.
- **No indicator in `default` on the shared instance:** a context without the header silently shows the baseline.

### D9: SQLite concurrency and a single process

- **PRAGMAs:** a SQLAlchemy `connect` event on the sync engine runs `PRAGMA journal_mode=WAL`, `busy_timeout=5000` and `synchronous=NORMAL` for file databases. The data is disposable, so `NORMAL` is acceptable. If WAL cannot be enabled (the PRAGMA returns another mode), the shop logs a warning and continues.
- **Short transactions:** writes stay short. A preset is one commit (D4), not one per flag.
- **Connection pool:** `pool_size` and `max_overflow` are set explicitly. The defaults (5 + 10) are below the target of 40 spaces. The early load test tunes the values and the gating load test confirms them (D10).
- **One worker:** Coolify runs the image's default single uvicorn worker, and the runbook forbids `--workers` and `WEB_CONCURRENCY`.
- **Artificial delays:** they must use `asyncio.sleep` and must not hold a pooled connection. Flags come from a short-lived session (D4), and `drift-coverage` places the `BUG_SLOW_RESPONSE` delay before the route starts its database work.

*Alternatives considered:*
- **Multiple workers:** correct once the cache is gone, but adds cross-process writer contention on one SQLite file and is not what the load test validates.
- **PostgreSQL:** an extra Coolify service and a second database path that local images would not exercise.

### D10: Locust load test with leakage detection

- **Location and install:** `loadtest/locustfile.py` at the repository root. It is outside `backend/` and `tools/`, so it stays out of the image and pytest does not collect it. Locust lives in a separate uv dependency group, `loadtest`.
- **Simulated users:** each user takes the next space id `load-001`, `load-002`, … and its own `X-Session-ID`, and sends both on every request. Think time is short (0.5-2 s) to imitate test suites.
- **Known start state and expected flag map:** in `on_start`, each user reads `GET /api/workshop/presets` once, applies preset `clean` in its own space and starts an expected flag map from `clean`'s flags. It uses `clean` rather than reset, because reset returns 404 on the image from before spaces that the negative control runs against. After every preset switch that returns 2xx, the preset's flags (the `applied_flags` of the response, equal to the listing's `flags`) are merged into the map. Keys the preset does not set keep their values, because presets compose (`drift-coverage` Decision 12: `stage1` no longer turns off bugs, and `buggy` sets no locator flags). The expected `locator_stage` follows the server's order: `v4` if `LOCATOR_V4` is on, else `v3` if `LOCATOR_V3`, else `v2` if `LOCATOR_V2`, else `v1`.
- **Weighted flows:** home and product listing, the catalogue API (`GET /api/products/`, a plain JSON request with the user's space and session headers), product detail, add to cart through the API, cart page, checkout form submit (renders PDFs where the native PDF libraries are present), preset switches (`stage1`-`stage4`, `buggy`, `clean`, and `drift_and_bug` once present), and status checks. For `/` and `/products`, the user parses the returned HTML and fetches every same-origin `<link rel="stylesheet" href>`, `<script src>` and `<img src>`, as a browser would, with its space and session headers. These requests use fixed names `asset:stylesheet`, `asset:script` and `asset:image`, so the stylesheet URL is never hard-coded and a digest in it (`drift-coverage` serves `/assets/styles.<digest>.css`) does not create a new report row per stage.
- **Leakage checks:** a leak is recorded when any of these fails:
  - status `space` equals its own space;
  - `locator_stage` matches the stage derived from its expected flag map;
  - cart API items equal the items it added since its cart was last emptied. A form `POST /checkout` that returns 2xx (the same successful checkout from which the user takes the order id below) empties the very cart the adds filled, because `checkout_submit` calls `CartService.clear_cart()` after creating the order and the page and the cart API resolve the storage key from the same space and `X-Session-ID` (D3). The user therefore clears its expected items exactly when a checkout answers 2xx, and on any other flow it runs that clears the cart; a checkout that answers 400 (empty cart or a rejected order) leaves both the server cart and the expected items unchanged;
  - pages contain `data-workshop-space="<own id>"`;
  - its own latest order document answers 200 and the latest order document of another load space answers 404 (`leak:order`). After a successful form `POST /checkout`, the user takes the order id from the confirmation page's `/api/docs/orders/<id>/invoice.pdf` link (a link target, which drift never changes) and records it for itself and in a process-wide registry keyed by space. The order check requests both `invoice.pdf` documents with its own space header. Locust runs as one process (no `--processes` and no distributed workers), so all users share the registry. The check therefore needs a target where PDF rendering is available — the container image, and every deployment of it: outside the image `api/docs.py` answers 503 when the native libraries are missing (`reproducible-image` D8), which records both `leak:order` and a 5xx. Every run that can arm the check uses such a target: the early and gating runs against a deployment, and the container runs of tasks 13.2 and 13.3.

  Leaks are reported as Locust failures named `leak:<check>`: `leak:space`, `leak:stage`, `leak:cart`, `leak:indicator` and `leak:order`.
- **Excluding planted delays:** requests to `/products` and `GET /api/products/` are reported under names with the suffix `[slow-bug]` exactly when `BUG_SLOW_RESPONSE` is on in the user's expected flag map. The name is chosen before the request is sent. These requests are excluded from p95 but still count for 5xx and leak checks.
- **Pass/fail:** a `quitting` hook sets a non-zero exit code unless p95 of HTML and API requests (excluding `[slow-bug]`) is below 1000 ms, there are zero 5xx responses, zero `leak:` failures and zero failed `asset:` requests.
- **Run parameters:** headless, target users (registered participants × 1.25, default 40), at least 10 minutes, with CSV and HTML reports kept as evidence, from outside the host network, against a Coolify deployment in shared mode. A redeploy afterwards removes the `load-*` spaces. There are two kinds of run:
  - **Early run:** on the candidate image of this change's merge commit, deployed by digest (D11). It tunes the pool and rehearses the procedure. It is not capacity evidence. Before `drift-coverage`, `BUG_SLOW_RESPONSE` adds no delay, so this run only checks the `[slow-bug]` naming.
  - **Gating run:** on the candidate image of the release-candidate commit, deployed by digest (D11), after `drift-coverage` and `acceptance-conformance` have merged. It is the capacity evidence, it drives the scale-out decision, and it verifies that `[slow-bug]` requests really take at least 1 s (`drift-coverage` applies a 1-3 s delay). If the `workshop-<id>` tag later points at application code that differs from the tested commit, the gating run is repeated on the tag.

*Alternatives considered:*
- **k6:** a JavaScript toolchain next to a Python repository.
- **Ad-hoc asyncio or pytest scripts:** no percentiles or reports.
- **Robot Framework-based load:** heavy, and puts RF suites into the shop repository, which `acceptance-conformance` avoids so the repository does not publish ready-made lab solutions.
- **Only the early candidate run:** it measures a build without `drift-coverage` and `acceptance-conformance`, which add per-request work and the real planted delay.

### D11: Coolify operated by published image (digest or version tag), with a runbook

`docs/COOLIFY-RUNBOOK.md` covers:

- **Application setup:** a Docker-image application from `ghcr.io/manykarim/demo-webshop` (never built from the repository), port 9090, health check on `/health`. The image reference follows `reproducible-image` D7, where `build` pushes an untagged candidate by digest and `publish` tags it only after every required verification passed:
  - a **candidate** is deployed by digest (`ghcr.io/manykarim/demo-webshop@sha256:…`), taken from the `digest` output of the `build` job in the step summary of the candidate commit's `main` run, and only when that run's `publish` job succeeded. Candidates are never deployed by `edge`, which moves with every push to `main`, or by `sha-<short>`, which a later build of the same commit can re-point; either would change what a redeploy or rollback pulls;
  - the **workshop** is deployed by its `workshop-<id>` tag, and a **rollback** target by its `X.Y.Z` or `workshop-<id>` tag or a recorded digest.
- **Environment:** `WORKSHOP_SHARED_MODE=true`, `WORKSHOP_ADMIN_TOKEN` as a secret (for example `openssl rand -hex 32`) and `WORKSHOP_AI_PROVIDER=mock`. Never set:
  - `WORKSHOP_DATABASE_URL` and `WORKSHOP_PDF_OUTPUT_DIR`: the image defaults `/data/workshop.db` and `/data/pdfs` (`reproducible-image` D3) are the only locations uid 1000 can write, and they are outside the `/static` mount. A copied `.env.example` value such as `./workshop.db` resolves to the root-owned `/app`, and the entrypoint refuses to start. A PDF directory below `backend/app/static` would expose order PDFs through `/static`.
  - `WORKSHOP_FLAG_*`: an environment override would freeze that flag for every space.
  - `WORKSHOP_APP_VERSION`, `WEB_CONCURRENCY` and `--workers`.
- **Storage:** no persistent volume or storage on `/data`, so a redeploy is a full reset. The rehearsal checks that the action used really recreates the container (a runtime order must be gone afterwards).
- **The `default` space rule:** never change the `default` space on the shared instance. Other spaces are unaffected by design (D4), but it is what participants and agents without a header or cookie see. Facilitator demos run in a facilitator space (`?space=<facilitator-handle>`). The token is used only for the rehearsal's 401 checks and to restore `default` with reset if it was changed by mistake.
- **Procedures:**
  - deploy and verify:
    - for `X.Y.Z` and `workshop-<id>` tags, `/health` `version` equals the tag;
    - for a candidate deployed by digest, `/health` reports `dev` (`reproducible-image` spec, scenario *Image without a version tag*), so the build is identified by the running image digest, which must equal the recorded `build` digest, and by the `org.opencontainers.image.revision` label, which must equal the candidate commit;
    - neither `WORKSHOP_DATABASE_URL` nor `WORKSHOP_PDF_OUTPUT_DIR` is set in the Coolify environment;
    - a preset without a space returns 401, and a preset in a test space works;
    - the indicator is visible in the test space, and a page without a space shows `Space: default` with the hint;
    - status without a space reports `v1` and no active bugs;
    - after an API checkout in the test space, that order's `invoice.pdf` returns 200 (the PDF directory is writable);
  - roll back by redeploying the previous version tag or a recorded digest, checked by version or digest in the same way, never by `sha-<short>`;
  - reset one space with `curl -X POST …/api/workshop/reset -H 'X-Workshop-Space: <handle>'`;
  - reset everything by redeploying;
  - scale out if the gating load test of one instance fails: N instances, each in shared mode, with participants split by the first character of their handle so that each of `a`-`z` and `0`-`9` is assigned to exactly one instance, the registered count per instance, and a published URL table. Each instance must pass the load test with its share × 1.25 users, all instances at the same time when they share a Coolify host. A `leak:` failure or a 5xx at any share is a defect, not a reason to scale out further.
- **Capacity and rehearsal records:** one row per load-test run with kind (early or gating), image reference (digest, or tag when deployed by tag), commit (revision label), digest, whether `drift_and_bug` is listed, users, duration, p95 excluding `[slow-bug]`, 5xx count and leak count. A failed single-instance run keeps its row when the deployment is scaled out.
- **Checklists:**
  - After this change merges: deploy the merge commit's candidate by digest (`dev`, matching digest and revision label), run the early load test and tune the pool, rehearse redeploy, rollback and reset.
  - T-1 week, after `drift-coverage` and `acceptance-conformance` have merged: deploy the release-candidate commit's candidate by digest, run the gating load test, decide on scale-out, and commit any tuning before tagging (a new commit needs a new gating run).
  - T-1 day: deploy the final `workshop-<id>` tag, check the version and that the tag's revision equals the load-tested commit (or that no application file differs; otherwise re-run the gating load test on the tag and record it), smoke-test with two spaces and the default-space indicator, redeploy to wipe, publish the URL.
  - Day of: fresh redeploy, health and version check, status without a space reports `v1`, watch logs for 5xx, keep the token with facilitators only.

*Alternatives considered:*
- **Coolify building from the repository:** not reproducible, and replaced by `reproducible-image`.
- **A persistent volume:** state across redeploys is not wanted, and it would make "reset all" a manual database operation.
- **Deploying candidates by `sha-<short>`:** simpler to type, but `reproducible-image` D7 makes it a moving per-commit pointer, so a record or rollback could silently name another build.

### D12: Tests reuse the shared harness and live in their own suite directory

`reproducible-image` D11 owns the pytest harness, and this change follows its rules:

- **Environment:** the only change to the root harness is two entries in the declarations of `backend/tests/harness.py`: `WORKSHOP_ADMIN_TOKEN` is added to `SCRUBBED_ENV_VARS` and `"WORKSHOP_SHARED_MODE": "false"` to `PINNED_ENV_VARS`. `pin_test_environment` applies them from the root `backend/tests/conftest.py` before any app import, so a developer's `.env` can neither turn on shared mode nor make the import fail (process environment variables win over `.env`). `WORKSHOP_FLAG_*` is already scrubbed there. No workshop-spaces conftest sets environment variables, resets the engine globals or defines a fixture with a canonical name.
- **Fixtures reused by exact name:** `app_client` (products and flags), `seeded_app_client` (full seeding with the demo users `jamie@flowlinesupply.com` and `alex.productlead@example.com` and their order history), `temp_database` (patched settings and engine globals without a client, for schema and concurrency tests), and `fake_weasyprint` (PDF files exist for reset and document tests without native libraries).
- **Suite directory:** integration tests go to `backend/tests/spaces/` (new, with `__init__.py`). Its `conftest.py` provides only the suite fixture `shared_mode` (monkeypatches `settings.shared_mode` to true and `settings.admin_token` to a known token, and yields the token). `backend/tests/spaces/helpers.py` provides the plain functions `sqlite_rows(sql, params=())`, which reads the database file that `settings.database_url` points to at call time with stdlib `sqlite3`, and `rendered_stage(html)`. Unit tests that need no harness fixture (`test_spaces.py`, `test_settings_shared_mode.py`, `test_flag_seam.py`) stay in `backend/tests/unit/`.
- **Admin token from `.env`:** scrubbing removes the token only from the process environment, so `settings.admin_token` may still come from a local `.env`. It has no effect, because the write guard ignores the token while shared mode is off, and every shared-mode test sets both values through `shared_mode`.

*Alternatives considered:*
- **Module-top `os.environ` code and an autouse settings fixture in a suite conftest:** duplicates the root harness, and the result depends on which conftest pytest imports first.
- **Suite fixtures in `backend/tests/integration/conftest.py`:** that directory also holds `reproducible-image`'s harness tests, so its conftest would not belong to one suite.

## Risks / Trade-offs

- **SQLite lock contention** during concurrent checkouts and preset switches → WAL, `busy_timeout`, one commit per operation, and writes included in the load test. Contingency: N independent instances (D11).
- **Connection pool exhaustion** by artificial delays (`AI_RANDOM_DELAYS`, `BUG_SLOW_RESPONSE`) holding pooled connections → flags come from short-lived sessions, delays run without an open transaction, the pool is sized explicitly, and the load test includes the `buggy` preset.
- **Event loop saturation** on a single worker from CPU work: WeasyPrint rendering in a thread still competes for the GIL, and Jinja rendering and the per-request RAG index build in `AIService` run in the loop → the load test includes checkout submits with PDF generation. Contingency: scale out. Measured during task 10.2 on an 8-core host: 40 *simultaneous* checkouts with real WeasyPrint saturated the CPU, starved the event loop and produced `database is locked` for 18 of 40 spaces at the first write, while 40-way preset-only concurrency stayed clean (max 0.57 s). The concurrency test therefore fakes rendering; the gating capacity test (14.4) uses realistic think times and must watch checkout latency and 5xx specifically.
- **Capacity measured on a different build than the one used on the day** → the capacity evidence comes from the gating run on the release-candidate commit, and the T-1 day checklist compares the tag's revision with it or re-runs the test.
- **Participants forget the header** → writes to control endpoints get a 401 that explains `?space=` and the header. Reads land in `default`; in shared mode every page shows `Space: default` with the hint, so a person or an agent's own browser context can see it, and status reports `"space": "default"`. The workshop repository's `coolify` profile sets the header in one place, and its agent configurations should open `?space=<handle>` or send the header (handoff note, outside this change).
- **A facilitator changes the `default` space on the shared instance** → participant spaces are unaffected (D4 baseline), but people without a header see the change. The runbook forbids it; reset in `default` with the token restores it.
- **Browser `extraHTTPHeaders` sends `X-Workshop-Space` to every origin** the context contacts → the shop loads no third-party resources (verified), so the header leaves the shop only if a test navigates to an external footer link. The value is a public handle. Mention this in workshop material.
- **Cookie and header confusion** → the header always wins, including over `?space=`, in which case no cookie is set, and the indicator shows the effective space. A `?space=` visit persists in that browser for 30 days, and `?space=default` switches back. The sign-in snapshot in `localStorage` (`flowline_auth_state` in `app.js`) is per origin, not per space, so participants should sign in again after switching spaces.
- **Anyone can act in any space by sending its handle** → accepted. Spaces protect against accidents, not adversaries. The token protects only the shared baseline, and a redeploy restores everything.
- **GitHub handles stored in the database and in access logs** (query parameter) → no endpoint lists spaces, there is no volume, a redeploy wipes the data, and the runbook says not to export logs.
- **Legacy GitHub handles with double or trailing hyphens, or the handle `default`** → rejected or reserved. Those participants use a variant such as `<handle>-ws`, noted in the participant instructions.
- **Invoice PDFs under `/static/pdfs/` in runs that keep the default `pdf_output_dir`** → local, non-container runs write to `backend/app/static/pdfs`, which the `/static` mount serves as `invoice_<order_number>.pdf` for any space. Accepted: those runs are single-user local mode, and order numbers are `ORD-` plus 8 random hex digits. The published image, and so the shared Coolify instance, writes to `/data/pdfs` (`reproducible-image` D3, a maintainer decision), where runtime PDFs are served only through `/api/docs/orders/{id}/invoice.pdf` and `/summary.pdf`, which D5 scopes. The runbook forbids pointing `WORKSHOP_PDF_OUTPUT_DIR` below `backend/app/static` (D11).
- **A default-space session id containing `:` looks like a space key** → browser session ids are UUIDs, so only hand-crafted headers are affected. Accepted; the only effect is that a default-space reset skips such carts. The cart API still reports the id unchanged, because the label is not derived from the key (D3).
- **The indicator appears in non-default spaces, and in shared mode on every page**, so screenshots differ between the `local` and `coolify` profiles → visual checks mask `[data-workshop-space]` and `.workshop-space-hint`, or keep baselines per profile.
- **Shared-mode validation runs at import time**, so a shell or `.env` with `WORKSHOP_SHARED_MODE=true` and no token also breaks seeding and tests → the error names the missing variable. Tests are protected by the shared harness: `PINNED_ENV_VARS` in `backend/tests/harness.py` pins `WORKSHOP_SHARED_MODE=false` and `SCRUBBED_ENV_VARS` removes `WORKSHOP_ADMIN_TOKEN` from the process environment before any app import (D12), and process environment variables win over `.env`.
- **Removing the cache adds reads per request** → one small indexed query. The load test covers it.
- **A load test with idealized traffic is not representative** → static assets parsed from real pages, short think times, write flows, 1.25 × registered participants and the gating run on the release build.
- **`drift-coverage` rebases onto this change and moves the stylesheet, hides the workshop and admin routers from `/openapi.json`, and narrows the page template context** → tests here avoid those dependencies, so `drift-coverage` runs `backend/tests/spaces/` unchanged after its rebase: static checks use `/static/app.js` and the linked stylesheet, the no-enumeration test lists routes from `app.routes`, the load test reads asset URLs from pages, and flag seam checks use `NEW_CART_UI` in the template context and `rendered_stage()` for drift. `rendered_stage()` (`backend/tests/spaces/helpers.py`) changes only if `drift-coverage` renames the card blocks `item-card` or `product-tile` in its `StageSpec` tables. Mounted asset routes such as `/assets` never run the space dependency (D1).

## Migration Plan

1. **Prerequisite:** `reproducible-image` is merged (uv `[dependency-groups]`, `uv.lock`, `WORKSHOP_APP_VERSION`, insert-if-missing seeding at container start, `/data` in the image, the shared pytest harness, and the `image.yml` job graph in which `publish` tags a candidate only after verification). It may still be active as an OpenSpec change until its task 10.6; nothing here depends on its archive.
2. **Develop in parallel with `drift-coverage`; merge this change first.** Both start after `reproducible-image`. `drift-coverage` codes against the `get_effective_flags` seam, then rebases onto this change (`drift-coverage` task 15.1) and keeps the stable `[data-workshop-space]` element.
3. **Schema:** applied automatically at start. Fresh containers get `space_feature_flags` and `orders.space` from `create_all`. Persisted local databases get the `ALTER`, the index and the `default` backfill from `init_db()` on every start. No manual steps.
4. **Configuration and docs:** new settings default to off (local mode unchanged). Update `.env.example` (remove the cache setting, document shared-mode variables). Add a `## Workshop spaces` section to `docs/WORKSHOP-FEATURES.md` (header, query and cookie precedence, baseline for non-default spaces, reset, shared-mode 401, indicator and hint). Add the runbook and the `loadtest` group.
5. **Early candidate check, after this change merges:** once the merge commit's `main` run has published, deploy its candidate by digest on Coolify in shared mode (`/health` reports `dev`; the running digest equals the `build` digest and the revision label equals the merge commit), run the early load test to tune the pool, rehearse the runbook procedures, then redeploy. This is not capacity evidence.
6. **Gating capacity test, T-1 week:** after `drift-coverage` and `acceptance-conformance` have merged and `main` is green, deploy the release-candidate commit's candidate by digest, run the gating load test, decide on scale-out, and record commit and digest.
7. **Workshop tag:** tag `workshop-<id>` on the tested commit, deploy it on Coolify per the T-1 day checklist (revision check or re-run), and the workshop repository pins the same tag.
8. **Archive:** after the workshop day checklist (task 15.3), archive this change on `main` with `openspec archive workshop-spaces -y`, which creates `openspec/specs/workshop-spaces/spec.md`. No other change modifies the `workshop-spaces` capability and no sibling waits on this archive, so keeping the change active until then blocks nothing: `drift-coverage` is archived right after it merges (its task 17.3), `reproducible-image` in its task 10.6 and `acceptance-conformance` in its task 18.5, and `acceptance-conformance` correctly states that this archive is not a prerequisite there.
9. **Rollback:**
   - *Coolify:* redeploy the previous version tag or recorded digest, never `sha-<short>`. All state is wiped anyway; participants re-apply presets.
   - *Persisted local databases:* the schema additions (one table, one nullable column, one index) are ignored by older images, because the ORM selects explicit columns. Orders created by an older image have no user and no space; the next start of a spaces image backfills them to `default` (D3), so they stay scoped and resettable.

## Open Questions

- Registered participant count. It sets the load-test user count (registered × 1.25; default 40), the scale-out decision and, if the deployment is split, each instance's target. It does not change the design.
- Coolify hostname(s). They fill the runbook placeholders and the workshop repository's `coolify` profile URL.
