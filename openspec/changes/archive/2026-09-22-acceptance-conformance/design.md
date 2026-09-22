## Context

Motivation and scope: see `proposal.md` (Why, What Changes). Requirements: see `specs/acceptance-stories/spec.md`. This section records only the current state that shapes *how* the change is built. Facts about today's code were checked on branch `openspec/workshop-plan` on 2026-09-16 and re-checked on 2026-09-17 where this revision changed them. Where a sibling change alters a fact, the state after that change is stated too, because this change starts only after all three have merged. The candidate deviations in D5 come from reading the code and the stories, not from running checks.

**Source story set**
- Repository `manykarim/ai-workshop-rbcn-2026`, path `docs/RF-MCP/1.3.RF-MCP_Automate_Scenarios/user_stories/webshop/{web,api,ai}/`, contains 28 files: WEB-001 to WEB-011, API-001 to API-011 and AI-001 to AI-006. HEAD of the default branch is `580e816` (2026-02-09). The last commit touching the directory is `5700421` (2026-02-05). The files were read via `gh api` at `580e816`.
- AC headings (`### AC-n: title`) in the in-scope files: WEB-002 13, WEB-003 9, WEB-004 8, WEB-005 9, WEB-006 11, WEB-007 10, API-005 11, API-006 13, API-007 11. That makes 95 in total. Every in-scope story numbers its criteria from AC-1 to AC-n without gaps.
- Each file has a header table (ID, title, priority, component, then labels or endpoints), the user story, Given/When/Then/And criteria, test data tables, example requests and responses, and notes.
  - The API stories' examples use `http://localhost:8000`.
  - Several notes name internals, for example `CartService.get_cart_state()`, Pydantic `Field` constraints and `selectinload`.
  - None of the in-scope files contains the words `drift` or `feature flag`.
- The source set contradicts itself on at least one point. WEB-006's test data expects `^ORD-\d{4,}$`, while API-006 AC-2 expects `ORD-[A-F0-9]{8}`.

**Current docs, tests and pipeline**
- `docs/user-stories/` holds three lighter files without IDs (`shopping-experience.md`, `checkout-and-orders.md`, `ai-and-operations.md`). No file in the repository links to them.
- `backend/tests/` holds the packages `unit` (two modules today, `test_order_service.py` and `test_workshop.py`) and `integration` (only `__init__.py`). After the sibling changes:
  - `reproducible-image` (its D11) owns the one shared test harness. `backend/tests/harness.py` provides the scope-agnostic context manager `isolated_app(tmp_dir, *, seed_users=False)` and the process environment declarations `SCRUBBED_ENV_VARS`, `SCRUBBED_ENV_PREFIXES` (with `WORKSHOP_FLAG_`) and `PINNED_ENV_VARS`, applied by `pin_test_environment`. The root `backend/tests/conftest.py` pins that environment at module top, before any app import, and provides the function-scoped fixtures `temp_database`, `app_client`, `seeded_app_client`, `pdf_unavailable` and `fake_weasyprint`. Later changes reuse these by exact name, never define a fixture with one of these names, never add a second root conftest, and never set environment variables of the pytest process or reset engine globals themselves; suite-specific fixtures go only into conftest files of their own test directories.
  - `workshop-spaces` adds its suite in `backend/tests/spaces/` (for example `test_space_carts.py`, `test_space_resolution.py`), and `drift-coverage` adds `backend/tests/contract/` (for example `test_stage_contract.py` with `COVERED_PAGES`, `coverage_oracle.py`, `test_docs_sync.py`, `test_presets_api.py`, `test_planted_bugs.py`) and `backend/tests/browser/` (marker `browser`).
  - `drift-coverage` adds `pytest-playwright` to the uv `dev` group (its task 1.2) and `[tool.pytest.ini_options]` with the marker `browser` and `addopts = "-m 'not browser'"` (its task 7.1). Its Decision 8 defines the base-URL mechanism for every suite that targets a running server: only pytest-base-url's `--base-url` option; each suite overrides the session-scoped `base_url` fixture in its own directory conftest; `base_url` is never set in `pyproject.toml`, and no project-specific environment variable selects a target — the only source is that option, whose default pytest-base-url reads from its own `PYTEST_BASE_URL`.
  - `httpx` is already a runtime dependency in `pyproject.toml`, so the API checks add no package.
  - The conformance suite targets a running container and uses none of the in-process fixtures. Regression tests for app fixes found by the audit use the root fixtures.
- The `reproducible-image` design (D7) defines `.github/workflows/image.yml` as follows:
  - `check` runs `uv run pytest backend/tests`.
  - `build` builds `linux/amd64` and `linux/arm64` once and pushes the candidate by digest with no tag. Its job outputs are `digest` (the pushed index digest), `app_version` and `tags`.
  - Verification jobs run against `ghcr.io/manykarim/demo-webshop@${{ needs.build.outputs.digest }}`: `smoke` natively on amd64 and on arm64, `drift-coverage`'s `test`, and this change's `conformance`.
  - `publish` needs every verification required for the ref. Only then does it create `sha-<short>` and `edge`, `X.Y.Z` or `workshop-<id>` with `docker buildx imagetools create` on the verified digest, without rebuilding. A candidate that fails a required verification carries no tag at all, `sha-<short>` included. `sha-<short>` is a moving per-commit pointer; a specific image is identified by its digest or its version or workshop tag.
  - `conformance` is required only on `workshop-*` tag refs. It runs without being required on `main` and on `workflow_dispatch` runs of other refs, and it does not run for pushed `vX.Y.Z` tags or pull requests. The target graph is `check` → `build` → (`smoke` matrix, `test`); `smoke` → `conformance`; (`build`, `smoke`, `test`, `conformance`) → `publish`.
  - `reproducible-image` task 10.5 checks the image level of the workshop tags this change pushes: the blocked rehearsal candidate carries no tag; the promoted digest equals the `build` output, `sha-<short>` resolves to it, the revision label names the tagged commit, and an anonymous arm64 pull works and reports the workshop version.
- **Archive order of the siblings.** `drift-coverage` is archived right after it merges (its task 17.3), so `openspec/specs/planted-bugs/spec.md` exists when this change starts. `reproducible-image` stays an active change until its task 10.5 has checked this change's first workshop tags, and is archived in its task 10.6. `workshop-spaces`' archive is not a prerequisite here.

