## Why

The workshop's self-healing module depends on two things the shop only half provides. First, UI drift must hit the elements tests actually use: today only the home page, product listing and product card drift, while the navigation (cart badge), sign-in modal, product detail, cart, checkout form and chat widget never change, even though the documentation claims they do (e.g. `auth-email` → `login-email`). Existing workshop tests locate exactly those unchanged elements. Second, healing must be judged against defects it must *not* hide, but the checkout flow has no planted bug, and the drift itself has no written contract of what stays stable, so there is no objective way to tell a legitimate heal from a masked regression. Drift today also has side effects of its own. Stage 2 and stage 4 cards render unstyled because the stylesheet has no rules for the drifted class names, and in stages 3 and 4 add-to-cart analytics reports `source: "cta"` for card buttons because the script looks for `[data-test='product-card']`. Extending drift to the navigation, sign-in modal and checkout would break the client script outright, because it binds to `#auth-email`, `.checkout-form`, `#checkout-*` and `.site-nav`.

## What Changes

- Locator drift covers every element used by the workshop flows: navigation incl. cart badge, sign-in modal, product listing and cards, product detail, cart, checkout form and summary, chat widget.
- A written **drift contract** per stage defines what changes (ids, classes, `data-test` attributes, structure of product cards, product detail purchase actions and checkout form fields) and what stays stable (visible text, roles, accessible names, labels, form field names, link targets), verified by automated tests.
- Stage precedence is consistent across all pages (stage 4 over 3 over 2).
- The shop's client-side script binds only to stable semantic hooks (ARIA roles and relationships, form field names, link targets, content data attributes such as `data-product`), so its behavior keeps working in every stage. The behavior-only `data-*` markers (`data-cart-count`, `data-auth-*`, `data-chat-*` except the content attribute `data-chat-prompt`, `data-search-*`, `data-nav-*`, `data-theme-*`, `data-icon-*`, `data-filter-form`, `data-price-*`, `data-event`, `data-product-id`, `data-product-wrapper`) are removed in every stage, stage 1 included, and the script no longer writes marker attributes or ids at runtime. **BREAKING** for suites and facilitator material that locate elements by those markers (RBCN-era material).
- The stylesheet follows the drift: it is served per stage at a hidden `/assets/styles.<digest>.css`, and `/static/styles.css` is removed (404). **BREAKING** for anything that links or fetches the old URL.
- The "Workshop Mode Active" banner is removed from the home and listing pages. **BREAKING** for facilitator material that reads it; `/api/workshop/status` reports the stage and bugs instead.
- Search-result cards are rendered on the server through a hidden `/search/results` fragment with the product-card markup, so drift and bugs apply to them; the extra icon-only add-to-cart button goes away. Other markup the script builds (suggestions, chat messages, account menu) is cloned from server-rendered `<template>` elements.
- The add-to-cart confirmation names the product.
- The checkout summary shows the tax amount and a total that equals what the created order charges. Today it shows "Estimated tax: Calculated after address" and a total without tax, while the order adds 7% tax, so the clean state already disagrees with the invoice.
- New planted bug `BUG_CHECKOUT_TOTAL`: the checkout summary shows a total that does not equal subtotal plus tax, while the created order and invoice stay correct.
- A registry of planted bugs with deterministic triggers. Existing bugs keep their flags, triggers and observable defects (same product ids, ×1.15 card price, `/products/invalid-<id>` link, missing button). Markers that reveal a defect as deliberate, such as the "Button unavailable" placeholder, are removed. `BUG_SLOW_RESPONSE` is seeded and part of the `buggy` preset but currently has no effect anywhere; it gets a defined scope (product listing page and product list API).
- Presets own flag groups: `stage1`–`stage4` set only locator flags, so `stage1` no longer turns off bugs. Stage 1 is the absence of locator flags (there is no `LOCATOR_V1`), so `stage1` and `clean` both reset the stage, but only `clean` also clears the planted bugs. **BREAKING** for facilitator material that uses `stage1` as a full reset; `clean` is that reset.
- New preset `drift_and_bug` combining stage 4 with bugs in the same flows, for heal-vs-hide exercises; `clean` and `buggy` include the new bug flag.
- Workshop control endpoints are no longer advertised in `/openapi.json`, `/docs` or `/redoc`, so agents browsing the published API schema do not find them. They stay callable, and their responses remain readable without credentials and name the active stage and bugs by flag key: they are unadvertised, not secret. **BREAKING** for anyone relying on `/docs` to find them.
- A new `test` job in the image workflow runs the unit and contract tests and the browser smoke test per stage against the untagged candidate digest that `build` pushed. `publish` needs it, so a candidate that fails gets no tag at all, not even `sha-<short>`. On pull requests the browser smoke runs inside `build` against the locally loaded image.
- `docs/WORKSHOP-FEATURES.md` is corrected to match the implemented mapping.

