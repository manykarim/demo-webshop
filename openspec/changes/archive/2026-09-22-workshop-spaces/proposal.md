## Why

Participants run the shop locally, but anyone whose laptop cannot run containers falls back to one shared, self-hosted instance on Coolify. On a shared instance all workshop state is global: one participant applying the `stage2` preset breaks every other participant's tests, API calls without a session header share a single cart, orders from all participants accumulate in the same history, and the control endpoints are unauthenticated. The fallback is only usable if each participant's workshop state is isolated.

## What Changes

- Introduce **workshop spaces**: a per-participant namespace for feature flags, carts and orders, selected by request header (tests), query parameter or cookie (humans), with a `default` space when none is given.
- Space identifiers use the GitHub handle format; participants use their own GitHub handle, which is unique and needs no assignment step.
- Presets, bulk flag updates and a new reset operation act on the caller's space only. Effective flags resolve in this order: environment override, then the space value (non-default spaces), then the baseline (non-default spaces: seeded defaults with preset `clean` applied) or the global value (`default` space). Changes to `default` therefore never leak into participant spaces.
- Flag changes are visible to the very next request in that space (no stale cache window).
- Runtime orders and carts are visible only within their space; seeded demo order history stays visible in every space. Cart API callers without a session id get the same fallback session name, `workshop-demo`, in every space.
- A **shared mode** for the hosted instance: workshop control operations (presets, flag updates, reset) on the global/default space require an admin token, while shopping in `default` (cart, checkout) stays open; the AI helper is forced to its mock provider; and no endpoint lists existing spaces.
- Pages show the active space when it is not `default`, and always on the shared instance, where the `default` space also shows how to select a personal space.
- Local mode without a space behaves exactly as today.
- Operational work for the fallback: Coolify deployment of the published image in shared mode (candidates by digest, the workshop by its `workshop-<id>` tag), a load test that proves capacity on the release build (per instance if participants are split) and detects cross-space leaks of flags, carts, orders and the indicator, and a runbook (redeploy, rollback, reset, scale-out).

## Capabilities

### New Capabilities
- `workshop-spaces`: Resolution, validation and isolation of per-participant workshop state (flags, carts, orders), space reset, shared-mode protections, and the capacity target for the shared fallback deployment.

### Modified Capabilities
<!-- None: no specs exist yet in this repository. -->

## Impact

- **Code**: request-scoped space resolution (new dependency/middleware), `core/feature_flags.py` (space-aware resolution with a clean baseline for non-default spaces, cache removal), `api/workshop.py` and `api/admin.py` (scoping, token checks, reset), `services/cart_service.py` (caller-facing session label), `api/cart.py`, `api/checkout.py`, `main.py` (cart keys, plus `settings` registered as a Jinja global so the layout can read `shared_mode`), `models/cart.py` (`session_key` declared as `String(128)`), `services/order_service.py` (`space` keyword on `create_order`, the `order_visible_in` predicate), `models/order.py` and the `ensure_*` schema helpers, which move from `seeds/seed_data.py` into `core/db.py:init_db()` (order `space` column), `models/feature_flag.py` (space flags table), `api/auth.py` (order history filtering), `api/docs.py` (order documents respect space visibility), `api/search.py` and `api/ai.py` (space-aware flag reads), `services/ai_service.py` (shared-mode mock), `core/config.py` (shared-mode settings), `core/db.py` (SQLite WAL/busy timeout, schema upgrade at start-up), `templates/base.html` and `static/styles.css` (space indicator and shared-mode hint).
- **Config**: new `WORKSHOP_SHARED_MODE`, `WORKSHOP_ADMIN_TOKEN`; `WORKSHOP_FEATURE_FLAG_CACHE_SECONDS` becomes obsolete (`.env.example`, `cachetools` dependency removed).
- **Tests**: new suite directory `backend/tests/spaces/` (its own `conftest.py` and `helpers.py`) on top of the shared harness from `reproducible-image`, whose only change here is two entries in the environment declarations of `backend/tests/harness.py` (`WORKSHOP_ADMIN_TOKEN` scrubbed, `WORKSHOP_SHARED_MODE=false` pinned); unit tests in `backend/tests/unit/`.
- **Operations**: Coolify application settings, load-test tooling (separate `loadtest` dependency group, `loadtest/`, which is added to `.dockerignore`), runbook document `docs/COOLIFY-RUNBOOK.md`, `## Workshop spaces` section in `docs/WORKSHOP-FEATURES.md`.
- **Downstream**: the workshop repository's Robot Framework profiles send the space header for the Coolify profile, and its agent configurations open `?space=<handle>` or send the header.
- **Order**: requires `reproducible-image` (tagged image, version reporting, insert-if-missing seeding, shared test harness). Developed in parallel with `drift-coverage`, which codes against the `get_effective_flags` seam. This change merges first, and `drift-coverage` then rebases onto it. Drift and bug flags become space-aware through this change. It is archived after its workshop-day checklist (task 15.3); no sibling depends on that archive.
