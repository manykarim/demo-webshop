## Context

See `proposal.md` (Why) for motivation. Requirements are in `specs/locator-drift/spec.md` and `specs/planted-bugs/spec.md`. This section covers only the current state that shapes the approach. All of it was checked against the code on branch `openspec/workshop-plan`. Where the prerequisite `reproducible-image` changes a fact, the state after that change is stated too, because it is this change's base (task 1.1).

**How drift works today**
- Drift is written inline in three templates. `templates/components/product_card.html` checks `LOCATOR_V2` before `LOCATOR_V4`, so stage 2 class names win when both flags are on. `home.html` and `products.html` show a "Workshop Mode Active" banner that names the active locator stage and bugs.
- `core/workshop.py` defines `LOCATOR_STAGES`, `ID_TRANSFORMS`, `get_class_name`, `get_element_id`, `get_data_test_attr` and the `apply_bug_*` helpers. Only `backend/tests/unit/test_workshop.py` uses them. No template or route does, so `auth-email → login-email` (documented in `docs/WORKSHOP-FEATURES.md`) is never rendered.
- Flags are passed into the card macro as a parameter (`feature_flags=`). `product_detail.html` (lines 92 and 106) calls `cards.product_card(...)` without that parameter, so related and trending cards never drift and never show bugs. Passing flags as a parameter is therefore a failure mode we have already seen, not a theoretical one.
- `base.html` (navigation, cart badge, sign-in modal, account menu, chat widget), `product_detail.html`, `cart.html` and `checkout.html` never drift.

**Client script and stylesheet**
- `static/app.js` finds elements in two ways:
  - Behavior-only `data-*` markers that never drift: `[data-cart-count]`, `[data-auth-*]`, `[data-chat-*]`, `[data-search-*]`, `[data-nav-*]`, `[data-theme-*]`, `[data-filter-form]`, `[data-price-slider]`, `[data-price-output]`.
  - Selectors that do or should drift: `[data-test='product-card']`, `.product-card__title a`, `#auth-email`, `.checkout-form`, `#checkout-email|name|address|team-size`, `.site-nav`, `#flash-message`.
  - `setupTypeahead` also looks up `.form-field`, a shared styling block on the field labels of the search boxes, newsletter, sign-in modal and checkout. It is not a covered hook (Decision 3).
- `app.js` also writes markers into the live DOM at runtime, in every stage: `dataset.mobileNavBound`, `dataset.chatBound`, `dataset.themeBound` and `dataset.chatPromptBound` as idempotency guards, `dataset.index` on suggestion options, and a fallback `widget.id = "chat-widget"` that feeds the launcher's `aria-controls`.
- `app.js` builds markup itself with hard-coded class names and `data-test`: search-result cards (`renderProductCards`), typeahead suggestions, chat messages and account-menu lists. It gives the suggestion listbox a random id (`uniqueId`). Suggestions highlight the query with `<mark>` through `innerHTML` (`highlightMatch`), which `docs/test-prompts/homepage-and-search.md` expects.
- The add-to-cart confirmation reads "Item added to cart." and does not name the product. `showFlash` finds the region by `#flash-message` and overwrites its whole `className` (`flash is-visible <variant>`, then `flash`).
- The sign-in overlay `div.auth-modal[data-auth-modal]` carries `hidden` and receives the backdrop click (`event.target.matches("[data-auth-modal]")`). The inner `role="dialog"` element has no id. The chat Escape handler also checks `[data-auth-modal]`.
- The price filter's two range inputs have no `name`, id or accessible name, and the two `<output>` elements have no `for`. Only the hidden inputs carry `name="price_min"` and `name="price_max"`. The script finds all of them through `data-price-slider` and `data-price-output`.
- `static/styles.css` uses universal (`*`, `*::before`, `*::after`), element (`body`, `a`, `h4`, `h5`, `input[type="range"]`, `:focus-visible` on `a`, `button`, `input` and `textarea`), element-plus-class (`body.theme-dark`, `body.site-nav-open`, `body.has-chat-open`), class and attribute selectors. It has no id selectors, one child combinator (`.site-nav__items>*`, inside `@media (max-width: 600px)`) and `[data-search-form].is-loading`. Its only at-rules are `@media (max-width: 900px)` and `@media (max-width: 600px)`. It has no rules for the existing drift names (`item-card`, `product-tile`, `tile-content`), so stage 2 and stage 4 cards render unstyled today. `.badge` is `display:none` unless `.is-visible` is set.

**Planted bugs**
- All card bugs live in `product_card.html`.
- `BUG_SLOW_RESPONSE` is seeded and part of `buggy`, but no code applies it.
- When `BUG_MISSING_BUTTON` hides a button, the card renders `<span data-test="hidden-button-placeholder">Button unavailable</span>`. That tells anyone reading the DOM that the button was hidden on purpose, and stage 3 does not remove it.
- `BUG_BROKEN_LINKS` links to `/products/invalid-<id>`. The detail route declares `product_id: int` and there is no validation handler, so that URL answers with a JSON 422 (`int_parsing`), not 404. `acceptance-conformance` plans an HTML not-found page for such ids (WEB-003 AC-9).
- `api/workshop.py` hard-codes the list in `_get_active_bugs`. Preset `stage1` also turns off three of the four bugs.

**Checkout totals**
- `checkout.html` shows Subtotal = cart total, "Estimated tax: Calculated after address" and "Total due at payment" = subtotal.
- `services/order_service.py` `calculate_totals` (7% tax) sets the order's subtotal, tax and total, and the invoice and summary PDFs use those values.
- `POST /checkout` in `main.py` re-renders the template with `total` on error and `total: 0` on success. The success message contains the order number (`ORD-` plus 8 hex characters from `uuid4`) and links to `/api/docs/orders/<order id>/invoice.pdf` and `summary.pdf`.

**Flags and tests**
- Every page route calls `list_feature_flags(session)`, which goes through a per-process `TTLCache`. `workshop-spaces` replaces this with per-request resolution that takes effect on the next request. Its precedence (its D4) is: environment override, then the space value (non-default spaces), then the baseline (non-default spaces) or the global value (`default` space).
- On the current base there is no `conftest.py` and no `TestClient` test. `reproducible-image` adds the one shared test harness (its D11). This change reuses it by exact name and never duplicates it:
  - `backend/tests/harness.py` holds the scope-agnostic context manager `isolated_app(tmp_dir, *, seed_users=False)`. It patches `settings.database_url` to a SQLite file in `tmp_dir` and `settings.pdf_output_dir` to `tmp_dir/pdfs`, resets the engine globals in `core/db.py`, clears the flag cache on enter and exit while that cache exists, seeds products and flags (all of `seed_data.main()` with `seed_users=True`) and yields a `TestClient`. The module also declares the process environment (`SCRUBBED_ENV_VARS`, `SCRUBBED_ENV_PREFIXES` with `WORKSHOP_FLAG_`, `PINNED_ENV_VARS`), applied by `pin_test_environment`.
  - The root `backend/tests/conftest.py` pins that environment at module top, before any app import, and provides the function-scoped fixtures `temp_database`, `app_client`, `seeded_app_client`, `pdf_unavailable` and `fake_weasyprint`.
  - Later changes add only suite-specific conftest files in their own test subdirectories, build package- or session-scoped fixtures on `isolated_app` with `tmp_path_factory`, and never patch settings, reset engine globals or set environment variables of the pytest process themselves.
- `backend/tests`, `backend/tests/unit` and `backend/tests/integration` are packages (`__init__.py`), and `workshop-spaces` adds the package `backend/tests/spaces`. New test directories need an `__init__.py` too, to avoid module-name collisions such as two `test_harness.py`.
- `config.settings` is created at import time, and `db.async_engine` is created lazily from it and then kept for the process. Setting environment variables in a conftest only works if nothing collected earlier imported the app, which pytest's alphabetical collection does not guarantee.
- Generated order PDFs go to `settings.pdf_output_dir` (`WORKSHOP_PDF_OUTPUT_DIR`). In the image that is `/data/pdfs`, and the documents are served only through `/api/docs/orders/{id}/invoice.pdf` and `/summary.pdf`, never under `/static/pdfs/` (`reproducible-image` requirement "Order documents in the container"). In tests the root harness points the setting into a temporary directory.
- After `reproducible-image`, `workshop.db` and `*_ORD-*.pdf` are gitignored, so plain `git status` cannot show a test that writes generated files. Isolation is checked with the harness's marker-file and `find` check instead: `touch "$marker"` before the run, then `find . \( -path ./.venv -o -path ./.git \) -prune -o \( -name '*.db' -o -name '*_ORD-*.pdf' \) -newer "$marker" -print` prints nothing.
- `pdf_service.py` imports `weasyprint` at module top today, so creating an order in a test needs the native libraries. After `reproducible-image` the import is lazy: the harness fixture `fake_weasyprint` records the rendered HTML without native libraries, and `pdf_unavailable` simulates missing libraries.