**Application behavior that shapes the checks (verified by reading)**
- **Session resolution differs by route.** Pages use the `X-Session-ID` header, then the `session_id` cookie, then `workshop-demo` (`backend/app/main.py:78-81`). `/api/cart` and `/api/checkout` read only the header (`api/cart.py:19-20`, `api/checkout.py:21-22`). `static/app.js` creates the `session_id` cookie (`app.js:62-72`) and sends the same value as `X-Session-ID` (`app.js:134-137`, `163-168`). `workshop-spaces` D3 decides this split on purpose: pages use the header, then the cookie; the APIs read the `X-Session-ID` header only. Its `backend/tests/spaces/test_space_carts.py` covers the pages with and without the cookie and the APIs with and without the header, but no cookie-only API call, so WEB-005 AC-8's cookie-only case (task 10.1) is what guards the APIs ignoring the cookie. It also makes `workshop-demo` the fallback session name in every space: `cart_session_id(session_id)` is the caller-facing id, `cart_storage_key(space, session_id)` is `<space>:workshop-demo` outside `default`, and `GET /api/cart/`, `POST /api/cart/items` and `DELETE /api/cart/` report the `session` field unprefixed (`session_label`).
- **Flag precedence after `workshop-spaces`** (its D4 wording): environment override, then the space value (non-default spaces), then the baseline (non-default spaces) or the global value (`default` space). The baseline is the seeded defaults with preset `clean` applied. A `WORKSHOP_FLAG_<KEY>` override therefore reaches every space, while a changed global flag reaches only `default`.
- **Runtime orders have no user.** Both checkout paths create orders without `user_id` (`main.py:303-306`, `api/checkout.py:42-43`). The login order history (API-007 AC-6) therefore contains only seeded orders today.
- **Seeding after `reproducible-image` (its D4) is insert-if-missing.** Products, flags and users are inserted only when missing; a user's addresses, payment methods and order history are created only together with that user, and seeding renders no PDFs. Today's `seed_users` still deletes and recreates an existing user's history (`seeds/seed_data.py`), which D4 removes. For conformance, seeded order numbers are random and differ between containers, while seeded order ids (1–3, Jamie's two orders then Alex's) and product ids 1–12 are autoincrement values that follow fixture order only on a fresh database. Seeded order history is committed as one unit per user, so its `created_at` values can tie (D5 candidate API-007_AC-7).
- **Preset `clean` does not own every flag.** Today it sets the `LOCATOR_*`, `BUG_*` and `AI_*` flags but not `NEW_CART_UI`, `MOBILE_UI_V1` or `SEARCH_V2` (`api/workshop.py:35-47`). `drift-coverage` Decision 12 keeps this: `clean` owns the locator, bug and AI groups, and no preset owns those three flags. They change `cart.html:6-10`, `home.html:52-53` and the `/api/search` response (`api/search.py:18-25`). `workshop-spaces` D7 restores them to seeded defaults when the `default` space is reset; non-default spaces read them from the baseline unless an environment override sets them.
- **Planted bugs apply only to product cards today.** They act inside `templates/components/product_card.html:59-65`. The related and trending cards on the product detail page are rendered without flags today (`product_detail.html:92,106`). `drift-coverage` Decision 9 moves the triggers into registry helpers, so card bugs apply wherever the card macro renders: listing, home grids, related and trending cards, and search-result cards (its A3). `BUG_CHECKOUT_TOTAL` makes the displayed checkout total omit the tax. Preset `drift_and_bug` sets `LOCATOR_V4`, `BUG_WRONG_PRICE` and `BUG_CHECKOUT_TOTAL` and turns every other locator and bug flag off, so status reports `locator_stage` `v4` (Decision 12).
- **Order documents in the image** (`reproducible-image` D3): PDFs are written to `/data/pdfs` and served only through `/api/docs/orders/{id}/invoice.pdf` and `/summary.pdf`; `/static/pdfs/` does not serve them. The `documents` field of `POST /api/checkout/` lists the server paths `/data/pdfs/invoice_<order_number>.pdf` and `/data/pdfs/summary_<order_number>.pdf`; the file names are unchanged.
- **Detail-page recommendations** (`main.py:190-204`): related cards are same-category products, filled up to 4 from the name-sorted catalogue; trending cards are the first 4 remaining products by name. On `/products/1` the related ids are 10, 5, 12 and 8 and the trending ids 7, 2, 4 and 11.
- **Checkout validation is server-side only.** The checkout form is a native POST to `/checkout` (`checkout.html:27`). The length constraints exist only on the server (`main.py:259-261`). FastAPI answers validation errors and `HTTPException` on HTML routes with JSON bodies.
- **The empty-cart sentence appears twice.** `GET /checkout` with no items already shows "Your cart is empty. Add items before completing checkout." in the summary (`checkout.html:94-96`). After a submission, the same text appears in the `role="alert"` block (`checkout.html:14-16`).
- **The cart badge is hidden when empty.** Its text is empty and the element is hidden when the quantity is 0 (`app.js:115-131`, `styles.css:269-284`).
- **Visible text and accessible names differ.** Card and detail add-to-cart buttons show "Add to cart" but carry `aria-label="Add <product name> to cart"` (`product_card.html:99-105`, `product_detail.html:33-34`), which `drift-coverage` keeps stable. `/products/1` shows 5 buttons with that visible text (hero plus 4 related cards). The sign-in dialog's close button shows only "×" with `aria-label="Close login form"` (`base.html:150`). The logout label is split across lines in markup (`base.html:112-113`).
- **Catalogue pages render the same card macro several times, so `<article>` is ambiguous page-wide.** `/products` renders 18 `<article>` elements: the 12 cards of the section headed "All products", plus 6 mini preview cards in the section headed "Collections to explore" (`products.html:145-167` renders `cards.product_card(product, variant="mini", show_actions=False, …)` at line 159 for `categories[:4]` with up to 3 newest products each; with the seed set the four categories are Audio, Displays, Furniture and Health, giving Aurora (1), Echo (10), Horizon (7), Atlas (5), Pulse (3) and Cascade (12)). A mini card is an `<article>` with the product-name `<h3>`, image and price, but no add-to-cart button, no description and no rating (`product_card.html:72-105`), so `/products` shows 18 articles against 12 add-to-cart buttons and six product names match two articles each. `/products/{id}` likewise mixes card kinds: three static `<article class="feature-card">` elements under "Why you'll love it", up to 4 compact cards under "You might also like" and 4 mini cards under "Trending in the studio" (`product_detail.html:62-109`). `drift-coverage` keeps all of these. None of these catalogue `<section>` elements carries an accessible name, so they expose the role `generic`, not `region`, and they are located from their visible heading instead (D3). The one exception is the search results section, which `drift-coverage` (its task 8.1) gives `role="region"` with `aria-label="Search results"` in `home.html` and `products.html`.
- **The price sliders have no accessible names today.** Two `input type="range"` with `data-price-slider` markers sit inside the fieldset with legend "Price range"; the submitted values travel in the hidden inputs `price_min` and `price_max` (`products.html:100-117`). `drift-coverage` (Decisions 3 and 4, its task 8.1) gives them `aria-label="Minimum price"` and `aria-label="Maximum price"` and the stable ids `price-min-range` and `price-max-range`, identical in every stage, and removes every `data-price-*` attribute. After `drift-coverage`, the content data attributes stable in every stage are exactly `data-product`, `data-product-name`, `data-category` and `data-chat-prompt`; every other behavior-only `data-*` marker is gone in all stages, and `app.js` writes no `data-*` attributes or ids at runtime.
- **Search-result cards after `drift-coverage` A3** are rendered on the server by the hidden `GET /search/results?query=` with the product card macro, so drift and planted bugs apply to them. The extra icon-only add-to-cart button is dropped, so each result card has one "Add to cart" button.

## Goals / Non-Goals

**Goals:**
- Every in-scope criterion has an executable check that names its criterion ID and runs against any local or CI container by base URL, with a result per criterion.
- The checks cover the two ways the shop is used: the `default` space (local containers and CI service containers) and named workshop spaces (the shared fallback instance).
- Checks are isolated and independent of execution order. A failure therefore means that story and app disagree, or that the check is wrong. It never means that another check interfered.
- Locator drift changes no criterion result, and the heal-vs-hide preset breaks exactly the criteria registered for its bugs, so Module 8 can judge heals against the stories.
- Each audit outcome is recorded once, reviewed by a human, and reproducible from the tag commit.
- The gate reuses `reproducible-image`'s pipeline and tests the exact image digest that later receives the workshop tag.
- Story files can be converted downstream without leaking planted-bug, drift or conformance information.

**Non-Goals:**
- The other 19 source stories (WEB-001, WEB-008–011, API-001–004, API-008–011, AI-001–006).
- Per-stage conformance statuses: `CONFORMANCE.md` records decisions for the clean state only. Checking hook mappings, determinism and drift documentation stays with `drift-coverage`. The in-scope web criteria whose checks drive the rendered page are still checked in stages 2–4 and under `drift_and_bug` (D3).
- Verifying story notes, visual design, accessibility or performance beyond what a criterion states.
- Running checks against the shared Coolify instance, and load testing (owned by `workshop-spaces`).
- Browsers other than Chromium.
- Conformance records or gating for images published before the first workshop tag, and for `X.Y.Z`, `edge` and `sha-` images. On `main`, conformance runs only as a non-blocking signal (D6).
- Image-level checks of workshop tags (platforms, `sha-<short>` pointer, revision label, anonymous arm64 pull, `/health` version of the published tag): owned by `reproducible-image` task 10.5. This change checks gate behavior only.
- Converting the stories into OpenSpec specs, or any change in the participant repository.
- Robot Framework suites.

## Decisions

Four points were open assumptions in earlier drafts: C1, clarifications keep the criterion ID while a semantic change withdraws it (D1); C2, no new criteria except replacements for withdrawn ones (D5); C3, several planted-bug flags per criterion (D2, D5); and C4, the gate tests the pushed candidate digest (D6). The maintainer accepted all four, so they are decisions now, and their fallback plans are gone. The labels stay for reference.

### D1. Story set: one file per story in `docs/user-stories/`, source file names kept

- **Files:** `docs/user-stories/<STORY-ID>_<slug>.md`, using the source file names unchanged (e.g. `WEB-006_complete_checkout.md`, `API-005_cart_operations.md`). Comparing against the source commit is then a plain file diff.
- **Import:** verbatim, with one normalization: example base URLs change from `http://localhost:8000` to `http://localhost:9090`. Normalizations are listed in the index. They are not criterion statuses, because they do not change a criterion.
- **Scope follows the folder:** every top-level file in `docs/user-stories/` whose name matches `^(WEB|API|AI)-\d{3}_.+\.md$` is in scope. Adding a story file later automatically brings it under the guard (D4) and the gate (D6).
- **Index `docs/user-stories/README.md`:**
  - provenance: source repository, path, commit SHA, import date and normalizations
  - story table: ID, title, file, number of active criteria
  - ID rules
  - withdrawn criteria table: ID, version withdrawn, reason, replacement ID
  - interpretation rules
  - a "For downstream consumers" section (D7)
  - a pointer to `legacy/`
- **ID rules:**
  - A criterion is referenced as `<STORY>_<AC>`, e.g. `WEB-006_AC-7`. `AC-n` is unique within its story.
  - IDs are never reassigned. Removing a criterion always requires a withdrawn-table entry; the guard enforces this (D4 check 8).
  - A correction that keeps the verified behavior keeps the ID (`story-corrected`).
  - **Clarifications keep the ID (decided, C1):** a clarification that only makes a term already in the criterion precise, in line with the story's evident intent, keeps the ID and is recorded as `story-corrected` with a Revisions entry. Examples: a card's "price" is the product's price; "Order total" is subtotal plus shipping plus tax, with a "Complimentary" shipping line counted as 0. Rationale: downstream tests and prompts reference criteria by ID, and a clarification does not change what a consumer of the original criterion expected.
  - **A semantic change withdraws the ID (decided, C1):** any other correction that changes *what* is verified withdraws the ID. The replacement gets the next free number in that story: the highest active or withdrawn number plus 1. Whether a given correction is a clarification or a semantic change is decided per criterion in PR review (D5 step 7).
  - Withdrawn criteria are removed from the story file and listed in the index.
- **Revisions:** a story file gets a `## Revisions` section at its end on its first correction. Each entry records version, criterion, original wording, new wording and reason.
  - The reason in a Revisions entry, and in the index's withdrawn table, is written from the shopper's or API consumer's point of view. It never names or hints at a defect, feature flag, drift stage, locator stability, conformance status or detection purpose. Example: "clarified that the displayed price is the product's price", not "so that a wrong card price is detected". Any internal motivation goes only into the note of the criterion's `CONFORMANCE.md` row.