## Capabilities

### New Capabilities
- `locator-drift`: Drift stages, presets that select them, coverage of workshop flows, the per-stage stability contract, stage precedence, determinism, and the guarantee that the shop's own behavior survives drift.
- `planted-bugs`: Registered, deterministic, flag-controlled defects per workshop flow (including the new checkout total bug), their combination with drift stages, and non-disclosure through the published API schema.

### Modified Capabilities
<!-- None: no specs exist yet in this repository. -->

## Impact

- **Code**:
  - `core/workshop.py`: single mapping, stage precedence, bug registry, preset builder, `planted_delay`, stylesheet variants.
  - `core/feature_flags.py`: interim `get_effective_flags` seam, replaced by the space-aware one from `workshop-spaces`. After the rebase, `workshop-spaces`' `baseline_flags()` takes preset `clean` from `build_presets()`.
  - `main.py`: Jinja globals `drift` and `bugs`, the `workshop_view` dependency on page routes, the checkout summary on `GET` and `POST /checkout`, `planted_delay` on `GET /products`, the hidden `/search/results` route, the `/assets` stylesheet mount, and `include_in_schema=False` for the `workshop` and `admin` routers in `configure_routes()`.
  - `api/workshop.py`: presets from the preset builder, status stage and bugs from the registry.
  - `api/products.py`: `planted_delay` on `GET /api/products/`.
  - `seeds/seed_data.py`: bug flag rows generated from the registry, adding `BUG_CHECKOUT_TOTAL`.
  - Templates under `backend/app/templates/` (`base.html`, `home.html`, `products.html`, `components/product_card.html`, new `components/search_results.html`, `product_detail.html`, `cart.html`, `checkout.html`).
  - `static/app.js`: stable behavior hooks, no runtime markers.
  - `static/styles.css` moves to `assets/styles.css` and is served as per-stage variants.
  - `services/order_service.py`: checkout summary with tax.
  - `backend/tests/`: unit tests, the contract suite (`backend/tests/contract/`) and the browser smoke suite (`backend/tests/browser/`). Both suites build on the shared harness from `reproducible-image` and reuse its fixtures by name, without a second root conftest.
- **Dependencies**: the uv `dev` group gains `pytest-playwright` (browser smoke, reused by `acceptance-conformance`) and `beautifulsoup4` (HTML parsing for contract tests); `uv.lock` is regenerated. `pyproject.toml` gains `[tool.pytest.ini_options]`, which registers a `browser` marker that is deselected by default (`acceptance-conformance` later extends the same `addopts` with its `conformance` marker). Suites that need a running target take it from the `--base-url` option.
- **Build/CI**: `.github/workflows/image.yml` (created by `reproducible-image`) runs the unit and contract tests in `check` and the browser smoke inside `build` on pull requests. It gains a `test` job, owned by this change, that verifies the untagged candidate digest on every other event. `publish` needs `test` before it creates any tag.
- **Docs**: `docs/WORKSHOP-FEATURES.md`. This change owns the document's structure and keeps the `## Workshop spaces` section from `workshop-spaces` verbatim.
- **Downstream**: workshop Modules 7 (filing planted bugs) and 8 (healing) rely on the contract and presets; facilitator material in the workshop repository references the preset names and receives a migration notice for the BREAKING items above.
- **Order**: requires `reproducible-image` to be merged (it may still be an active OpenSpec change until its task 10.6). `workshop-spaces` and `drift-coverage` are developed in parallel after `reproducible-image`, and `workshop-spaces` merges first. This change codes against the `get_effective_flags` seam and rebases onto it (task 15.1), resolving the expected conflicts listed in design Decision 15. It is archived right after merging, so `openspec/specs/planted-bugs` exists before `acceptance-conformance` writes a delta against it. `acceptance-conformance` runs after this change because it changes the rendered UI.