**Seed idempotency (checked, as the brief asked)**
- `seed_products`: upserts by SKU, so it never duplicates. On a fresh database, ids follow fixture order: 3 = Pulse Bio Ring, 4 = Nimbus Desk Light, 5 = Atlas Standing Desk, 12 = Cascade Water Bottle. `reproducible-image` changes it to insert-missing only.
- `seed_feature_flags`: inserts only missing keys and never overwrites existing values. A new `BUG_CHECKOUT_TOTAL` row is added safely to existing databases.
- `seed_users`, before `reproducible-image`, was not safe to re-run: for existing users it deleted and recreated addresses, payment methods and orders, and it removed `billing_address_index` from the module-level fixtures with `pop`. `reproducible-image` (task 4.2) makes it insert-missing and PDF-free. The contract harness still seeds no users, because contract tests do not need them.

**Constraints**
- Participants' coding agents inspect the live page and not the source. No shop page, stylesheet, script or published API schema may reveal the mapping or the active bugs.
- The JSON of the control endpoints (`/api/workshop/status`, `/api/workshop/presets`, `POST /api/workshop/preset` and `/flags` responses, `/api/admin/flags`) is the deliberate exception. It names the active stage and bugs by flag key and is readable without credentials. This is accepted (see Risks).
- The public `demo-webshop` repository does reveal them. That is accepted.
- `workshop-spaces` merges first and owns flag resolution and the write path.
- `acceptance-conformance` follows and audits the final UI.

## Goals / Non-Goals

**Goals:**
- One source of truth in `core/workshop.py` for drift hooks, structural variants, stage precedence, the bug registry and preset contents. Templates, the stylesheet, the status endpoint, docs checks and tests all derive from it.
- Enforce the drift contract with automated tests, not conventions: template and script scans, semantic snapshot comparison, coverage and structural oracles, docs sync, and a browser smoke test per stage.
- The page never learns which stage or bugs are active. Client behavior depends only on hooks that stay stable in every stage.
- A single seam, "effective flags for this request", so the change works both before and after `workshop-spaces`.

**Non-Goals:**
- No new stages, no randomized or per-space drift, no per-participant mappings.
- No change to order creation, invoice or PDF totals, API JSON shapes (besides status fields), cart page totals, AI flags, newsletter or footer. None of these is a covered flow.
- No drift in the filter panel (no covered ids, classes or `data-test`); it is not a covered flow. Its only changes are the stage-independent ones from Decision 4: its behavior markers are removed and it gains stable accessible hooks.
- No authentication or space scoping of control endpoints (`workshop-spaces`). No story conformance audit or release gate (`acceptance-conformance`).
- Control endpoints become unadvertised, not secret.
- The shop repository does not hide the mapping.

## Decisions

Items A1–A5 (in Decisions 3, 4, 5, 6 and 16) were open assumptions in earlier drafts. The maintainer accepted all five as written, so they are decisions now. Their labels stay because other changes cite them.

### 1. Single mapping in `core/workshop.py`, exposed as request-scoped Jinja globals

**Mapping structure.**
- `core/workshop.py` defines the covered hooks once, keyed by their stage-1 name: `COVERED_IDS`, `COVERED_CLASSES` and `DATA_TEST_VALUES`. It also defines `STABLE_IDS`, the ids that never drift: `main-content`, the price filter's `price-min-range` and `price-max-range`, and the newsletter form's `newsletter-email`, `newsletter-hint` and `newsletter-alert`, which stay literal because the newsletter is not a covered flow (Non-Goals) (see Decisions 3 and 4).
- A `StageSpec` per stage 2 to 4 holds:
  - `ids`: stage-1 id → replacement. Stage 3 has entries only for form-field ids.
  - `classes`: *block* renames (`product-card → item-card`, which also renames `product-card__*` and `product-card--*`) plus *exact* overrides (`product-card__title → item-title`).
  - `keep_data_test`: true only for stage 2.
  - `layout`: component → structural variant. Stage 4 only. The list is exhaustive: `product-card: wrapped`, `product-hero-actions: wrapped` and `checkout-field: grouped`.
- Replacement names are unique across stages, so a locator healed for stage 2 cannot pass stage 3 or 4 by accident. Existing names are reused where they exist (`login-email`, `item-card` for the stage 2 card block, `product-tile` for the stage 4 card block). `workshop-spaces`' `rendered_stage()` test helper (`backend/tests/spaces/helpers.py`) relies on the two card block names.

**Template helper.** A `DriftView` built for one request exposes:
- `drift.id(key)` and `drift.cls("key other-key")`, which resolve each token.
- `drift.test(key)`, which returns the `data-test` attribute or nothing.
- `drift.layout(component)` for structural branches.
- `drift.stylesheet_href` (Decision 5).

Keys are strict: an unknown key raises, so a typo fails the contract tests instead of silently not drifting. Block derivation means BEM element and modifier classes follow their block without one table row each.

**Request seam.**
1. `core/feature_flags.py` gets an async dependency `get_effective_flags(request, session) -> dict[str, bool]`. Until `workshop-spaces` merges, it returns `list_feature_flags(session)`. Afterwards it delegates to the space-aware resolver.
2. A dependency `workshop_view` builds `WorkshopView(stage, drift, bugs)` from those flags.
3. It stores the view on `request.state.workshop_view` and sets a `ContextVar` for the duration of the request, then resets it.
4. `_mount_static_and_templates` in `main.py` registers two Jinja globals, `drift` and `bugs`. They are thin proxies that read the `ContextVar` and raise when it is unset.
5. The page routes and the hidden `/search/results` fragment declare `workshop_view` as a dependency; they are the only routes that render HTML through the `drift` and `bugs` globals (tasks 2.6 and 9.1). `GET /api/products/` returns JSON and declares no view: it reaches the flags only through the dependency `planted_delay("catalogue")` (Decision 11), which resolves them through this same seam without building a view. `GET /products` declares both. Nothing else reads flags for drift or bugs.
6. HTML is rendered only while a view is active: from routes that declare `workshop_view`, never from a global exception handler, where the proxies raise. An error or validation page (for example a future HTML not-found page from `acceptance-conformance`) is rendered by the route itself after it validates its input.

The build order adds the pieces in steps (tasks 2.6, 3.1, 5.10): the view first carries only `stage` and `drift`, `bugs` arrives with the registry, and page contexts keep the full `feature_flags` dict until no template reads workshop flags any more.

**Why globals.** Macros imported with `{% import ... as cards %}` see globals but not the render context. Passing a parameter through every macro call has already failed once (`product_detail.html`).

**Enforcement.** A unit test scans `backend/app/templates/**` and fails on:
- any `LOCATOR_` or `BUG_` token;
- a literal `data-test=`;
- a literal `id="…"` whose value is not in `STABLE_IDS`;
- a name in `COVERED_IDS` or `COVERED_CLASSES` (including the `block__*` and `block--*` names derived from a covered block) written literally inside a `class="…"` attribute, that is anywhere outside a `drift.cls(…)`, `drift.id(…)` or `drift.layout(…)` argument. Covered names match as whole class tokens, never as substrings, so the uncovered literal `category-badge` keeps the covered name `badge` inside it.

The last rule is what makes the name-based stylesheet rewrite (Decision 5) safe: every covered name reaches the markup only through the resolver, so no element of an uncovered flow can keep pointing at a renamed rule. Its consequence for Decision 3 is that a class an uncovered flow writes literally (`form-field`, the shared `button` block) must not be covered.

Once the scan passes on every template, `feature_flags` stays in the template context only for non-workshop flags (`NEW_CART_UI`, `MOBILE_UI_V1`).