- **Story files stay neutral.** They never mention feature flags, planted bugs, drift stages, conformance status or test files. The guard's token check (D4 check 9) is a backstop, not proof of neutrality; paraphrases are caught in review (task 17.2).
- **Interpretation rules** (in the index, binding for checks and downstream conversion):
  - **Quoted UI text** in a criterion (the text on a button, link, heading or label) refers to the element's visible text (its rendered text content), not its accessible name. It is matched ignoring case, as a phrase contained in that text. Before comparing, leading and trailing whitespace is trimmed, and every run of whitespace (spaces, tabs, line breaks and indentation in markup) in both the quoted text and the element text counts as one space. Whitespace is never removed, so a word break matters. Examples:
    - "Add to Cart" matches a button whose visible text is "Add to cart", even though its accessible name is the more specific "Add Aurora Neural Headphones to cart".
    - "Tax" matches "Estimated tax".
    - "Log out" matches a label split in markup as "Log" + line break + "out".
    - "Logout" does not match "Log out".
  - **Accessible names** (aria-label, alt, associated label) are used only when a criterion speaks of a label or name, for form fields found by their label, or for a control without visible text, such as the "×" close button of the sign-in dialog. A difference between a quoted phrase and an accessible name is never a deviation and never a reason to change an accessible name.
  - **"An error message is displayed"** means a message that appears as a result of the action, in an alert-role element or next to the field. Text that was already on the page before the action does not count.
  - "e.g.", "or equivalent", example values and example requests or responses are not normative.
  - Notes are not normative. A test data table is normative only where a criterion refers to what it defines, such as credentials or the order number format.
- **Legacy:** the three existing files move with `git mv` to `docs/user-stories/legacy/`. Each gets a header note: superseded for the flows covered by WEB-002–007 and API-005–007, still the only description of the home page, AI helper and operations topics, and neither maintained nor gated.

Alternatives considered:
- **One file per area (legacy layout):** per-story diffs against the source and per-story conversion become harder.
- **Renaming files to a local convention:** breaks the one-to-one mapping to the source.
- **Storing stories as OpenSpec specs in this repository:** that is the downstream format. This repository's specs describe workshop capabilities, not shop features.
- **Importing all 28 stories now:** adds 138 criteria to audit that no current lab uses.
- **Matching quoted text against visible text or accessible name:** would make "Add to Cart" ambiguous between the hero and related-card buttons and invite checks that depend on names `drift-coverage` does not promise to keep in that exact form.

### D2. Conformance record `docs/user-stories/CONFORMANCE.md`