**Alternatives considered.**
- Middleware that rewrites HTML responses. Rejected: regex or DOM rewriting of HTML is fragile, and JS that relies on the old names breaks silently.
- A copy of each template per stage. Rejected: four times the maintenance, and copies drift apart in content, which breaks the stability contract.
- Flags as a macro parameter (today's approach). Rejected: easy to forget, as shown above.
- Starlette context processors plus `{% import ... with context %}`. Works, but every import has to remember `with context`, which is the same class of mistake.

### 2. Stage precedence: `effective_stage(flags)`

`effective_stage(flags)` returns 4 if `LOCATOR_V4`, else 3 if `LOCATOR_V3`, else 2 if `LOCATOR_V2`, else 1. `DriftView` and the status endpoint (`locator_stage = f"v{stage}"`) both use it, and it replaces `_get_locator_stage`.

The existing tests in `test_workshop.py` for `get_class_name`, `get_element_id`, `should_remove_data_test` and `get_data_test_attr` are rewritten against `effective_stage` and `DriftView`. The old helpers are removed so there is only one implementation.

Alternative considered: keep the per-helper loops over `["LOCATOR_V4", "LOCATOR_V3", "LOCATOR_V2"]`. Rejected: that is how the card template came to disagree with the helpers.

### 3. What each stage changes, and what never changes

Stage behavior follows the spec's "Stage contract" requirement. The design adds:

- **Covered elements per flow.** These are the flows from the spec. `docs/WORKSHOP-FEATURES.md` holds the full per-stage tables.

  | Flow | Template | Examples of drifting hooks | Stage 4 layout |
  |---|---|---|---|
  | Navigation and cart badge | `base.html` | `site-nav*`, `badge`, `primary-nav-menu` | — |
  | Sign-in modal and account menu | `base.html` | `auth-modal*` (including the overlay id `auth-modal`), `auth-email`, `auth-password`, `auth-modal-title`, `account-dropdown*` (including the panel id `account-panel`) | — |
  | Home hero search and featured products | `home.html` | `hero__search`, `product-grid` (all wrappers), the search results section class `search-results` and its results-container id `search-results`, product cards | `product-card` |
  | Listing and cards | `products.html`, `components/product_card.html` | `product-card*`, including the card action class `product-card__add` | `product-card` |
  | Product detail | `product_detail.html` | `product-hero*` (the add-to-cart button's hook, which keeps the shared `button` classes), `product-grid` wrappers, related cards | `product-hero-actions`, `product-card` |
  | Cart | `cart.html` | `cart-item*`, `cart-summary*` | — |
  | Checkout form, summary and result | `checkout.html` | `checkout-form`, `checkout-email\|name\|address\|team-size\|notes`, `checkout-summary*`, `checkout-alert*` | `checkout-field` |
  | Chat widget | `base.html` | `chat-widget*` (including the widget id `chat-widget`), `chat-launcher`, `chat-input`, `chat-message` | — |
  | Add-to-cart confirmation | `base.html` | `flash`, `flash-message` | — |

- **Id references follow their ids.** Attributes that point at covered ids (`for`, `aria-controls`, `aria-labelledby`, `aria-describedby`) resolve through `drift.id` too. That keeps label and ARIA relationships intact. References to ids in `STABLE_IDS` stay literal.
  - The skip link's `href="#main-content"` is a link target, and the contract keeps link targets identical. So `main-content` stays in `STABLE_IDS` and is removed from today's `ID_TRANSFORMS`.
  - The price filter's range inputs get the stable ids `price-min-range` and `price-max-range`, referenced literally by `<output for>`. The filter panel is not a covered flow.
  - The newsletter form in `home.html` is not a covered flow either (Non-Goals). Its ids `newsletter-email`, `newsletter-hint` and `newsletter-alert` carry its `label[for]` and `aria-describedby` relationships, so they stay literal in every stage and are in `STABLE_IDS`, which is also what lets the template scan accept them. No `StageSpec` references them, so `## Drift mapping` gets no row for them.
- **Stage 4 structure.** Only the three components in the `layout` list get structural variants: product cards, the product detail purchase actions and the checkout form fields. The other flows drift in stage 4 through id and class renames only. Structural variants only add or replace role-less `div` or `span` wrappers. They never add landmarks, headings or text, and never wrap a position targeted by a CSS child combinator (`.site-nav__items>*`). The `product-hero-actions` wrapper sits inside `.product-hero__actions` around its buttons, or replaces that container with a class-renamed equivalent, so flex layout is kept. Roles and content order therefore stay identical.
- **Stable in every stage.** These go into the stable-contract table in the docs:
  - Visible text, roles, accessible names, label associations, form field `name`, form `action` and `method`, hyperlink `href` (`a` and `area`), content order. The stylesheet `<link href>` is not part of this; it changes per stage by design (Decision 5).
  - *Content data attributes*: `data-product`, `data-product-name`, `data-category` and `data-chat-prompt`. They carry shop content (product id and name, category, the full prompt text, which differs from the chip label) that the page has nowhere else. `data-category` also drives the category badge colors in the stylesheet.
  - *JS state classes*: `is-*` (including the confirmation variants `is-success`, `is-error`, `is-info`), `theme-dark`, `has-chat-open`, `site-nav-open`, and modifiers of blocks that are not covered, such as `chip--active`.
  - Ids in `STABLE_IDS`, and the price filter's accessible names "Minimum price" and "Maximum price".
  - *The header shape the script binds to* (Decision 4): the mobile navigation toggle stays the only direct-child `button` of `nav[aria-label="Primary navigation"]` and stays outside the menu its `aria-controls` names, the account trigger stays inside that menu, and the chat launcher stays a direct child of `body`. No stage wraps or moves them — the `layout` list of Decision 1 is exhaustive and contains no header component — which is what makes the disambiguated lookups of tasks 8.2, 8.3 and 8.4 stage-independent.
  - The shared field wrapper block `form-field` (and `form-field__icon`). It styles the search boxes, newsletter, sign-in modal and checkout together, so renaming it would ripple into flows that are not covered. It is not covered on purpose: the field `name` attributes are already stable by contract, so it adds no new drift-proof locator for the fields. The script does not bind to it (Decision 4).
  - The shared button block `button` and its modifiers `button--primary`, `button--ghost`, `button--text` and `button--lg`, for the same reason. They style the card action together with the filter panel's "Apply filters", the newsletter's "Join", both search submits and the auth, chat, cart and checkout buttons, so renaming them would ripple into the filter panel and the newsletter, which are Non-Goals, and would leave those buttons unstyled in stages 2 and 4 once the stylesheet follows the drift (Decision 5). They add no drift-proof locator: every covered button is reachable by role plus its stable accessible name, `.button--primary` alone matches several unrelated buttons per page, and the card action carries the covered class `product-card__add` (`btn-main` in stage 2, `product-tile__add` in stage 4), which is the hook that breaks.
  - The space indicator from `workshop-spaces`: `[data-workshop-space]` with its `Space: <id>` text, the shared-mode hint `.workshop-space-hint` with its text, and their style rules. Its spec requires them to be unaffected by drift.
- **Workshop banner removed** from `home.html` and `products.html`. It changes visible text between stages, which the contract forbids, and it discloses active bugs to anyone reading the page. Facilitators read `/api/workshop/status` instead.
- **Stage-independent markup fix.** `home.html` closes two `<h2>` elements with `</h3>` (lines 145 and 164). These are fixed so the parsed tree used by the contract tests is well-formed.
- **Decided (A4): `data-test` in every covered flow.** Today only product cards carry `data-test`. This change adds `data-test` through `drift.test` to the interactive elements and assertion targets of every covered flow, in stages 1 and 2:
  - buttons and inputs;
  - the cart badge;
  - summary totals;
  - the checkout result message;
  - the chat input and launcher;
  - the account menu trigger.

  Values are unique per element kind where the same page shows both, for example the detail add-to-cart button uses a value distinct from the card's `add-to-cart-btn`.

  Rationale: the stage ladder only teaches something if a stage-1 test author could have used `data-test` in every flow. Then stage 2 is survivable with `data-test` everywhere and stage 3 removes it everywhere. Stage-1 markup gains `data-test` attributes. Its only removals are the behavior-only markers (Decision 4) and the workshop banner, which are removed in every stage.

  Alternative: keep `data-test` on cards only. Then stage 3 means different things in different flows.

### 4. Shop JS binds only to stable hooks

**Decided (A1).** `app.js` binds only to hooks the contract keeps stable:
- ARIA roles, labels and `aria-controls` / `aria-haspopup` relationships;
- form `action`, `method` and field `name` (`form.elements.email`);
- hyperlink `href`;
- the content data attributes from Decision 3.

Where no semantic hook exists, the template gains an accessible attribute in all stages, never a marker. The behavior-only `data-*` markers and unused hooks are **removed in all stages** (**BREAKING**, in the migration notice):
- `data-cart-count`, `data-auth-*`, `data-search-*`, `data-nav-*`, `data-theme-*`, `data-icon-*` and `data-filter-form`;
- `data-chat-*` except the content attribute `data-chat-prompt` (Decision 3), that is `data-chat-toggle`, `data-chat-widget`, `data-chat-close`, `data-chat-form` and `data-chat-messages`;
- every `data-price-*` attribute: `data-price-slider`, `data-price-output`, `data-price-min-default` and `data-price-max-default`. The two defaults duplicate the range inputs' own `min` and `max`, and their only reader is a `reset` listener (the filter's Reset control is a link to `/products`). Using them to find the wrapper would make them lookup markers rather than content;
- the unused hooks `data-event`, `data-product-id` and `data-product-wrapper`.

They are exactly the drift-proof locators the brief refuses to add as `data-js-*`, so keeping them would undermine the healing exercises. Because they disappear in stage 1 too, the stage contract holds.

**No runtime markers.** `app.js` never writes `data-*` attributes or ids to the DOM. "Already bound" bookkeeping lives in memory only, in a module-level `WeakSet` of bound elements or a closure flag, never in `data-*` attributes or `is-*` classes (`is-*` is stable in every stage, so an `is-bound` class would be a new drift-proof locator). This removes `data-mobile-nav-bound`, `data-chat-bound`, `data-theme-bound`, `data-chat-prompt-bound` and `data-index`: a suggestion option's index is its position among the listbox's `[role="option"]` children. The `widget.id = "chat-widget"` fallback goes away, because the widget id now comes from `drift.id` in `base.html`. Ids come only from templates.

Examples of the new bindings (tasks will list all of them):

| Today | Stable hook |
|---|---|
| `[data-cart-count]` | `nav a[href="/cart"] [aria-live]` |
| `.site-nav`, `[data-nav-toggle]`, `[data-nav-menu]` | `nav[aria-label="Primary navigation"]`, its **direct-child** `button[aria-controls]` (`:scope > button[aria-controls]`, the nav's only direct-child button; the "Log in" button and the account trigger carry `aria-controls` too but sit inside the menu), menu looked up by the `aria-controls` id |
| `[data-auth-login]`, `[data-auth-modal]`, `#auth-email` | "Log in" `nav[aria-label="Primary navigation"] button[aria-haspopup="dialog"]` (scoped to the nav, because the chat launcher carries the same attribute outside it) → overlay by its `aria-controls` id (carries `hidden`; backdrop click is `event.target === overlay`) → its `[role="dialog"]`; close button by `aria-label`; `form.elements.email` |
| `.checkout-form`, `#checkout-*`, `[data-auth-note]`, `[data-auth-note-name]` | `form[action="/checkout"]`, `form.elements.email\|name\|address\|team_size`; the signed-in note is the form's only direct-child `<p>`, and the user name goes into that note's only `<span>`, so the note keeps its sentence |
| `[data-auth-region]`, `[data-auth-menu*]`, `[data-auth-user-name]`, `[data-auth-addresses\|payments\|orders]`, `[data-auth-logout]` | account trigger = the only `button[aria-expanded][aria-controls]` inside the nav **menu** (the nav's own toggle is a direct child of `nav` and therefore outside the menu; the theme toggle carries `aria-pressed`, the "Log in" button no `aria-expanded`) → panel by that id (from `drift.id("account-panel")` in the template, which carries `hidden`); the user name is the trigger's only `<span>`; the three lists by `aria-label="Saved addresses"\|"Payment methods"\|"Recent orders"`; logout by `aria-label="Log out"`; signed-in state toggles `hidden` on the "Log in" button and the trigger, so no region wrapper is looked up |
| `[data-chat-toggle]`, `[data-chat-widget]`, `[data-chat-close]`, `[data-chat-messages]`, `[data-chat-form]` | launcher `body > button[aria-haspopup="dialog"][aria-controls]` (attributes move from runtime JS into the template; a direct child of `body`, unlike the "Log in" button, which carries the same pair inside the nav) → widget by that id; close button by `aria-label="Close AI assistant"`; message list `[role="log"]`; form `textarea[name="question"].form` |
| `[data-search-form]`, `[data-search-input]`, `.form-field` (typeahead anchor) | `form[role="search"]`, `input[name="query"]`, the input's enclosing `label` |
| `[data-search-results-wrapper]`, `[data-search-results]`, `[data-search-empty]`, `[data-search-clear]` | `[role="region"][aria-label="Search results"]`, its results container by the id from `drift.id("search-results")`, the clear button by `aria-controls` to that id; the empty state is rendered by the server fragment (Decision 6), so it needs no hook |
| `[data-theme-toggle]`, `[data-theme-label]`, `[data-icon-sun\|moon]` | `button[aria-pressed]` in the primary navigation; its label is the button's only `<span>`; the sun/moon swap moves out of the script into the per-stage stylesheet, keyed on `body.theme-dark` and the two paths' own uncovered `theme-toggle` block classes (for example `theme-toggle__icon--sun` and `--moon`), which are what tells the paths apart once the `data-icon-*` markers are gone |
| `#flash-message` | `[role="status"][aria-live]`, the only element with the `role="status"` attribute in `base.html`; `<output>` (the price filter) carries the implicit role `status`, so `get_by_role("status")` is ambiguous on `/products` and browser checks locate the confirmation on a page without `<output>`; state only through `is-visible` and `is-success\|is-error\|is-info` via `classList` |
| `[data-filter-form]`, `[data-price-slider]`, `[data-price-output]` | `input[name="price_min"].form`, `form.elements.price_min\|price_max`, `input[type="range"][aria-label="Minimum price"\|"Maximum price"]` (stable ids `price-min-range`, `price-max-range`), `output[for]`; reset defaults from the sliders' `min` and `max` attributes |
| `[data-test='product-card'] .product-card__title a` (fallback for the product name, and the analytics `source` field) | `button[data-product]` with `data-product-name`; the analytics `source` comes from the button's own context, with no `data-test` lookup |

- JS keeps state in `is-*` classes, `hidden`, `aria-expanded`, `aria-pressed` or `aria-busy`, never in modifiers of covered blocks, and changes classes only through `classList`, never by assigning `className` (which would reset a drifted class to its stage-1 name). For example, `chat-message--loading` becomes `aria-busy`, and the confirmation variants `success`, `error` and `info` become `is-success`, `is-error` and `is-info`.
- The CSS rules that target removed hooks move to the same semantic hooks: `[data-search-form].is-loading` to the search form's hook, and `.chat-message--loading::after`, which draws the "Thinking..." indicator, to `[role="log"] [aria-busy="true"]::after` — scoped to the log, because the add-to-cart button also carries `aria-busy` and has its own rule.
- The add-to-cart confirmation names the product, taken from `data-product-name` (for example "Pulse Bio Ring added to cart."), as the spec scenario requires.
- `app.js` also drops its dead `button.dataset.quantity` read: no template renders `data-quantity`, so the current read always falls back to 1 and add to cart posts the constant quantity 1. `quantity` is deliberately not added to the content data attributes, which are part of the stable contract; after this, no `dataset` property outside those four survives in `app.js`.
- A unit test scans `app.js` and fails on: any stage-1 name of a covered id or class, matched as a whole token inside string literals (never as a substring and never in an identifier position), so the stable state class `site-nav-open` survives although the covered block `site-nav` is a prefix of it; `data-test`; a removed marker (also in `dataset` camelCase form); any `data-*` name or `dataset` property outside the content data attributes; any runtime write of a data attribute or id (`dataset.x =`, `setAttribute`/`toggleAttribute`/`removeAttribute` with a `data-` name, `Object.assign(x.dataset`, `.id =`, `setAttribute("id"`); and any `className` assignment.
- Because a regex scan cannot catch every way of writing attributes, the browser smoke test also checks the live DOM after each flow (Decision 8).

**Alternatives considered.**
- Stable `data-js-*` attributes. Rejected: they hand participants and agents a drift-proof locator.
- Injecting the mapping or the stage into the page as JSON, or fetching it from an API. Rejected: it leaks the answer.
- Keeping the existing `data-*` markers. Rejected: the same leak as `data-js-*`, only already present.

### 5. The stylesheet follows the drift

**Decided (A2).**
- The stylesheet source moves out of the public static directory to `backend/app/assets/styles.css`.
- At startup, `core/workshop.py` produces one variant per distinct class mapping. It rewrites every covered `.class` token in selector preludes (never inside declaration blocks or at-rule preludes) with the same resolver the templates use. Element names, universal selectors and uncovered classes such as `theme-dark`, `site-nav-open`, `has-chat-open`, `is-*`, `category-badge`, `theme-toggle` (with the icon classes of Decision 4), `form-field`, the shared `button` block with its modifiers (`button--primary`, `button--ghost`, `button--text`, `button--lg`), `workshop-space` and `workshop-space-hint` are left alone. Covered names are matched as whole class tokens, so an uncovered name that contains one (`category-badge`, `site-nav-open`) is never rewritten. Stages 1 and 3 share the same variant.
- The rewrite works on class names alone and cannot see where a name is used, so a covered class must never be written literally in a template. The template scan of Decision 1 enforces that; its consequence is that a class an uncovered flow writes literally is not covered (Decision 3). That is why the card action carries the covered `product-card__add` beside the shared `button button--primary`, instead of covering `button--primary` itself.
- Each variant is served from memory at `/assets/styles.<digest>.css`, where the digest is a content hash, with `Cache-Control: immutable`. The route is a small Starlette app mounted with `app.mount("/assets", …)`, not a FastAPI route. A mount is never listed in `/openapi.json`, and it does not run FastAPI app-level dependencies, so after `workshop-spaces` merges the stylesheet ignores the space exactly like `/static` does (its D1 exempts mounted asset routes such as `/assets` from space resolution), and an invalid space header does not turn it into a 400. This change owns the mount (task 6.2).
- `/static/styles.css` is removed and answers 404 (**BREAKING**, in the migration notice).
- `base.html` links `drift.stylesheet_href`. A page and its stylesheet therefore always come from the same stage, even when the preset changes between the two requests.

Rationale:
- The spec requires stage 2 and stage 4 to rename class names of covered elements, and the stylesheet styles exactly those classes. Without this, drifted pages render unstyled: badge rules, off-canvas mobile navigation, modal and chat layout are lost.
- An unstyled page gives the drift away and breaks the "behavior survives drift" requirement for mobile navigation.

Unit tests assert:
- no covered stage-1 class name remains in the stage 2 and stage 4 variants;
- no `form-field` or `button`/`button--*` token is ever rewritten: the rules whose preludes hold only uncovered tokens (`.form-field`, `.form-field input, .form-field textarea`, `.form-field__icon`, `.button`, `.button--primary`, `.button--primary:hover, .button--primary:focus-visible`, `.button--ghost`, `.button--ghost:hover, .button--ghost:focus-visible`, `.button--text`, `.button--lg`, `.button[aria-busy="true"]`) are byte for byte identical in every variant, and the three rules that mix a shared token with covered ones (`.button:focus-visible, .theme-toggle:focus-visible, .site-nav__link:focus-visible, .product-card__link:focus-visible`; `.product-card--compact .button`; `.auth-modal__form .form-field`) keep their shared token while only their covered tokens are rewritten;
- the real stylesheet's at-rule preludes, declaration blocks and selectors without covered class tokens are unchanged, and a synthetic fixture covers forms the real file does not contain (decimal media preludes, values without a leading zero);
- the source contains no `[class…]` attribute selectors that a token rewrite would miss.

**Alternatives considered.**
- One static stylesheet listing all stage names (`.product-card, .item-card, .product-tile`). Rejected: anyone reading the CSS can derive the full mapping.
- A stable styling class that identifies one covered element, next to its drifting hook class. Rejected: a drift-proof class locator. Shared utility blocks are a different case and stay literal: `form-field` and `button`/`button--*` also style uncovered flows (filter panel, newsletter, footer), so they are not covered at all and match elements all over the page (Decision 3).
- Serving `/static/styles.css` per request based on the effective stage. Rejected: needs `no-store` caching and can load a stylesheet from a different stage than its page.
- Accepting unstyled drift (today's behavior). Rejected for the reasons above.
- A FastAPI route with a path check in the space dependency. Rejected: the mount needs no exemption and is hidden from the schema by construction.
- Trade-off: the stylesheet URL changes between stages. That reveals only that something changed, which drift makes obvious anyway.

### 6. Markup built on the client drifts too

**Decided (A3).**
- **Search results** are rendered on the server. A hidden route `GET /search/results?query=` (`include_in_schema=False`) uses the same search service as `/api/search/` and returns an HTML fragment built with the product-card macro. The fragment also renders the no-results state, so the script needs no separate empty-state element. `app.js` inserts it without `innerHTML`, by parsing it into a fragment and calling `replaceChildren` on the results container, and clears the container the same way, so no assignment of markup from a variable is left in the script. Drift and planted bugs therefore apply to search-result cards exactly as they do to listing cards. The extra icon-only add-to-cart button that `renderProductCards` draws today goes away. Name, price and "Add to cart" remain, as `docs/test-prompts/homepage-and-search.md` expects.
- **Other JS-built elements** are cloned from `<template>` elements rendered with `drift`. Each `<template>` lives inside the component it serves, and JS takes that component's templates as the ordered list `:scope > template`, so none needs a marker. A component that needs more than one shell renders them as template children in a fixed, documented order and JS selects by position: the chat log holds a user shell and then an assistant shell, whose differing `chat-message--user` and `chat-message--assistant` classes come from `drift.cls` in the template and never from the script (a `className` write would reset a drifted class, and the script scan of Decision 4 rejects covered derived names). A marker is not an option here either: `data-*` literals are banned in `app.js`, and any non-content `data-*` name in the document, `template` elements included, fails the live DOM check (Decision 8). This covers the suggestion dropdown and options, chat messages (two variants) and account-menu list items. JS fills clones with `textContent`, which also removes today's `innerHTML` interpolation of user data.
- The suggestion highlight is kept without `innerHTML`: the label is built from text nodes plus `document.createElement("mark")` for each case-insensitive match of the query, so the `<mark>` highlight that `docs/test-prompts/homepage-and-search.md` expects stays true.
- The suggestion listbox id comes from the template (`drift.id`) instead of `uniqueId`, so ids are deterministic.

Rationale: drift and planted bugs must reach every product card a shopper sees, and markup the script builds must drift with its page. Rendering on the server with the same macro and the same `drift` and `bugs` globals achieves both without sending the mapping or the active bugs to the client.

**Alternatives considered.**
- Cloning a card `<template>` for search results. Rejected: bugs would not apply unless JS re-implemented the triggers, which would leak them.
- Leaving JS markup static. Rejected: `data-test` and stage-1 classes would survive stages 3 and 4 inside a covered flow, and the markup would be unstyled under Decision 5.

### 7. Contract tests (pytest + `TestClient`)

**Location and fixture.**
- Tests live in `backend/tests/contract/` (a package, with `__init__.py`).
- `backend/tests/contract/conftest.py` builds only on the shared harness from `reproducible-image` (Context). Its package-scoped fixture `contract_client` enters `isolated_app(tmp_path_factory.mktemp("contract"))` once for the package and yields that `TestClient`. The harness seeds products and flags and no users, because contract tests do not need them.
- The conftest does not patch settings, reset engine globals, clear the flag cache or set environment variables: `isolated_app` does the patching and cache clearing, and the root conftest pins the environment before any app import. The result therefore does not depend on pytest's collection order or on collection-time imports of the app by other suites (for example `acceptance-conformance`'s `backend/tests/conformance`, which imports the bug registry). It defines no fixture with a canonical harness name.
- Contract tests that place orders also request the root fixture `fake_weasyprint`, so none depends on native PDF libraries.
- A guard test asserts that the engine's database path and the PDF directory resolve inside the pytest temporary directory. Subprocesses (the fresh-interpreter determinism check) receive the same paths explicitly: the `subprocess_env` fixture copies `os.environ` and sets `WORKSHOP_DATABASE_URL` and `WORKSHOP_PDF_OUTPUT_DIR` to the values `settings` holds inside `contract_client`.
- Carts are filled through `/api/cart/items` with `X-Session-ID`. Pages are requested with `x-session-id`.

**Setting the stage.**
- Most cases override the seam: `app.dependency_overrides[get_effective_flags]`, set and cleared in `try/finally`. This matrix is quick and independent of the flag cache and spaces.
- A few cases go through `POST /api/workshop/preset` end to end.

**Matrix.** Each covered page × stages 1 to 4 × bug sets {none, `buggy`}. Pages:
- `/`, `/products`, `/products/3`, `/search/results?query=desk`;
- `/cart` and `/checkout`, with items and empty;
- `POST /checkout` error and success renders. The success render runs with `fake_weasyprint`, so it needs no native libraries. It is posted with identical form data and an identical cart in every case, and compared after normalizing the values that are unique per order (see Assertions).

**Semantic snapshot.**
- Parser: `beautifulsoup4` with the stdlib `html.parser` backend, added to the uv `dev` group. It is pure Python, tolerates malformed markup and supports CSS `select()`.
- The snapshot is the document-order sequence of:
  - normalized visible text (excluding `script`, `style` and `template` content);
  - explicit and implicit roles;
  - accessible names: `aria-labelledby` resolved within the same document, `aria-label`, `label[for]` or wrapping label, `alt`, or name from content;
  - form field `name` and `type`, form `action` and `method`, hyperlink `href` (`a[href]` and `area[href]` only; resource URLs such as `link[href]` and `script[src]` are excluded);
  - content data attributes.
- The snapshot function takes optional replacements (regex → placeholder) applied to text and `href` values. Without them it behaves exactly as above.

**Assertions.**
1. The snapshot of stage N equals stage 1 for the same bug set. Stage 1 with `buggy` equal to stage N with `buggy` is also the "Bugs combine with drift" check. The `POST /checkout` success render, and only that render, is compared after replacing `ORD-[0-9A-F]{8}` with `ORD-<n>` and `/api/docs/orders/<digits>/` with `/api/docs/orders/<id>/`. Before normalizing, each render is checked to contain exactly one order number that resolves to the order the request created, and two document links that carry that order's id, so the placeholders cannot hide a missing number or a broken link.
2. Expected differences per stage:
   - Stage 2: the multiset of `data-test` attributes is identical and not empty, covered ids and classes differ, and the ancestor tag chains of the structural anchors are equal.
   - Stage 3: no `data-test`, classes identical, only covered form-field ids differ, ancestor chains equal.
   - Stage 4: no `data-test`, covered ids and classes differ, and the structural oracle holds.
   - **Structural oracle.** A hand-written list in the tests (not in `core/workshop.py`) maps each stage 4 `layout` component to its pages and to anchors found through stable hooks: every `button[data-product]` on `/products` for `product-card`; `button[data-product="3"]` on `/products/3` (the page's own product, which related and trending cards never show) for `product-hero-actions`; the fields `form[action="/checkout"] [name=email|name|address|team_size|notes]` on `/checkout` for `checkout-field`. In stage 4, each anchor's ancestor tag chain (tag names up to `body`, so depth counts) differs from stage 1. Every anchor must match at least once on a listed page, so the check cannot pass vacuously, and the oracle's components must equal the keys of `StageSpec(4).layout`, so a layout that is declared but never checked, or checked but never declared, fails.
3. **Coverage oracle.** A hand-written list of stage-1 selectors per flow (`.site-nav__link--cart .badge`, `#checkout-email`, `#auth-email`, `[data-test='product-card']`, `#chat-input`, …). Each entry names the stages that must break it and must match in every other stage: class entries and ids that are not form fields break in stages 2 and 4, form-field ids in stages 2–4, and `[data-test='…']` entries in stages 3–4 (so they match in stage 2). Every flow in the spec's "Flow coverage" requirement has at least one `data-test` entry and at least one id or class entry. The list lives in the tests, not in `core/workshop.py`, so a missing mapping entry cannot hide itself.
4. **Docs sync.**
   - The mapping tables and the bug registry table in `docs/WORKSHOP-FEATURES.md` are found under the headings `## Drift mapping` and `## Planted bugs` (Decision 14), so other sections (for example `## Workshop spaces` from `workshop-spaces`) and tables elsewhere do not affect parsing.
   - Tokens removed and added between stage 1 and stage N (computed as sets, so no element alignment is needed) are all explained by rows in the doc, taking block rules into account.
   - The doc rows equal the tables in `core/workshop.py`, including the `layout` rows, so no stale rows remain.
   - The bug registry table equals `PLANTED_BUGS`.
5. **Determinism.** Two sessions and a fresh app instance produce identical hook sets for each stage.

**Alternatives considered.**
- Golden HTML files. Rejected: brittle against content edits. Comparing against stage 1 of the same build is not.
- A hand-written tree builder on stdlib `html.parser`. Rejected: more code, and it would need its own tolerance for malformed markup.
- `lxml`. Rejected: native wheels for no benefit at this size.
- Patching `uuid4` to make the success render identical. Rejected: `order_number` is unique, and `order.id` keeps increasing unless every render gets a fresh database.
- Environment variables set before the app is imported. Rejected: silently runs against the developer's `./workshop.db` when another suite imported the app first.
- A contract-specific settings patch and engine reset next to the shared harness. Rejected: two harnesses patching the same globals in one `pytest` process interfere (`reproducible-image` D11), and `isolated_app` already works at package scope.

### 8. Browser smoke test per stage (pytest-playwright)

- `pytest-playwright` is added to the uv `dev` group. `acceptance-conformance` reuses it together with `httpx`.
- Tests live in `backend/tests/browser/` (a package) under marker `browser`. They are parametrized over presets `stage1` to `stage4`, applied through `POST /api/workshop/preset`.
- The flows are the ones listed in the spec's "Shop behavior survives drift" requirement: add to cart (badge and a confirmation that names the product), sign-in and account menu (including closing the dialog by its close button and by clicking the backdrop), checkout autofill after sign-in, search suggestions with keyboard selection and the `<mark>` highlight, mobile navigation at 390×844, theme toggle (`theme-dark` on `body`, `aria-pressed`), and the chat widget (mock AI). The price filter (slider output and `price_min` on submit) is smoke-tested too, because its markers are removed.
- The smoke test uses only role, label and text locators. Where it reads a detail of an element found that way (the `mark` children of an option, the class list of the confirmation region), it uses `evaluate` on the role-located element. It is itself a drift-proof reference suite.
- As a cross-check of the static approximation, each page's `locator("body").aria_snapshot()` in stage N must equal stage 1. A real browser computes accessible names and applies CSS visibility, so this also catches stylesheet regressions such as an always-visible badge. Both sides are captured in the same browser context — and therefore, after `workshop-spaces`, in the same space, with the same `[data-workshop-space]` indicator in the accessibility tree — with the stage-1 side produced by applying preset `stage1` in that context rather than reused from another parametrization.
- **Live DOM check.** After each smoke flow in each stage, `page.evaluate` collects every attribute name and id in the document. Every `data-*` name must be a content data attribute, `data-test` (stages 1 and 2 only) or, after `workshop-spaces`, `data-workshop-space`. Every id must also appear in the server-rendered HTML of the same page and stage (including `<template>` content). This catches runtime markers however the script writes them.

**Target server.**
- **Base-URL mechanism**, which `acceptance-conformance`'s conformance suite uses too: the `--base-url` option of pytest-base-url (bundled with pytest-playwright) selects a running target, for example the candidate image in CI. `backend/tests/browser/conftest.py` overrides pytest-base-url's session-scoped `base_url` fixture for its own directory and returns the option value when it is given. `base_url` is never set in the ini file, and no project-specific environment variable selects a target: the only target selector is pytest-base-url's `--base-url` option, whose default that plugin itself fills from `PYTEST_BASE_URL`. Nothing else points a suite at an external server. Without a resolved value the browser suite starts its own server from source (below), while `acceptance-conformance`'s conformance suite stops with a usage error instead of falling back to a port.
- Without `--base-url`, the same fixture seeds a temporary database with `python -m tools.seed_db` in a separate process, starts uvicorn from source on a free port with `WORKSHOP_DATABASE_URL` and `WORKSHOP_PDF_OUTPUT_DIR` passed explicitly in the subprocess environment, and returns that server's URL.
- Runs are sequential in the default space. After `workshop-spaces`, each stage uses its own space through `extra_http_headers`, which allows parallel runs and runs against the hosted fallback; cross-stage comparisons never cross a space boundary.

**Alternatives considered.**
- Robot Framework Browser suites in this repository. Rejected: those belong to the participant repository and would duplicate the workshop's material.
- Contract tests without a browser. Rejected: they cannot catch JS or CSS regressions.

### 9. Planted-bug registry

`PLANTED_BUGS` in `core/workshop.py` is an ordered tuple. Each entry has `flag`, `flow`, `trigger`, `defect` and `scope`:

| Flag | Flow | Trigger | Defect |
|---|---|---|---|
| `BUG_MISSING_BUTTON` | Catalogue | product id % 5 == 0 | card has no add-to-cart button |
| `BUG_WRONG_PRICE` | Catalogue | product id % 3 == 0 | card price × 1.15, rounded to cents |
| `BUG_BROKEN_LINKS` | Catalogue | product id % 4 == 0 | card links to `/products/invalid-<id>`, which is not a product page (4xx) |
| `BUG_SLOW_RESPONSE` | Catalogue | every request to `GET /products` or `GET /api/products/` | 1 to 3 s delay |
| `BUG_CHECKOUT_TOTAL` | Checkout | any non-empty cart | displayed total omits tax |

The registry drives:
- `_get_active_bugs`, in registry order;
- preset contents (Decision 12);
- the docs table check;
- `FEATURE_FLAGS` seed rows, which are generated from the registry so a new bug cannot be forgotten.

Behavior goes through registry helpers only:
- Templates use `bugs.card_price(product)`, `bugs.card_href(product)` and `bugs.hides_add_to_cart(product)`.
- Routes use `bugs.checkout_total(summary)` and the `planted_delay("catalogue")` dependency.

Triggers depend only on product id or cart state, never on stage, session or space. That makes the spec's "identical in every stage" property true by construction. Card bugs apply wherever the card macro renders, including the related and trending cards on the product detail page and search-result cards.

**No bug markers.** A defect must look like an ordinary defect. The hidden-button placeholder and its `data-test="hidden-button-placeholder"` / "Button unavailable" text are replaced by an empty, `aria-hidden` spacer that keeps the layout. Existing bugs keep their triggers and defects, so the `/products/invalid-<id>` URL is kept (see Risks).

**Alternatives considered.**
- Keeping the bug logic inline in templates. Rejected: drift and bug conditions end up mixed, and the two can drift apart.
- Hash-based or random triggers. Rejected: not documentable and not reproducible in one run.

### 10. Checkout summary and `BUG_CHECKOUT_TOTAL`

- A function `checkout_summary(cart_state)` in `services/order_service.py` returns `subtotal`, `tax` and `total` from `calculate_totals(cart_state["items"])`. It uses the same default tax rate as `OrderService.create_order`, so the page cannot disagree with the order.
- `GET /checkout` and both re-renders in `POST /checkout` (error and success) pass `summary = bugs.checkout_total(checkout_summary(cart_state))`.
- `checkout.html` shows Subtotal, Shipping ("Complimentary"), Tax (amount) and Total.
- With `BUG_CHECKOUT_TOTAL`, only the displayed `total` is replaced by `subtotal`. Subtotal and tax lines stay correct.
- Order creation, `api/checkout.py` and the PDFs are untouched.
- The trigger "any non-empty cart" needs tax > 0. The cheapest seeded product (39.50) gives tax ≥ 2.77, and a registry unit test asserts that the minimum seeded price × rate ≥ 0.01.
- `cart.html` ("Estimated tax: Calculated at checkout") stays as it is. It is truthful and outside the spec.
- `seed_feature_flags` gains the `BUG_CHECKOUT_TOTAL` row through the registry. It inserts only missing rows (checked), so no data migration is needed, and a missing row reads as disabled.

Alternatives considered:
- Computing totals in the template. Rejected: that duplicates `calculate_totals`.
- Applying the bug in `OrderService`. Rejected: the spec requires the order and invoice to stay correct.

### 11. `BUG_SLOW_RESPONSE` scope

- A dependency `planted_delay("catalogue")` is attached to the `GET /products` page route and to `GET /api/products/` in `api/products.py`. It awaits `asyncio.sleep(random.uniform(1.0, 3.0))` when the bug is active.
- The sleep happens after the effective flags are resolved and before the route's own catalogue queries. Once `workshop-spaces` is merged, flags come from its short-lived resolver session (its D4), so the request session holds no pooled connection or transaction during the sleep. The interim seam (task 2.1) reads flags on the request session when the TTL cache misses, so it can hold that connection during the sleep. This is accepted because the interim body exists only until the rebase (task 15.1).
- `asyncio.sleep` does not block the worker, so other requests, including other spaces on the shared instance, are unaffected.
- The random duration is fine because the registry's deterministic property is *which* responses are delayed.

Alternatives considered:
- Global middleware. Rejected: the spec forbids delaying other responses.
- A fixed 2 s delay. Also fine, but the brief and the existing helper use 1 to 3 s.

### 12. Presets are absolute for the flag groups they own

`build_presets()` in `core/workshop.py` derives presets from `LOCATOR_FLAGS`, `PLANTED_BUGS` and `AI_FLAGS`. `api/workshop.py` imports the result.

| Preset | Owns | Sets |
|---|---|---|
| `clean` | locator, bug, AI | all locator and bug flags off; `AI_DETERMINISTIC` on, other AI flags off |
| `stage1` | locator | every locator flag off (stage 1 is the absence of locator flags; there is no `LOCATOR_V1`) |
| `stage2` to `stage4` | locator | exactly the stage's flag on, the other locator flags off |
| `buggy` | bug | all registry bugs on |
| `drift_and_bug` | locator, bug | `LOCATOR_V4` on, `BUG_WRONG_PRICE` and `BUG_CHECKOUT_TOTAL` on, every other locator and bug flag off |
| `ai_chaos` | AI | unchanged |

- `drift_and_bug` uses stage 4, not stage 2 as the original brief proposed. Stage 2 keeps `data-test` (A4 adds it to the card price and the checkout totals) and stage 3 keeps classes, so a suite built on either hook kind would see only the bug assertions fail and have nothing to heal. Stage 4 is the only stage that breaks all three non-semantic hook kinds (`data-test`, ids, classes) in the same flows as the bugs, while role and text locators still find the elements. The heal and the bug therefore meet in one run, which is what the heal-vs-hide judgment needs. A gentler "bugs without heals" exercise is available as `stage2` followed by `buggy`.
- `stage1` no longer turns off bugs. Today it turns off three of four, which is inconsistent. With ownership by group, presets compose: `stage3` then `buggy`.
- `GET /api/workshop/presets` gains a description for `drift_and_bug`.
- `workshop-spaces` owns the write path. Applying a preset should write all owned flags in one commit, so a concurrent page request never sees a half-applied preset. Precedence already makes any transient state a well-defined stage.

Alternative considered: presets that set only what they switch on. Rejected: leftovers from earlier presets make the result depend on history.

### 13. Control endpoints are not advertised

`configure_routes()` in `main.py` passes `include_in_schema=False` for the `workshop` and `admin` routers. Everything under `/api/workshop/` (including `reset` from `workshop-spaces`) and `/api/admin/` disappears from `/openapi.json`, `/docs` and `/redoc`, but stays callable. The new `/search/results` route is also hidden, and the `/assets` stylesheet mount is never part of the schema. `docs/WORKSHOP-FEATURES.md` documents the control endpoints for facilitators.

This hides the endpoints from agents browsing the schema only. Their JSON still names the stage and bugs (Constraints), so workshop material must keep that output out of agent context (Risks, Migration Plan step 6).

Alternatives considered:
- Removing `/docs` entirely. Rejected: agents legitimately explore the shop API.
- Requiring a token to read flags. That is `workshop-spaces` territory, and only in shared mode.
- Hiding bug identities behind a facilitator token or reveal switch. Out of scope: it would change the "Bug registry" requirement, the status contract that `acceptance-conformance` relies on, and the env var contract. It needs its own cross-change decision if the workshop owner wants real secrecy.

### 14. `docs/WORKSHOP-FEATURES.md` rewritten as a machine-checked contract

This change owns the document's structure. It has these sections, in this order, with these exact headings:
1. `## Stages and precedence`: stages overview and precedence.
2. `## Stable contract`: the stable-contract table (Decision 3).
3. `## Drift mapping`: one table per covered flow, each under a `###` flow heading, with the fixed columns `Kind | Stage 1 | Stage 2 | Stage 3 | Stage 4`. `Kind` is one of `id`, `class-block`, `class-exact`, `data-test` and `layout`, and `—` means unchanged. Every table in this section is a mapping table.
4. `## Planted bugs`: the bug registry table (Decision 9) with the columns `Flag | Flow | Trigger | Defect`, one row per `PLANTED_BUGS` entry in registry order. A new planted bug (for example from `acceptance-conformance`) gets a `PLANTED_BUGS` entry and a row in this table, never a table of its own.
5. `## Presets`: presets and owned flags (Decision 12), including `drift_and_bug` as stage 4 plus two bugs.
6. `## Control endpoints`: hidden from the schema, still callable, and their responses readable. For space scoping, reset, the shared-mode 401 and the status fields `space` and `version`, this section links to `## Workshop spaces` instead of repeating it.
7. `## Workshop spaces`: owned by `workshop-spaces` (prose only, no tables), written there and kept verbatim here as the last section. It appears on this branch once `workshop-spaces` is on the base (at the latest after the rebase in Decision 15).

The docs-sync test parses tables only under `## Drift mapping` and `## Planted bugs`. Other sections, including `## Workshop spaces` and any prose section another change adds, do not affect it.

Obsolete content is removed: the fallback-selector example built on `data-event`, and the exercise list that assumed only cards drift.

Alternative considered: generating the tables from code. Rejected for now: hand-written tables checked by tests stay readable in review. Generation can come later without changing the check.

### 15. Interaction with `workshop-spaces`

- drift-coverage reads flags only through `get_effective_flags`. After `workshop-spaces` merges, that function's body is replaced by the space-aware one. Templates and helpers do not change. `workshop-spaces`' tests and tools avoid today's markup, template context and stylesheet URL, so the rebase only confirms them (below).
- Expected merge conflicts, resolved by rebasing drift-coverage onto `workshop-spaces` (task 15.1):
  - `core/feature_flags.py`: the interim `get_effective_flags` body gives way to the space-aware dependency. `workshop-spaces`' `baseline_flags()` is pointed at this change's sources: the seeded `FEATURE_FLAGS` defaults, whose bug rows come from `PLANTED_BUGS` (task 3.2), with `build_presets()["clean"]` applied on top. A new bug flag such as `BUG_CHECKOUT_TOTAL` is then part of every space's baseline.
  - `api/workshop.py`: status fields, presets vs. scoping and reset.
  - `base.html`: space indicator vs. drifted markup.
  - `main.py`: cart keys vs. `workshop_view` dependencies.
  - `backend/app/static/styles.css`: the `.workshop-space` and `.workshop-space-hint` rules from `workshop-spaces` (its task 9.2) vs. the move to `backend/app/assets/styles.css`. The rules move unchanged into the per-stage stylesheet source. Their classes are not covered, so every variant keeps them. A repository-wide grep for `static/styles.css` after the rebase and task 15.6 finds only the 404 assertion (task 6.2).
  - `docs/WORKSHOP-FEATURES.md`: the rewrite of sections 1–6 vs. the added `## Workshop spaces` section, which is kept verbatim as the last section (Decision 14).
- `workshop-spaces` wrote its suite to survive this change (its D12 and Risks), so `backend/tests/spaces/` runs unchanged after the rebase. Task 15.6 confirms each point and edits only what is missing:
  - `backend/tests/spaces/test_page_flags.py` checks the seam with `NEW_CART_UI`, which stays in the page context, and checks drift with `rendered_stage()`. It never reads `LOCATOR_*` or `BUG_*` from `response.context["feature_flags"]`.
  - `backend/tests/spaces/test_space_resolution.py` checks `/static/app.js` and the stylesheet linked from `/` with an invalid space header, never `/static/styles.css`.
  - `loadtest/locustfile.py` fetches the assets linked from each loaded page under `asset:stylesheet`, `asset:script` and `asset:image`.
  - `rendered_stage()` in `backend/tests/spaces/helpers.py` stays valid as long as the `StageSpec` card block names stay `item-card` and `product-tile` (asserted by a unit test, task 2.3). It is updated only if those names change.
  - The no-enumeration test in `backend/tests/spaces/test_shared_mode.py` lists routes from `app.routes`, so it still calls the control endpoints after they leave the schema (task 15.4).
- The space indicator must use stable hooks and must not go through `drift`.

### 16. CI: the `test` job gates promotion of the candidate

**Decided (A5).** drift-coverage owns a `test` job in `.github/workflows/image.yml`, and `publish` needs it. The job graph is `reproducible-image`'s (its D7):
- `build` builds `linux/amd64` and `linux/arm64` once and pushes the candidate by digest with no tag.
- Verification jobs run against that digest.
- `publish` needs every verification required for the ref. Only then does it create `sha-<short>`, `edge`, `X.Y.Z` and `workshop-<id>` with `docker buildx imagetools create`.

A candidate that fails `test` therefore carries no tag at all, not even `sha-<short>`.

**The `test` job** needs `build`, runs on every event except pull requests, uses `ubuntu-24.04` and pins actions by full SHA. It:
1. checks out the commit, sets up uv and runs `uv sync --locked`;
2. runs the unit and contract suites (`uv run pytest backend/tests/unit backend/tests/contract`);
3. logs in to GHCR read-only (`packages: read`), which is required while the package is private (until `reproducible-image` task 10.2) and harmless afterwards;
4. starts `ghcr.io/manykarim/demo-webshop@${{ needs.build.outputs.digest }}` with only `-p 9090:9090` and waits for `healthy`;
5. installs Chromium and runs `uv run pytest -m browser backend/tests/browser --base-url http://localhost:9090` for `stage1`–`stage4`, printing `docker logs` on failure.

**Pull requests.** Nothing is pushed, and the loaded amd64 image exists only inside `build`. The browser smoke therefore runs as extra steps at the end of `build`, after `reproducible-image`'s `recreated` smoke phase and against that same running container. `test` is skipped. The unit and contract suites run in `check`, as on every event.

**`publish`.** `needs` gains `test`, and the condition gains `needs.test.result == 'success'`. After `acceptance-conformance` adds `conformance`, the job reads `needs: [build, smoke, test, conformance]` (`reproducible-image` D7). `test` is required on `main`, `vX.Y.Z`, `workshop-<id>` and `workflow_dispatch` runs.

Rationale:
- The browser smoke is the only check that exercises the built image's script and stylesheet in every stage, so it verifies the digest that will be tagged, not a separate build.
- Running the unit and contract suites in the same job (they also run in `check`) makes `test` the single result that says the drift contract holds for this candidate. Re-running that one job re-verifies all of it.

Alternatives considered:
- Browser smoke only in `check`, from source. Rejected: it would not test the image that gets tagged.
- A `test` failure that blocks only the human-readable tags. Rejected: `reproducible-image` tags nothing before verification, so an unverified candidate must not carry `sha-<short>` either.

## Risks / Trade-offs

- **[JS regressions after rebinding]** → Browser smoke per stage (Decision 8), the `app.js` scan for covered names and runtime writes, the live DOM check, and the aria-snapshot cross-check.
- **[Snapshot brittleness]** → Every comparison is stage N against stage 1 of the same build, not golden files. Text is whitespace-normalized. The simplified accessible-name algorithm is the same on both sides, and the Playwright aria snapshot catches what it misses. Values unique per order (order number, order id in document links) on the checkout success render are normalized, and nothing else is.
- **[Mapping revealed by the public shop repository]** → Accepted. The participant repository contains no shop source. No shop page, stylesheet, script or schema reveals the mapping: no banner, no bug markers, no stage in JS, no runtime markers, CSS contains only the active stage's names, and the schema is hidden. The stylesheet digest changes per stage, which reveals only that something changed.
- **[Control endpoints still readable (`GET /api/workshop/status`, `GET /api/workshop/presets`, `GET /api/admin/flags`, and the `POST /api/workshop/preset` and `/flags` response bodies)]** → Accepted. They are unadvertised, not secret, and name active bugs by flag key. Shared-mode write protection comes from `workshop-spaces`. Mitigation is a teaching convention with a concrete handover (migration notice item, task 17.2): workshop material applies presets through a script whose output the agent does not read (no `active_bugs`, `applied_flags`, `all_flags` or preset flag contents printed), and participant agent instructions (for example the participant repository's `CLAUDE.md`) say not to call `/api/workshop/*` or `/api/admin/*` while diagnosing failures or healing. Permission deny rules for those paths are at most a speed bump, not a boundary. The public shop repository discloses the same information.
- **[Suites built only on roles and text never need healing]** → Intended. That is the stage contract working; facilitators should know that such a suite passes drift stages untouched and still fails on planted bugs.
- **[RBCN-era heal tests relying on `data-test` or `data-*` markers]** → Stage 2 keeps `data-test`. Decision 4 (A1) removes behavior markers in stage 1 as well. This is listed in the migration notice. RBCN material is reference only, and the participant repository has no suites yet.
- **[Templates mixing drift and bug logic]** → Templates call `drift.*` and `bugs.*` only. The scan forbids flag keys. The bug-set × stage snapshot matrix proves the two are independent.
- **[Stage 4 wrappers break layout or CSS child combinators]** → Wrappers are role-less, limited to three components and placed away from child-combinator targets. The structural oracle, the mobile-nav smoke test and the aria snapshot cover this.
- **[The class-selector rewrite misses a selector form]** → A unit test checks that no covered stage-1 class remains in the stage 2 and 4 variants and that the source has no `[class…]` selectors.
- **[Id-based triggers depend on seed order]** → The registry documents product ids. Contract tests look products up by SKU and assert the expected ids. `acceptance-conformance` must append fixtures, not reorder them.
- **[`/products/invalid-<id>` hints at the defect]** → Accepted. Existing bugs keep their triggers and defects (proposal), and the defect is meant to be detectable: the link target is not a product page and answers with a client error. Today that is a JSON 422 from the `int` path validation; it may become an HTML not-found page once `acceptance-conformance` fixes WEB-003 AC-9, so tests assert a 4xx without product content, not one exact status.
- **[`ContextVar` unset or leaking between requests]** → The dependency sets it and resets it per request. An unset value raises, so the failure is loud in tests. HTML is never rendered from exception handlers (Decision 1).
- **[Contract tests writing into the developer's database or PDF directory]** → The shared harness patches settings at fixture time, a guard test checks the resolved paths, and the marker-file and `find` check (Context) looks for new database and order PDF files instead of relying on `git status`.
- **[Behavior changes facilitators may rely on: `stage1` no longer turns off bugs, banner removed, stylesheet URL moved, search-result card markup changes, `drift_and_bug` on stage 4]** → Covered by the migration notice and the rewritten `WORKSHOP-FEATURES.md`. `clean` is the reset.
- **[A browser-only regression leaves a `main` commit without any tag, `sha-<short>` included]** → Accepted and intended (Decision 16): `edge` keeps pointing at the last verified candidate, and the fix goes forward in a new commit. The failing run's digest stays in its step summary for debugging.
- **[Checkout copy and totals change in the clean state]** → This is intended by the proposal. `acceptance-conformance` audits the new text afterwards.

## Migration Plan

1. **Prerequisites.** `reproducible-image` is merged: uv `dev` group, `uv.lock`, the shared test harness, idempotent PDF-free seeding, graceful PDF degradation and `image.yml` with `check`, `build`, `smoke` and `publish`. It may still be an active OpenSpec change until its task 10.6. drift-coverage adds `pytest-playwright` and `beautifulsoup4` to the `dev` group and updates `uv.lock`. Items A1–A5 are decided, so no confirmation gate precedes template work.
2. **Build order inside the change.**
   1. Seam, `effective_stage`, `DriftView` (the view carries `stage` and `drift`; page contexts keep the full `feature_flags` dict), then the registry with the `bugs` global, presets, and unit tests.
   2. Templates, flow by flow, with `data-test` additions, ARIA hooks, banner removal and `<template>` elements. `feature_flags` is narrowed to non-workshop flags once the template scan passes.
   3. Stylesheet variants and mount.
   4. `app.js` rebinding and the search-results fragment.
   5. Checkout summary and the new bug.
   6. Slow-response dependency.
   7. Router schema flags.
   8. Contract tests, docs rewrite, and completion of the browser smoke test, whose harness and stage-1 flows land with the smoke harness (task group 7, before the `app.js` rebinding) while the assertions that depend on the new ARIA hooks are added with that rebinding (tasks 8.3 and 9.3).
   9. The CI `test` job (Decision 16).
3. **Merge.** `workshop-spaces` and drift-coverage are developed in parallel after `reproducible-image`; `workshop-spaces` merges first. drift-coverage rebases, points `get_effective_flags` at the space resolver and `baseline_flags()` at `build_presets()["clean"]`, resolves the conflicts in Decision 15, runs `backend/tests/spaces/` unchanged, and merges. Archive it with `openspec archive drift-coverage` right after merging, before `acceptance-conformance` starts, so `openspec/specs/planted-bugs/spec.md` exists for that change's delta. Then `acceptance-conformance` starts against the final UI.
4. **CI (Decision 16).** Unit and contract tests run in `check` on every event. On pull requests the browser smoke runs as steps inside `build` against the locally loaded amd64 image. On other events the `test` job verifies the untagged candidate digest that `build` pushed, and `publish` creates tags (`sha-<short>`, `edge`, `X.Y.Z`, `workshop-<id>`) only after `test` succeeded. A failing `test` leaves the candidate with no tag at all. `acceptance-conformance` later adds its `conformance` job next to `test`.
5. **Data.** No schema change. `seed_feature_flags` adds the `BUG_CHECKOUT_TOTAL` row to existing databases (insert-missing only). Presets create missing rows on demand through the space write path of `workshop-spaces` (`set_flags`, one transaction per preset; see task 15.1).
6. **Release.** After `publish` tags `edge` (only once `test` passed), run the browser smoke test against it (task 17.1). Version and workshop tags are cut later as planned. Send a notice to facilitator material in the workshop repository covering:
   - the new preset `drift_and_bug` (stage 4 plus `BUG_WRONG_PRICE` and `BUG_CHECKOUT_TOTAL`);
   - `stage1` no longer turns off bugs;
   - the banner is gone;
   - control endpoints are hidden from `/docs`;
   - control endpoint responses still name active bugs, so preset switching stays out of agent context and agents are told not to call them;
   - the removed behavior `data-*` markers;
   - the stylesheet URL move;
   - the removed hidden-button placeholder and the new search-result card markup;
   - the updated mapping document.
7. **Rollback.** Redeploy the previous `X.Y.Z` tag or a recorded digest. `sha-<short>` is a moving per-commit pointer and is not used for rollback. The extra flag row is ignored by older code: its hard-coded bug list and templates never read it. Participant repositories pin image tags and are unaffected until they bump.

## Open Questions

- Exact wording of the add-to-cart confirmation and of the checkout summary labels ("Tax", "Total"). They should match the WEB-005 and WEB-006 acceptance criteria imported by `acceptance-conformance`. Tests compare against stage 1 and use role or label locators, so a wording change does not affect the mapping, the tests or the tasks.
- Concrete replacement names for newly covered hooks (for example stage 2 and 4 names for `checkout-summary` or `chat-launcher`) and concrete `data-test` values. They are chosen during implementation under the uniqueness rule. The docs-sync test keeps them consistent. The card block names `item-card` and `product-tile` are fixed.
- Whether the aria-snapshot cross-check runs on every covered page or only on the smoke flows. This is runtime tuning of the browser suite.