- **Sections:** one `## workshop-<id>` section per workshop image version, newest first. `X.Y.Z`, `edge` and `sha-` images get no section. During development the top section is `## Unreleased`; at most one `Unreleased` section exists, and it is always on top. Each section holds a complete table of all criteria active in that version.
- **Section header:** names the image tag, the image digest, the `sha-` tag and the story-set commit.
  - The digest (the `digest` output of the tag run's `build` job, which `publish` promoted) is the authoritative identifier of the image. `sha-<short>` is recorded for orientation only, because it is a moving per-commit pointer (`reproducible-image` D7).
  - The rename commit that gets tagged names the image tag and states that the `sha-` tag and story commit are those of the tagged commit.
  - The literal `sha-<short>` and the digest are added in one follow-up commit after the tag is published, because a commit cannot contain its own hash and the digest exists only after the tag run. That commit touches header lines only.
- **Table:** `| Criterion | Status | Flag | Note |`, sorted by story and criterion number.
  - `Flag` is filled only for `planted-bug`. It holds one or more flag keys, comma-separated (decided, C3; see D5).
  - `Note` holds one sentence plus a link to the commit, PR or change. It is required for `app-fixed`, `story-corrected` and `planted-bug`. It is optional for `conforms`, where it records a planted-bug flag that breaks the criterion incidentally (D5 step 5), and optional for `pending`, where it may name a spin-out change. Unlike `Flag`, a note is never forbidden by status.
- **Planted bugs without criterion:** a `### Planted bugs without criterion` subsection per version with the table `| Flag | Reason |`. The reason is one sentence plus a link to the PR in which the maintainer approved it.
- **Status semantics:** statuses are relative to the imported source text and carry forward to later versions until something changes for that criterion.
  - `conforms`: the app met the imported criterion without any change.
  - `app-fixed`: the application was changed to meet it. The note names the change and the version.
  - `story-corrected`: the criterion text differs from the source. The story's Revisions section holds the neutral reason, and the note holds any planted-bug motivation.
  - `planted-bug`: the criterion holds in the clean state and is violated while any listed flag is enabled.
- **Precedence** when several statuses apply: `planted-bug` > `story-corrected` > `app-fixed` > `conforms`. The note mentions the others. Facilitators first need to know which flag breaks a criterion. Consumers holding the source text next need to know that the text changed.
- **`pending`** is allowed only in `## Unreleased` while the audit runs, and after a release only for new criteria.
- **Release:** the tag commit renames `Unreleased` to `workshop-<id>`. Once the tag is published, that section's table and its "Planted bugs without criterion" table are frozen; its header lines may be completed once, in the follow-up commit. All earlier released sections are fully frozen.
- **After a release:** the first later change that affects the record opens a new `## Unreleased` section at the top as a full copy of the latest released table (statuses carry forward) and applies the change there. Changes that affect the record are: a story file, the index story or withdrawn tables, a `planted_bug` marker, or a row. The header-only follow-up commit does not count. Released tables are never edited; the guard checks the section structure (D4 check 4), and PR review checks that released tables are unchanged.

Illustrative rows (the actual outcomes are decided by the audit):
```
| WEB-006_AC-7 | story-corrected |                    | Order numbers are ORD- plus 8 hex characters, as in API-006_AC-2 (PR #…) |
| WEB-006_AC-1 | planted-bug     | BUG_CHECKOUT_TOTAL | Tax amount added to the summary by drift-coverage; total rule clarified (PR #…) |
```

Alternatives considered:
- **One table with a "since version" column:** cannot answer "status at version X" after later changes without reading git history, which is exactly the spec's lookup scenario.
- **Generating the record from test results:** a status is a decision about *why* a criterion holds. Results feed the audit, and the record keeps the decisions.
- **YAML or JSON:** facilitators read the record on GitHub. A Markdown table is still trivial for the guard to parse.
- **One file per version:** more files, and harder to compare versions.
- **A guard that compares released sections with git history:** the offline guard runs on temporary copies and CI checkouts are shallow. It can be added later as a separate CI step with full history.

### D3. Checks: a pytest suite in `backend/tests/conformance/`

**Layout and selection**
```
backend/tests/conformance/
  __init__.py
  conftest.py              # suite fixtures only: target, space modes, variants, sweep mode, report
  stories.py               # parser for story files, index and CONFORMANCE.md (shared with D4)
  helpers.py               # phrase(), control(), section() and other locator helpers, plus ConformanceSetupError
  test_stories_parser.py   # offline
  test_helpers.py          # offline
  test_story_coverage.py   # D4, offline
  test_harness.py          # live harness checks, marked conformance, no ac marker
  test_web_002_browse_product_catalogue.py   # one module per in-scope story (9)
  ...
```
- **Markers** are added to the `[tool.pytest.ini_options]` section that `drift-coverage` introduces, next to its `browser` marker:
  - `ac("<STORY>_<AC>")`: exactly one literal ID per check.
  - `planted_bug("<FLAG>")`: zero or more per check.
  - `conformance`: set as module-level `pytestmark` in every story module.
- **Default runs skip browser and live checks.** `drift-coverage` sets `addopts = "-m 'not browser'"`. This change extends that same `addopts` to exactly `addopts = "-m 'not browser and not conformance'"`, so both markers are deselected by default. `uv run pytest backend/tests` (the `check` job, which has no browsers and no target) then runs the unit, contract and offline guard tests. The live run is `uv run pytest backend/tests/conformance -m conformance`. The later `-m` overrides the one from `addopts`.
- **No app import at collection.** `backend/tests/conformance/conftest.py` imports nothing from `backend.app` at module level. The planted-bug registry and presets (`PLANTED_BUGS`, `build_presets`) are imported lazily inside the functions that need them.
- **Shared harness rules** (`reproducible-image` D11). The suite adds no database harness of its own and changes nothing in `backend/tests/harness.py` or the root `backend/tests/conftest.py`. Its conftest defines only suite fixtures (`base_url`, `space`, `api`, `space_page`, `prefill_cart`), never one named `temp_database`, `app_client`, `seeded_app_client`, `pdf_unavailable` or `fake_weasyprint`, and sets no environment variable of the pytest process. `backend/tests/conformance/` is a package (`__init__.py`), so its `test_harness.py` does not collide with `drift-coverage`'s `backend/tests/browser/test_harness.py`. Offline guard tests use `tmp_path` copies of the docs and need no app. Regression tests for app fixes live in the suite of the code they cover (task 5.1) and use the root fixtures by name.
- **Checks and criteria:** a criterion may have several checks, for example the valid and invalid inputs of WEB-006 AC-4. Each check verifies exactly one criterion, so the result per criterion is unambiguous.

**Target**
- The suite uses `drift-coverage`'s base-URL mechanism (its Decision 8). `backend/tests/conformance/conftest.py` overrides pytest-base-url's `base_url` fixture inside that directory, session-scoped because pytest-playwright's `browser_context_args` depends on it. It returns the `--base-url` option when given and `None` otherwise. No project-specific environment variable selects the target; the only source is that option, whose default pytest-base-url fills from its own `PYTEST_BASE_URL`.
- Unlike `drift-coverage`'s browser suite, the conformance suite never starts a server from source without the option: the spec requires checks against a running image. With no base URL it starts nothing; the first live fixture raises a `pytest.UsageError` naming `--base-url`, so every check that needs a target ends as an error in setup, before any request, so a run never falls back to whatever happens to listen on port 9090 — for example the developer source run that `reproducible-image`'s README documents there, which is not an image and would silently become the gated target. Offline guard and helper checks never request a live fixture and are unaffected. Every documented invocation therefore passes `--base-url` explicitly.
- `base_url` is not set in the ini file, because that would disable `drift-coverage`'s self-starting server.
- Non-loopback targets are refused unless `CONFORMANCE_ALLOW_REMOTE=1` is set. The rule applies to the resolved value, and the refusal is enforced by the `base_url` fixture itself, before any live fixture or browser context exists, so it fires for the `api`, `space_page` and browser-context fixtures alike and no request is ever sent. `CONFORMANCE_ALLOW_REMOTE` only permits a value, it never supplies one. Checks create spaces, carts and orders and, in `default` mode, reset global flags, so a shared instance must not be hit by accident.

**Space modes** (`CONFORMANCE_SPACE_MODE=per-check|default`, default `per-check`)
- **`per-check`:** a function-scoped space per check.
  1. The space id is `cf-<6 hex characters of a run id>-<4-digit counter>`, which is valid in the GitHub-handle format from `workshop-spaces`.
  2. Every request carries `X-Workshop-Space: <space>`: the `api` client, and the browser context through `context.set_extra_http_headers`.
  3. The precondition also requires status `space` to equal the id.
- **`default`:** the space participants use locally and in CI service containers.
  1. No `X-Workshop-Space` header is sent by the API client or the browser context. An explicit `default` is not sent either, because participants send no header.
  2. Before the first reset of a run, the fixture reads status once. A planted bug, a stage other than `v1`, or one of `NEW_CART_UI`, `MOBILE_UI_V1` and `SEARCH_V2` already enabled raises `ConformanceSetupError` for the run: the default-space reset restores global flags (`workshop-spaces` D7) and would otherwise silently repair a misconfigured target.
  3. A 401 from reset means shared mode is on; it raises `ConformanceSetupError` naming `WORKSHOP_SHARED_MODE`.
  4. The precondition also requires status `space` to equal `default`.
  5. Runs are serial. The fixture stops with a `pytest.UsageError` under parallel workers (e.g. pytest-xdist).
- **Checks in both modes** never depend on whether the space indicator `[data-workshop-space]` is present; it exists only in named spaces.

**Setup per check** (function-scoped, both modes)

**Harness failures are never assertions.** `helpers.py` defines `class ConformanceSetupError(Exception)`. Every setup, precondition, teardown and usage failure of a suite fixture raises it (or `pytest.UsageError` for a misconfigured invocation); a fixture never signals failure with `assert`, a Playwright `expect(...)` or any other `AssertionError`. Reason: pytest evaluates an `xfail(raises=...)` mark before fixtures run and applies it to the setup *and* teardown phases, so an `AssertionError` raised by a fixture in a `[<FLAG>]` variant or a marked `[drift_and_bug]` variant would be reported as XFAIL — exactly the outcome those variants expect — and the report would count a misconfigured target as a passing criterion. `ConformanceSetupError` does not match `raises=AssertionError`, so such a check ends as a pytest ERROR in every variant, marked or not. `AssertionError` is reserved for check bodies.

1. `POST /api/workshop/reset`.
2. `POST /api/workshop/preset` with `clean`, raising `ConformanceSetupError` unless the response reports `"status": "success"`.
3. The variant's own step (see Variants): a stage preset or `drift_and_bug`, or `POST /api/workshop/flags` with body `{"flags": {"<FLAG>": true}}`.
4. **Precondition:** `GET /api/workshop/status` must report the variant's expected `locator_stage`, `active_bugs` equal to the variant's bug set, and `NEW_CART_UI`, `MOBILE_UI_V1` and `SEARCH_V2` disabled. If not, the fixture raises `ConformanceSetupError` naming the flag, so the check ends as a pytest *error* in every variant, including the xfail-marked ones, not as a criterion failure. This enforces the spec's clean-state definition: a misconfigured target (environment overrides, changed global flags) is reported, never silently repaired and never mistaken for a story deviation. `drift-coverage` Decision 12 leaves those three flags outside every preset, so conformance checks them instead of setting them. Under the `workshop-spaces` precedence (Context), an environment override such as `WORKSHOP_FLAG_BUG_WRONG_PRICE=true` shows up in every space and fails this precondition in both space modes for every variant whose expected bug set does not contain the overridden flag — `clean`, the stage variants and every other flag variant — so a run against such a target always reports setup errors and never a criterion failure (spec scenario "Target not in clean state"). A variant that enables the overridden flag itself, i.e. `drift_and_bug` for `BUG_WRONG_PRICE` or `BUG_CHECKOUT_TOTAL` and that bug's own `[<FLAG>]` variant, sees exactly its expected set and is caught only by the `default` mode's pre-run check, which also catches a globally changed flag.
5. Teardown calls reset again, raising `ConformanceSetupError` if that fails — a teardown `assert` would be swallowed by the xfail mark entirely.

Why a space (or a reset) per check rather than per test session: API-005 AC-1, AC-8 and AC-10 must use the fallback session `workshop-demo` without `X-Session-ID`, API-007 AC-6 counts orders, and WEB-006 AC-9 needs an empty cart. Per-check isolation makes every check independent of order. In `per-check` mode it also allows parallel runs later without redesign. The `default` pass exercises the paths that differ there: global flag writes, legacy cart keys (`workshop-demo` shared by anonymous API callers), orders with `space = 'default'`, the default branch of reset, and pages without the space indicator.

**Variants** (`pytest_generate_tests` in `conftest.py`)
- **`clean`:** every check.
- **`stage2`, `stage3`, `stage4`:** every check that uses the `space_page` fixture, i.e. the UI checks of the `test_web_*` modules. Expected stage `v2`–`v4`, no active bugs, expected to pass. API checks (including API-based checks inside web modules, such as WEB-005 AC-8) get no stage variants, because drift is template-only; the spec requirement "Drift-stage conformance" scopes the stage and `drift_and_bug` presets to exactly the criteria whose checks drive the rendered page.
- **`drift_and_bug`:** every check that uses `space_page`. Expected stage `v4` (`drift-coverage` Decision 12: `LOCATOR_V4` on, every other locator flag off) and the bug set that `build_presets()["drift_and_bug"]` enables (`BUG_WRONG_PRICE` and `BUG_CHECKOUT_TOTAL`). Stage 4 removes `data-test`, covered ids and classes in the same flows as the bugs, while roles, names and visible text stay, so a check that passes here is judged on behavior only. A check whose `planted_bug` markers intersect that bug set is `xfail(strict=True, raises=AssertionError)`. Every other check must pass.
- **`<FLAG>`:** one per `planted_bug` marker, in every module. Expected stage `v1` and exactly that bug active. Marked `xfail(strict=True, raises=AssertionError)`: it must fail with an assertion. A pass (strict XPASS) or any other exception fails the run.
- Presets are applied after `clean` because stage presets no longer clear bugs (`drift-coverage` Decision 12).
- Test IDs look like `test_ac_1_order_summary[clean]`, `[stage3]`, `[drift_and_bug]` and `[BUG_CHECKOUT_TOTAL]`.

**API checks**
- A function-scoped `httpx.Client` with the base URL, the space header in `per-check` mode, and a 10-second timeout.
- `X-Session-ID` is sent only where the criterion uses it.

**UI checks**
- pytest-playwright sync `page`, Chromium, headless.
- A function-scoped fixture sets the space header with `context.set_extra_http_headers` in `per-check` mode. pytest-playwright's `browser_context_args` is session-scoped and cannot carry a space per check.
- **Arrange through the API, act and assert through the UI.** A cart is prefilled by setting the context's `session_id` cookie to a generated value and calling `/api/cart/items` with the same `X-Session-ID`. The exception is a criterion about the UI action itself (WEB-005 AC-1, AC-2, AC-9).
- **Locators** use roles, accessible names, labels and visible text, which is the stable surface of `drift-coverage`'s stage contract. They never use ids, classes or `data-test`. A check therefore never encodes a locator hook the workshop changes on purpose.
  - Quoted UI text goes through `phrase()` against visible text: `get_by_role(<role>).filter(has_text=phrase(...))` (wrapped as `control(scope, role, text)`) or `get_by_text(phrase(...))`. It is never passed as the `name=` of `get_by_role`.
  - `get_by_role(..., name=...)` and `get_by_label(...)` are used for criteria about labels or names, for form fields found by their label, and for controls without visible text (e.g. the dialog's close button).
  - Lookups are scoped to the container the criterion names, because a page shows several buttons with the same text and repeats the same product in more than one card (Context), and strict mode rejects an unscoped action. They never rely on `.first` or `.nth` to pick among equal controls:
    - **a named section:** `section(page, "<heading text>")` in `helpers.py` returns the section that holds the heading with that visible text, located from the heading itself: `page.get_by_role("heading", name=<text>, exact=True).locator("xpath=ancestor::section[1]")`. It uses no id, class or `data-test` (`locator("section")` would also be allowed as a tag selector, but the nearest-ancestor step is what keeps the enclosing layout `<section>` out of the match), and it is stable in every stage, because `drift-coverage` freezes visible text, roles, accessible names and content order and its stage-4 structural variants wrap only product cards, the detail-page purchase actions and the checkout form fields, never headings. The catalogue sections carry no accessible name, so `get_by_role("region", name=…)` would match nothing (Context);
    - **a product card:** `<container>.get_by_role("article").filter(has=get_by_role("heading", name=<product name>))`, where `<container>` is the section the criterion names, never `page`; product names come from the story's test data. On `/products` catalogue cards are the cards in `section(page, "All products")` (12 cards, one add-to-cart button each); the six mini cards in `section(page, "Collections to explore")` repeat six of those products without a button, description or rating, so an unscoped article locator matches 18 elements and six product names match two articles each (Context);
    - **the product detail action area:** the container holding the `h1` with the product name, excluding the cards under "You might also like" and "Trending in the studio". Related cards are the cards inside `section(page, "You might also like")`, never the three static "Why you'll love it" feature `<article>` elements or the trending mini cards (Context);
    - **a search-result card:** the same card scope inside the results region, `get_by_role("region", name="Search results")`, which `drift-coverage` (its task 8.1) names in `home.html` and `products.html`; on `/products` that region is shown next to the "All products" grid and the previews, so search criteria never look at the page as a whole.
  - Controls without visible text are found by role and accessible name within the container the criterion names. The two price sliders are `get_by_role("slider", name="Minimum price")` and `name="Maximum price"` inside the group named "Price range"; `drift-coverage` keeps those names identical in every stage (Context). An element that has neither visible text nor an accessible name is found by role and document order within its named group, never by id, class or `data-*` marker.
- **Network criteria** (WEB-004 AC-5, WEB-005 AC-1, and WEB-004 AC-4 as imported) use `page.expect_request`. Request predicates match the path exactly, so `/api/search/suggest` cannot satisfy a criterion about `/api/search`.

**Assertions and evidence**
- Everything observable is asserted with web-first `expect(...)`, including the preconditions of actions (assert the button is visible before clicking it). Defects then surface as `AssertionError`. Infrastructure problems (navigation errors, action timeouts) surface as other exceptions. The planted-bug variants rely on this distinction. Fixtures are excluded from it: they raise `ConformanceSetupError` (see "Setup per check"), so `AssertionError` comes only from a check body.
- **No automatic reruns** (no pytest-rerunfailures). A rerun inside a release gate hides flakiness. Failures produce evidence instead: `--tracing retain-on-failure` and `--screenshot only-on-failure`, uploaded by CI.

**Bug sweep mode (audit only)**
- With `CONFORMANCE_SWEEP_FLAG=<FLAG>`, which must name a registry flag, every check runs once in its `clean` setup with that flag enabled, without xfail.
- With `CONFORMANCE_SWEEP_PRESET=drift_and_bug`, every check runs once with that preset applied after `clean`, without xfail.
- The report lists the criteria the flag or preset breaks (D5 step 5).

**Report**
- A small plugin in `conftest.py` aggregates results per criterion ID from the `ac` markers.
- It writes `conformance-report/<space mode>/report.json` and `report.md` (git-ignored), with criterion, result (`pass`, `fail` or `error`), the checks involved and the verified variants (`clean`, stages, `drift_and_bug`, flags). It also prints a terminal summary and records the ID as a JUnit property for `--junitxml`.
- Checks without an `ac` marker — the live harness checks of `test_harness.py` — are listed with their own result under a `Harness` heading of `report.md` and in the terminal summary, never as a criterion. The CI step summary reads that section (D6 step 7), so a failing harness check is visible without being attributed to a criterion.
- A criterion passes when every variant behaves as expected: `clean` and stage variants pass, and flag variants and marked `drift_and_bug` variants xfail. A setup, precondition or teardown error in any variant — the xfail-marked flag and `drift_and_bug` variants included — gives `error`, which counts as not passing, and a run with at least one `error` exits non-zero, so it fails the CI step and blocks `publish`.
- The report header contains the base URL, the space mode and the `version` from `/health`.
- A criterion passes the gate only if it passes in the reports of both space modes.

Alternatives considered:
- **Robot Framework suites:** would publish ready-made lab solutions (excluded by the spec).
- **One space per test session:** default-session and order-count criteria become order-dependent.
- **A fresh container per check:** the strongest isolation, but minutes per check.
- **In-process FastAPI `TestClient`:** does not exercise the image or the client-side script, and the spec requires checks against a running image.
- **A `pytest.raises` wrapper instead of strict xfail:** same effect, but duplicates check bodies and hides the variant in reports.
- **Playwright Test in TypeScript:** a second toolchain in a Python and uv repository.
- **Only named spaces:** certifies the clean state in a mode local participants never use.
- **One CI leg per preset:** more containers and duplicated setup. Variants inside one run keep one report per space mode.
- **Stage variants for API checks:** drift changes templates only, so they would only add runtime.

### D4. Offline coverage guard

`test_story_coverage.py` needs no server and is not marked `conformance`, so it runs in every `pytest backend/tests`. Its rules live in `stories.py` as `check_*(docs_root, tests_root)` functions, so they also run on temporary copies. It checks:
1. **Story headings:** story files within the D1 scope contain well-formed `### AC-<n>: <title>` headings, and IDs are unique per story.
2. **No reuse:** no ID from the index's withdrawn table appears as a heading.
3. **Marker coverage:** story modules are scanned statically with `ast` for `pytest.mark.ac(...)` and `pytest.mark.planted_bug(...)`.
   - Only literal arguments are allowed, which keeps the scan independent of `-k` or `-m` selection.
   - Every active ID is referenced at least once, and every referenced ID exists (this catches typos).
   - Every story module has a module-level `conformance` mark.
4. **Record completeness and structure:**
   - At most one `## Unreleased` section exists, and if it exists it is the top version section. No released section contains `pending`.
   - The top section has exactly one row per active criterion and no rows for unknown or withdrawn IDs.
   - Every status is from the allowed set, and `pending` appears only under `Unreleased`.
   - `Flag` is filled exactly for `planted-bug`. `Note` is non-empty on every `app-fixed`, `story-corrected` and `planted-bug` row, and is not constrained on `conforms` or `pending` rows, which may carry a note or leave it empty. A `Flag` cell may hold several comma-separated flag keys (C3); each key is checked on its own by check 5.
5. **Planted-bug consistency and completeness:**
   - Each criterion's flags in the record equal the `planted_bug` markers on its checks. Every flag exists in `drift-coverage`'s planted-bug registry (`backend/app/core/workshop.py`, imported lazily).
   - Every row in "Planted bugs without criterion" names a registry flag that appears in no row, and has a non-empty reason with a link.
   - **Completeness** (once the top section has no `pending` rows, and always in release mode): every flag in `PLANTED_BUGS` appears either in the `Flag` cell of at least one `planted-bug` row or in "Planted bugs without criterion", never in both and never in neither.
   - **Heal-vs-hide coverage** (same condition): every `BUG_*` flag that `build_presets()["drift_and_bug"]` enables appears in at least one `planted-bug` row and not in the no-criterion list.
6. **Index consistency:** the index lists exactly the story files present, with their active-criteria counts.
7. **Release mode:** when `CONFORMANCE_RELEASE=<tag>` is set, the top section must be named exactly `<tag>` and contain no `pending`.
8. **No silent removal:**
   - (a) Released IDs: every criterion ID in a row of any released version section (every version section other than `Unreleased`) must be an active heading in its story file or listed in the withdrawn table.
   - (b) No gaps: for each story, the active AC numbers together with the story's withdrawn numbers form exactly 1..max, where max is the highest active or withdrawn number.
   - The guard cannot see removal of the highest-numbered criterion before the first release, rows deleted from frozen sections, or edited released tables. Those stay with task 17.2's `git diff` against the import commit and with PR review. Rule (a) protects only IDs whose version sections are kept; the withdrawn table is the durable list.
9. **Decision records:** every `story-corrected` row has a Revisions entry for that criterion; every Revisions entry names a criterion that is withdrawn or `story-corrected` or `planted-bug`; every withdrawn ID's replacement exists as a heading; story files contain none of the tokens `BUG_`, `LOCATOR_`, `planted`, `drift` (case-insensitive), `CONFORMANCE.md` or `backend/tests`.

Alternatives considered:
- **Reading markers from `request.session.items` at runtime:** gives wrong results when only a subset is selected.
- **A separate CI script:** a second place to maintain the same rules.
- **A JSON mapping from IDs to tests:** a second source of truth next to the markers.
- **An import-baseline list of IDs for rule 8:** a second source of truth; the no-gaps rule covers the same cases offline.

### D5. Audit procedure and triage rules

**Procedure** (the tasks run steps 2–4 per story):
1. **Import:** import the stories (D1) and commit them as the baseline. `CONFORMANCE.md` gets `## Unreleased` with every row set to `pending`.
2. **Write checks from the story text, before looking at app output.** Ambiguities are resolved by the interpretation rules or a clarification in the index, never by reading the implementation. Otherwise checks encode current behavior instead of the story.
3. **Run:** against an image built from `main` after `reproducible-image`, `workshop-spaces` and `drift-coverage` have merged (`compose.yaml` or `edge`), in both space modes and with all variants.
4. **Triage each failing criterion:**
   - First rule out a defect in the check. A wrong check is fixed and gets no status. A check that fails only because a control's accessible name differs from its visible text, or because it relies on a hook that drift changes, has a defect in the check.
   - A failure that happens only in a stage or `drift_and_bug` variant is a drift defect in the app, fixed in the drift layer under `drift-coverage`'s contract and recorded as `app-fixed` with a note naming the stage. It is `story-corrected` only if the criterion names a hook that drift changes, and never `planted-bug`.
   - Otherwise choose exactly one outcome from the table below.
   - Record the row in `CONFORMANCE.md`, a Revisions entry for story corrections, and the commit or PR link.
5. **Bug sweep:** one run per registered planted-bug flag (D3 sweep mode), plus one run with preset `drift_and_bug`.
   - Mappings that need a clarification (see "No new criteria" below) are proposed before the sweep, even when the sweep shows no break, because a check that is not yet clarified cannot break. After the clarification is applied, the sweep is rerun for those flags.
   - For each criterion a flag breaks, decide whether the criterion is meant to catch that bug. If so, add a `planted_bug` marker and set the status to `planted-bug`. If the break is incidental, add a note only. The row keeps its status, so after close-out (step 6) it is a `conforms` row carrying a note, which D4 check 4 allows.
   - For the flags that preset `drift_and_bug` enables, an incidental break is not left as a note, because the `drift_and_bug` variant must fail exactly on registered criteria. The break either becomes a registered `planted-bug`, or, where the criterion does not concern the affected product, the check arranges its data so the bug's trigger does not apply.
   - The failing set of the `drift_and_bug` sweep must equal the union of the per-flag sweeps for its flags. Any difference goes into the sweep PR.
   - Bugs that no in-scope criterion detects are listed under "Planted bugs without criterion" with a reason. This is allowed only for bugs that preset `drift_and_bug` does not enable (today, for example, `BUG_SLOW_RESPONSE`). The heal-vs-hide bugs must be detectable (D4 check 5).
   - Candidate mappings to confirm:
     - `BUG_CHECKOUT_TOTAL` → WEB-006 AC-1, once "Order total" is clarified
     - `BUG_MISSING_BUTTON` → WEB-002 AC-1
     - `BUG_WRONG_PRICE` → WEB-002 AC-1, once "price" is checked against the product's price
     - `BUG_BROKEN_LINKS` → WEB-003 AC-5, because `drift-coverage` Decision 9 applies card bugs to the related cards on the detail page. It shows only on pages whose related cards include an id divisible by 4: on `/products/1` the related cards include 8 and 12, while on `/products/12` no related card is affected.
     - WEB-004 AC-3 and AC-8 for all three card bugs: with `drift-coverage` A3, search-result cards use the card macro, so whether a bug shows depends on the query (ids divisible by 3 for the price, by 5 for the button, by 4 for links). The test-data queries `headphones` and `aurora` probably return only product 1, which triggers none.
     - `BUG_SLOW_RESPONSE` → no in-scope criterion
   - **Detectability on detail pages:** with the 12 seed products, no trending card on any detail page has an id divisible by 3, and WEB-003 AC-5 requires no button. So WEB-003 AC-6 cannot detect `BUG_WRONG_PRICE`, and WEB-003 AC-5 cannot detect `BUG_MISSING_BUTTON`. A wrong price on a related card (Cascade Water Bottle, id 12, on `/products/1`) is covered by no criterion; covering it would need a new criterion, which this change does not add (C2).
6. **Close out:** rerun until clean runs, stage variants and planted-bug variants behave as expected in both space modes. Remaining `pending` rows become `conforms`.
7. **Human decision:** the maintainer approves every outcome in PR review. An agent may run steps 2–5 and propose outcomes, but does not decide them ("agents draft, humans decide").

**Triage rules**

| Outcome | Choose when | Constraints |
|---|---|---|
| `story-corrected` | The story over-specifies incidental detail (format of generated identifiers, exact wording beyond the interpretation rules, static strings, response fields nobody relies on), contradicts another in-scope story, or requires a locator hook (id, class, data attribute) that drift stages change by design | Keep the ID if the verified behavior is unchanged or the correction is a D1 clarification, otherwise withdraw and replace (D1). The Revisions entry keeps the original wording and a neutral reason (D1) |
| `app-fixed` | The story describes sensible shopper-facing or API-consumer behavior the app lacks or gets wrong, and the fix takes about half a day or less | No renaming of cross-change contract names (endpoints, flags, presets, env vars). No fix that undoes a sibling change's decision (e.g. `drift-coverage` A3, server-rendered search results, or `workshop-spaces` D3, cart and checkout APIs that read only the `X-Session-ID` header); such a deviation goes to `story-corrected` or a spin-out. Accessible names kept stable by `drift-coverage` (e.g. "Add <product> to cart") are never removed or changed to satisfy a text criterion. Fixes in covered flows keep `drift-coverage`'s contract: markup through `drift.id`/`drift.cls`/`drift.test` with `StageSpec` entries and docs rows, except the shared uncovered blocks `form-field` and `button`/`button--*`, which stay written literally beside the covered hook and never become covered names (`drift-coverage` design Decision 3), new render states in `COVERED_PAGES`, no new element carrying the `role="status"` attribute (the add-to-cart confirmation stays the only one on every page; a live count uses `aria-live="polite"` without that role, validation messages use `role="alert"` or `aria-describedby` text), JS bound only to stable hooks (roles, ARIA relationships, form field names, link targets and the content data attributes `data-product`, `data-product-name`, `data-category`, `data-chat-prompt`) with no behavior-only `data-*` marker and no runtime `data-*` or id writes, and HTML error or validation pages rendered from routes that declare `workshop_view`, never from global exception handlers (the `drift`/`bugs` globals raise there, and a global handler would change the JSON errors API stories expect). Prefer a story correction for pure wording differences, because visible text is the baseline of the drift contract and of workshop materials. Exception: the app contradicts itself |
| `planted-bug` | The deviation is a realistic, deterministic defect in a workshop flow that is valuable to detect in Modules 7 and 8 | The clean state gets the correct behavior. The deviation moves behind a new `BUG_*` flag in `drift-coverage`'s registry (`PLANTED_BUGS`: flow, trigger, defect), disabled by `clean` and enabled by `buggy`, with a row in the `## Planted bugs` table of `docs/WORKSHOP-FEATURES.md`, never a separate table. This change then adds a `specs/planted-bugs/spec.md` delta for the new bug, which requires `drift-coverage` to be archived first (Migration Plan). Facilitators of the workshop repository are told the flag name |
| spin-out (not a status) | An app fix would take more than about half a day | A separate OpenSpec change. The workshop tag waits for it, because the gate blocks. An interim story correction needs explicit maintainer sign-off and a note naming the pending change |

**No new criteria (decided, C2):** this change adds criteria only to replace withdrawn ones. To make registered bugs detectable, existing criteria may be *clarified* where their intent already covers correctness (D1 clarification rule, C1), recorded as `story-corrected` with the ID kept. Examples: "price" on a card means the product's price (WEB-002 AC-1), and "Order total" equals subtotal plus shipping plus tax, with a "Complimentary" shipping line counted as 0 (WEB-006 AC-1). If review judges a proposed change to be semantic rather than a clarification, the D1 ID rules apply: the criterion is withdrawn and its replacement carries the correctness rule. The bugs that preset `drift_and_bug` enables are never left without a criterion. Rationale: the imported set stays the one the workshop labs use, so downstream material does not have to learn criteria that exist only for planted bugs, and the audit stays bounded.

**Several flags per criterion (decided, C3):** the `Flag` column may list more than one flag key, comma-separated, each with its own `planted_bug` marker and variant. The spec requires the flag key of each planted bug that produces a criterion's deviation. Rationale: among the WEB-002 and WEB-003 criteria, `BUG_MISSING_BUTTON` and `BUG_WRONG_PRICE` both rely only on WEB-002 AC-1, with WEB-004 AC-3/AC-8 possible depending on the search query; one flag per row would leave one of them without its natural criterion. Each flag variant runs on its own, so a criterion recorded with two flags must fail under each of them separately.

**Candidate deviations** (found by reading; the audit confirms or rejects each)

| Criterion | Story expects | App today (evidence) | Likely outcome |
|---|---|---|---|
| WEB-002_AC-3 | Price range minimum corresponds to $39.50 | Slider bounds are rounded: `min="40"`, label `$40` (`products.html:106-113`) | app-fixed |
| WEB-002_AC-6, AC-9 | Filtered grid matches all selected criteria, and the product count reflects the results | On page load `syncOutputs` writes the slider value 40 into the hidden `price_min` (`app.js:1028-1035`), so every "Apply filters" excludes Insight Smart Notebook ($39.50). There is no product count element (`products.html:168-181`) | app-fixed (a live count uses `aria-live`, never `role="status"`) |
| WEB-003_AC-3 | Add to Cart button carries a data attribute such as `data-product-id` | `data-product` (`product_detail.html:33`). The criterion names a locator hook | story-corrected (verify that the right product is added) |
| WEB-003_AC-9 | Error or 404-like page for an unknown id | `/products/9999` returns JSON `{"detail": "Product not found"}` (`main.py:185-188`). `/products/abc` returns a JSON 422 | app-fixed: the `/products/{product_id}` route takes the id as a string, parses it itself and returns an HTML not-found template with status 404 while `workshop_view` is active; no global exception handler |
| WEB-004_AC-4 | The frontend calls `/api/search` with the query parameter (test data: `q`), and the API returns matching products | Today `app.js:308` calls `/api/search/?query=`; the API ignores `q` (`api/search.py:15`). With `drift-coverage` A3, `app.js` loads results as an HTML fragment from the hidden `GET /search/results?query=` and no longer calls `/api/search` (`drift-coverage` Decision 6, tasks 9.1/9.2). `/api/search/?query=` still returns matching products | story-corrected by withdrawal and replacement (D1): WEB-004_AC-4 is replaced by WEB-004_AC-9. The maintainer picks the wording: (a) `GET /api/search` with the `query` parameter returns matching products, checked with httpx; or (b) endpoint-neutral: submitting requests results from the server with the query value and matching products are shown, without naming the hidden route. App fixes are excluded: client-side rendering from `/api/search` would undo A3, and serving the fragment under `/api/search` would change an API contract |
| WEB-004_AC-5 | Suggestions are an array of strings (test data) | `{"results": [{id, name, price, category}]}` (`api/search.py:36-45`). Requests start at 2 characters (`app.js:1140`) | story-corrected |
| WEB-005_AC-2 | Badge visible in desktop and mobile navigation | The badge sits inside the collapsible menu and stays hidden on mobile until the menu opens (`base.html:38,67`) | story-corrected |
| WEB-005_AC-8 | Cart API session comes from the `X-Session-ID` header or the `session_id` cookie | Both `/api/cart` and `/api/checkout` read only the header (`api/cart.py:19-20`, `api/checkout.py:21-22`). Pages read header, then cookie (`main.py:78-81`). `workshop-spaces` D3 decides this split on purpose: APIs read the `X-Session-ID` header only, and without it use the fallback session `workshop-demo` of their space. `workshop-spaces` does not cover a cookie-only API call, so this criterion's cookie-only case is the check that guards it. `app.js` sends the cookie's value as `X-Session-ID`, so the shop's own cart calls share the page's cart | story-corrected, aligned with `workshop-spaces` session resolution: the cart API takes the session from the `X-Session-ID` header, and without it uses `workshop-demo`; the `session_id` cookie identifies the cart for pages only. Whether the ID is kept or withdrawn follows the D1 ID rules. An app fix that makes the APIs read the cookie is excluded, because it would undo `workshop-spaces` D3 (triage table) |
| WEB-006_AC-1 | Summary shows a tax amount and the order total | "Calculated after address", and the total equals the subtotal (`checkout.html:97-114`) | app-fixed by `drift-coverage`, planted-bug `BUG_CHECKOUT_TOTAL` |
| WEB-006_AC-4 | Visible email error, and submission is blocked | Only native `type=email` (`checkout.html:36`): the browser shows a tooltip and there is no message in the DOM. `a@b` passes the browser, fails `EmailStr` and returns a JSON 422 (`main.py:260`) | app-fixed, together with AC-5, AC-6 and AC-11 |
| WEB-006_AC-5, AC-6, AC-11 | Message per field, and the shopper stays on checkout | No `minlength` (`checkout.html:42,50`). The server's `Form(min_length=…)` returns a JSON 422 as a new page (`main.py:259-261`) | app-fixed (timebox risk): `POST /checkout` validates the fields inside the handler and re-renders `checkout.html` with per-field messages built from drift hooks (`for`/`aria-describedby` targets through `drift.id`); no `RequestValidationError` handler |
| WEB-006_AC-7 | `^ORD-\d{4,}$` | `ORD-` plus 8 uppercase hex characters (`order_service.py:54`), consistent with API-006 AC-2 | story-corrected |
| WEB-006_AC-9 | Cart badge shows 0 | The badge is empty and hidden at 0 (`app.js:115-131`, `styles.css:269-284`) | story-corrected |
| WEB-007_AC-1 | "Sign in" button in the header | The header button says "Log in" (`base.html:90`), while the modal's title and submit button say "Sign in" (`base.html:151,168`) | app-fixed (app contradicts itself) or story-corrected |
| WEB-007_AC-7 | "Logout" button | "Log out" (`base.html:112-113`) | story-corrected: not whitespace-equivalent under D1 |
| API-005_AC-1, AC-8, AC-10 (and WEB-005_AC-8, "neither" case) | `"session": "workshop-demo"` without the header | Holds today in `default`. `workshop-spaces` D3 stores the fallback cart as `<space>:workshop-demo` in named spaces and reports `session` from `cart_session_id` (`session_label`), unprefixed, from `GET /api/cart/`, `POST /api/cart/items` and `DELETE /api/cart/` in every space | conforms; a mismatch is a defect in `workshop-spaces`' implementation and is fixed there |
| API-006_AC-6 | Two document paths for the created order | Inside the image, `documents` lists `/data/pdfs/invoice_<order_number>.pdf` and `/data/pdfs/summary_<order_number>.pdf` (`reproducible-image` D3); the file names are unchanged | conforms if the criterion concerns file names; story-corrected (neutral reason) if it names a `static/pdfs` location |
| API-007_AC-2 | Expiry about 4 hours after the current UTC time | A naive UTC datetime without an offset (`api/auth.py:58`) | conforms by interpretation, or app-fixed (explicit offset) |
| API-007_AC-4 | Addresses in the order Home, Studio | The relationship has no `order_by` (`models/user.py:16`) and relies on insertion order | conforms; app-fixed (`order_by`) if unstable |
| API-007_AC-7 | Most recent order first | Seeded `created_at` values are set at insert time. Seeding in one transaction (`reproducible-image` D4) could produce equal timestamps | conforms; app-fixed (explicit seeded timestamps) if they are equal |

Findings outside criteria (no status, fix optionally):
- The login form is `novalidate` (`base.html:153`). An empty email yields a 422 whose `detail` is a list, and the modal shows "[object Object]" (`app.js:386`). Only a test data row in WEB-007 mentions this case.
- The price sliders have no accessible names today (`products.html:110-113`). No WEB-002 criterion requires them, and `drift-coverage` (its task 8.1) already names them "Minimum price" and "Maximum price" identically in every stage, so no follow-up is needed.
- Notes in the source stories that are false for this app are corrected together with their story, without a status.

Alternatives considered:
- **Always fix the app:** turns the audit into open-ended feature work and changes the visible text the drift baseline and workshop materials depend on.
- **Always correct the stories:** the stories would drift toward whatever the app does, which defeats their role as judge.
- **Pre-deciding outcomes in this design:** the table above lists candidates only. Outcomes need a run and a review.
- **ADDED-only `planted-bugs` deltas (no MODIFIED "Bug registry"):** avoid the archive-order dependency, but the "Buggy preset" and "Stage preset keeps active bugs" scenarios would not list the new key.

### D6. CI gate in `.github/workflows/image.yml`

This builds on `reproducible-image` D7 and on `drift-coverage`'s `test` job (its Decision 16). `build` builds `linux/amd64` and `linux/arm64` once and pushes the candidate by digest with no tag; verification jobs run against that digest; `publish` creates `sha-<short>`, `edge`, `X.Y.Z` and `workshop-<id>` with `docker buildx imagetools create` only after every verification required for the ref has passed. The job graph is `check` → `build` → (`smoke` matrix, `test`); `smoke` → `conformance`; (`build`, `smoke`, `test`, `conformance`) → `publish`. The gate is one of the verifications required for workshop tags under the `workshop-image` capability.

**New job `conformance`**
- `needs: [build, smoke]` — deliberately a second verification stage rather than a sibling of `smoke` and `test`: the gate runs only on a candidate `smoke` has already verified, so a candidate that fails `smoke` never spends two 45-minute legs. It runs for `refs/tags/workshop-*`, for pushes to `main` and for `workflow_dispatch`, never for pushed `vX.Y.Z` tags or pull requests. Runner `ubuntu-24.04` (amd64). Permissions `contents: read` and `packages: read`.
- A matrix over `space_mode: [per-check, default]` with `fail-fast: false`. Each leg starts its own container from the candidate digest and has a timeout of 45 minutes.
- Steps per leg:
  1. Check out the same commit and log in to GHCR read-only (required while the package is private, harmless afterwards).
  2. Start `docker run -d -p 9090:9090 ghcr.io/manykarim/demo-webshop@${{ needs.build.outputs.digest }}` and wait for `healthy`.
  3. Run `setup-uv` (pinned) and `uv sync --locked`.
  4. Restore the Playwright browser cache, keyed by the locked Playwright version, then run `uv run playwright install --with-deps chromium`.
  5. Run the guard in release mode on workshop tags: `CONFORMANCE_RELEASE=${{ github.ref_name }} uv run pytest backend/tests/conformance/test_story_coverage.py`.
  6. Run the live suite: `CONFORMANCE_SPACE_MODE=${{ matrix.space_mode }} uv run pytest backend/tests/conformance -m conformance --base-url http://localhost:9090 --junitxml=conformance-report/${{ matrix.space_mode }}/junit.xml --tracing retain-on-failure --screenshot only-on-failure`.
  7. Always write the failing or erroring criterion IDs from `report.md`, and any failing or erroring harness checks (checks without an `ac` marker) under a "Harness" heading, with the space mode and the tested digest, to `$GITHUB_STEP_SUMMARY`, and upload the report and traces per leg. On failure, dump `docker logs`.

**Changes to `publish`**
- `drift-coverage` task 16.2 leaves `needs: [build, smoke, test]`. This change appends `conformance`, giving `needs: [build, smoke, test, conformance]`, the final form of `reproducible-image` D7. `build` stays listed because `publish` reads its outputs.
- The condition gains `&& (needs.conformance.result == 'success' || !startsWith(github.ref, 'refs/tags/workshop-'))`, giving `if: ${{ !cancelled() && github.event_name != 'pull_request' && needs.build.result == 'success' && needs.smoke.result == 'success' && needs.test.result == 'success' && (needs.conformance.result == 'success' || !startsWith(github.ref, 'refs/tags/workshop-')) }}`.
- Effect by ref (`reproducible-image` D7 table):
  - A `workshop-*` tag gets published only after `smoke`, `test` and both conformance legs pass.
  - `main` publishes `sha-<short>` and `edge` whatever the conformance result, as long as `smoke` and `test` pass, so the run there does not block.
  - `workflow_dispatch` requires conformance only on a `workshop-*` tag ref.
  - `vX.Y.Z` tags and pull requests do not run conformance.
- The explicit expression is required because a skipped or failed dependency would otherwise skip `publish` implicitly.
- On a failed gate for a workshop tag, `publish` is skipped and the candidate digest carries no tag at all, `sha-<short>` included, and no `workshop-<id>` exists. This is what the spec scenario "Unregistered deviation blocks the tag" and `reproducible-image`'s scenario "Failed verification publishes no workshop tag" require.
- **Both outcomes are rehearsed.** The non-blocking `main` path is rehearsed right after the gate PR with a deliberately failing harness check (task 6.3), because story PRs merge only when their criteria pass and a failure on `main` would otherwise never be observed. The blocked-tag path is rehearsed before the first release (task 18.1). Tasks 18.1 and 18.3 check gate behavior; `reproducible-image` task 10.5 checks the image level of the same runs (untagged blocked candidate; platforms, `sha-<short>`, revision label, anonymous arm64 pull and `/health` version of the published tag).

**Decided (C4): the gate tests the pushed candidate digest.** The brief planned to build an amd64 image locally in the gate job, test it, and only then build and push the multi-arch workshop image. This design instead tests the untagged candidate digest that `reproducible-image`'s `build` job pushed and its `smoke` job verified, and `publish` promotes that same digest. Rationale: the image receiving the workshop tag is then exactly the one that passed, nothing is built a second time, and the pipeline stays the one `reproducible-image` D7 defines. arm64 is not checked for conformance. `smoke` covers it natively.

Alternatives considered:
- **Local amd64 build, then a multi-arch build and push after the gate** (the brief): the published image comes from a second build that was never tested, and the pipeline would diverge from `reproducible-image` D7.
- **A separate workflow triggered by the tag or by `workflow_run`:** logs and permissions get split, and it races with the image workflow on the same tag.
- **Blocking on `main`:** would block `edge` during the audit, when failures are expected.
- **Both space modes in one leg on one container:** simpler, but doubles the leg's runtime and lets state from the first pass reach the second.
- **A forced-failure `workflow_dispatch` input for the rehearsal:** adds a permanent switch to the release workflow for a one-time check.

### D7. Downstream handoff

- **Consumer (out of scope):** the workshop repository converts the story files at a `workshop-<id>` tag into `openspec/specs/shop/*`, with scenario names containing `<STORY>_<AC>`.
- **What this change guarantees for that conversion:**
  - Self-contained story files without flags, bugs, drift or test references (D1).
  - Stable IDs and a list of withdrawn IDs.
  - Provenance and interpretation rules in the index, including that quoted UI text is matched against visible text, not role names, so converted Robot Framework or Playwright tests follow the same rule.
  - A tag commit that pins the exact story text the tagged image conforms to.
- **Facilitator material stays here.** `CONFORMANCE.md` and `backend/tests/conformance/` map criteria to planted-bug flags, which would spoil Module 7. They must not be copied into the participant repository. The index section "For downstream consumers" says to convert only the `<STORY-ID>_*.md` files.

Alternative considered: publishing the story set as a release asset or package. That is unnecessary, because the tag plus the path identifies it exactly.

## Risks / Trade-offs

- [Flaky UI checks] → Web-first `expect` auto-waiting, one space or reset per check with `clean` applied, arranging state through the API, no fixed sleeps, scoped locators, traces on failure. No reruns: a flaky check counts as a check defect and is fixed before tagging.
- [Checks built on role names miss controls whose accessible name differs from their visible text] → Quoted text is matched against visible text (D1), lookups are scoped, and a harness check proves the pattern on `/products` and `/products/1` (task 4.3).
- [App fixes from the audit expand the scope] → Timebox of about half a day per fix. Larger fixes become separate changes that the tag waits for. Wording-only differences go to story corrections.
- [App fixes break the drift contract (literal ids, unregistered hooks, JS bound to stage-1 names, HTML rendered outside `workshop_view`)] → The `app-fixed` checklist (task 5.1) names the obligations, and the per-story verification runs `drift-coverage`'s contract and browser smoke tests whenever templates, `app.js` or the stylesheet change.
- [Story corrections erode the stories' intent] → The ID is kept only when the verified behavior is unchanged or the correction is a clarification, otherwise the criterion is withdrawn and replaced. The Revisions section keeps the original wording. The maintainer approves each correction, and the record's precedence surfaces `story-corrected`. Downstream can diff against the source commit.
- [Revisions reasons reveal what a criterion was tightened to detect] → Neutral-reason rule (D1), token backstop in the guard, and a maintainer read of every reason (task 17.2).
- [Checks encode the implementation instead of the story] → Checks are written from the story text before looking at app output. Reviewers compare each check with its criterion. Ambiguities go into the index's interpretation rules.
- [The conformance suite hints at lab solutions] → Accepted: the stories are public anyway, and the checks are pytest/Playwright code, not Robot Framework. `CONFORMANCE.md` is not copied downstream (D7).
- [Sibling changes differ from what the checks assume: space reset, the `workshop-demo` fallback session in every space, flags and bugs in the status response, an importable bug registry and presets, `drift_and_bug` on stage 4, `BUG_CHECKOUT_TOTAL`, the `build` job's `digest` output, the `test` job] → The audit starts only after all three changes have merged, and task 1.2 probes these interfaces first. Mismatches are fixed in the owning capability and recorded as `app-fixed`, not worked around in checks.
- [Default-space code paths differ from named spaces (global flags, legacy cart keys, default reset, no space indicator)] → A second, serial pass in `default` mode on its own container (D3, D6).
- [`default` mode resets global flags, carts and runtime orders of the target] → Loopback targets only unless explicitly allowed, a pre-run status check that refuses a misconfigured target, and serial runs only.
- [Precondition errors on targets with overridden or globally changed flags] → Intended. The error names the offending flag. The gate's fresh containers have seeded defaults.
- [Seeded-data assumptions: product 1 is Aurora, Jamie has 2 orders, order timestamps are distinct] → The stories state these for fresh containers, and the checks target fresh containers. Checks depend on neither seeded order ids nor order numbers: the numbers are random per container, and the ids only hold on a fresh database. Timestamp ties are handled as a D5 candidate.
- [Planted bugs cannot be detected by the detail-page recommendation criteria] → Documented in D5 step 5; heal-vs-hide bugs must be mapped to a criterion that can detect them (D4 check 5).
- [App fixes to visible text break prompts or tests in the workshop repository] → Triage prefers story corrections for wording. Visible-text changes are listed in the handoff note for the workshop tag.
- [Conformance delays `edge` publishing on `main`] → Accepted: the delay is the suite runtime, cached browsers keep it short, and the result there does not block.
- [Longer gate from stage variants, `drift_and_bug` variants, planted-bug variants and two space modes] → Two parallel matrix legs with a 45-minute timeout each, no stage variants for API checks, and the bug sweep only during the audit.
- [Only amd64 is checked for conformance] → `smoke` exercises arm64 natively, and `reproducible-image` task 10.5 checks the anonymous arm64 pull of the first workshop tag (see Open Questions).
- [Flag names in test IDs and the record are publicly visible] → Accepted: the flags are already callable on the image, just hidden from the API schema.
- [A MODIFIED `planted-bugs` delta passes `openspec validate --strict` while its target spec does not exist, but `openspec archive` refuses it] → `drift-coverage` is archived right after it merges (its task 17.3), before this change starts and so before any such delta is written; task 1.1 verifies that prerequisite (`openspec/specs/planted-bugs/spec.md` exists and `openspec list` no longer shows `drift-coverage`), and the tasks that write or reconcile the delta check the `openspec validate acceptance-conformance --strict --json` output for "Archive would refuse" (tasks 5.2 and 17.3).
- [Regression tests for app fixes build a second test harness] → They use the root fixtures of `reproducible-image` D11 by exact name and add fixtures only in conftest files of their own suite directories (task 5.1); the conformance suite itself needs no in-process app.

## Migration Plan

Prerequisites:
- `reproducible-image`, `workshop-spaces` and `drift-coverage` are merged into `main`, and `edge` is published (the package is public after `reproducible-image` task 10.2).
- `drift-coverage` is archived right after it merges (its task 17.3). This is the hard requirement: `openspec/specs/planted-bugs/spec.md` must exist before this change writes a `planted-bugs` delta (step 3) or is archived (step 7). Outcome: the audit added no planted bug, so this change has no `planted-bugs` delta and its proposal lists no modified capability (task 17.3).
- `reproducible-image` may still be an active change: it stays active until its task 10.5 has checked the image level of this change's rehearsal tag (task 18.1) and first workshop tag (step 5), and is archived in its task 10.6. `workshop-spaces`' archive state does not matter here. This change modifies neither the `workshop-image` nor the `workshop-spaces` capability.

1. **Foundation PR (docs and test scaffolding):**
   - import the 9 stories, write the index and move the legacy files
   - create `CONFORMANCE.md` with `## Unreleased` and all rows `pending`
   - extend `drift-coverage`'s pytest configuration (markers, combined `addopts`), add `stories.py`, the guard, `helpers.py` and the `conftest.py` fixtures
   - The guard passes, since `pending` is allowed.
2. **Gate PR:** add the `conformance` job and the new `publish` condition to `image.yml`. On `main` the job runs without blocking from now on, and no workshop tag exists yet. Right after it merges, rehearse the non-blocking `main` path with a temporary failing harness check and revert it (task 6.3).
3. **Per-story PRs (9):** checks, the audit run, triage outcomes (app fixes, story corrections, new planted bugs including their spec delta) and `CONFORMANCE.md` rows.
4. **Bug sweep PR:** clarifications, `planted_bug` markers and rows, plus the "Planted bugs without criterion" table.
5. **Release:**
   1. Once both conformance legs on `main` are green, commit the rename of `## Unreleased` to `## workshop-<id>`.
   2. Push the git tag `workshop-<id>`.
   3. Gate and publish run on the candidate digest.
   4. Check gate behavior (task 18.3). `reproducible-image` task 10.5 (b) checks the image level of the same run: platforms, promoted digest, `sha-<short>`, revision label, anonymous arm64 pull and the `/health` version.
   5. Commit the literal `sha-<short>` and the digest from the tag run's `build` output into the section header (header lines only).
6. **Handoff:** give the workshop repository maintainers the tag, the story path, the story corrections, visible-text changes and any new flag names (the last two as facilitator notes).
7. **Archive:** `openspec archive acceptance-conformance`. It adds the `acceptance-stories` spec only, because the audit added no planted bug and so wrote no `planted-bugs` delta (task 17.3). `reproducible-image` is archived in its own task 10.6 once its task 10.5 is done; the two archives do not depend on each other.

Rollback:
- **Failed gate:** the candidate carries no tag, and nothing with the workshop tag is published. Fix forward, then re-push the tag or cut a new id (tag mutability is a `reproducible-image` open question).
- **Reverting an app fix:** revert the commit and change the row in `## Unreleased` (opened per D2 if needed). The criterion fails again and the gate blocks until it is triaged anew.
- **Docs import:** reverting the foundation PR restores the legacy layout.
- **Broken gate job:** fix the workflow. Workshop tags are never promoted manually to bypass the gate. Only a reviewed status change can unblock a criterion.
- **Removing the gate:** reverting the gate PR restores the `publish` behavior of `reproducible-image` and `drift-coverage`.

## Open Questions

- Should the `conformance` job also run natively on `ubuntu-24.04-arm`?
- Should conformance run without blocking on pull requests, e.g. when `docs/user-stories/`, templates or `static/app.js` change?
- When should the remaining 19 source stories be imported? Scope-by-folder and the ID rules already support it.
- Does `CONFORMANCE.md` keep every version section, or only the last few, with older ones left to git history? If sections are pruned, at least the most recent released section stays, because D4 check 8 (a) only protects IDs whose sections are kept.
- Should story corrections be reported back to `manykarim/ai-workshop-rbcn-2026`?
