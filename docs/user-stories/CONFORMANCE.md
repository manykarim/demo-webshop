# Conformance record

This record states, for each workshop image version (`workshop-<id>`), how every in-scope acceptance criterion of the story set in this directory relates to the image in its clean state. It is facilitator material: it maps criteria to planted-bug flags and must not be copied into a participant repository (see [For downstream consumers](README.md#for-downstream-consumers)). Criterion IDs follow the [ID rules](README.md#criterion-ids) of the index.

**Statuses.** Each criterion has exactly one status per version. Statuses are relative to the imported source text and carry forward to later versions until something changes for that criterion.

- `conforms`: the app met the imported criterion without any change.
- `app-fixed`: the application was changed to meet it. The note names the change and the version.
- `story-corrected`: the criterion text differs from the source. The story's `## Revisions` section holds the neutral reason, and the note holds any planted-bug motivation.
- `planted-bug`: the criterion holds in the clean state and is violated while any flag listed in `Flag` is enabled.

**Precedence.** When several statuses apply, the row records the highest one: `planted-bug` > `story-corrected` > `app-fixed` > `conforms`. The note mentions the others.

**`Flag`** is filled only for `planted-bug`. It holds the key of every planted bug that violates the criterion; several keys are comma-separated, for example `BUG_MISSING_BUTTON, BUG_WRONG_PRICE`. It stays empty for every other status.

**`Note`** is one sentence plus a link to the commit, PR or change. It is required for `app-fixed`, `story-corrected` and `planted-bug`. It is optional for `conforms`, where it records a planted-bug flag that breaks the criterion incidentally, and optional for `pending`, where it may name a spin-out change.

**`pending`** marks a criterion whose audit is not finished. It is allowed only in the `## Unreleased` section: while the audit runs, and after a release only for new criteria.

**Release lifecycle.**

- There is one section per `workshop-<id>` tag, newest first. Images tagged `X.Y.Z`, `edge` or `sha-<short>` get no section and carry no conformance guarantee.
- During development the top section is `## Unreleased`. At most one such section exists, and it is always on top. Every section holds a complete table of all criteria active in that version, sorted by story and criterion number, and a `Planted bugs without criterion` table whose reason is one sentence plus a link to the PR in which the maintainer approved it.
- The tag commit renames `## Unreleased` to `## workshop-<id>` and fills the image tag and story commit header lines, stating that the `sha-` tag and the story commit are those of the tagged commit. Once the tag is published, that section's tables are frozen. All earlier released sections are fully frozen.
- The literal `sha-` tag and the image digest are added to the header in one follow-up commit after tagging, because a commit cannot contain its own hash and the digest exists only after the tag run. That commit touches header lines only. The digest (the tag run's `build` job output that `publish` promoted) is the authoritative identifier of the image; the `sha-` tag is recorded for orientation only, because it is a moving per-commit pointer.
- After a release, the first change that affects the record opens a new `## Unreleased` section at the top as a full copy of the latest released table (statuses carry forward) and applies the change there. Changes that affect the record are: a story file, the index story or withdrawn tables, a `planted_bug` marker, or a row. The header-only follow-up commit does not count. Released tables are never edited.

**Running the checks.** Start the image and run the suite against it, once per space mode, each time on a fresh container:

```bash
docker run -d --name conformance-target -p 9090:9090 ghcr.io/manykarim/demo-webshop:<tag>
uv run pytest backend/tests/conformance -m conformance --base-url http://localhost:9090 \
  --tracing retain-on-failure --screenshot only-on-failure
# then recreate the container and repeat in the default space:
CONFORMANCE_SPACE_MODE=default uv run pytest backend/tests/conformance -m conformance \
  --base-url http://localhost:9090 --tracing retain-on-failure --screenshot only-on-failure
```

Each run writes `conformance-report/<space mode>/report.json` and `report.md` with pass, fail or error per criterion; Playwright traces of failed UI checks land under `test-results/`. Both directories are ignored by git and excluded from the image build context.

## How deviations are resolved

This section is the audit procedure and the triage rules. How to start a target, run the checks in both space modes and find the report is described under **Running the checks** above and is not repeated here. The procedure starts after step 1, the import of the story set with every row `pending`.

### Procedure

2. **Write the checks from the story text, and commit them before their first run.** A story module `backend/tests/conformance/test_<web|api|ai>_<nnn>_<slug>.py` is written from the story text, the [interpretation rules](README.md#interpretation-rules) and the index only. An ambiguity is resolved by an interpretation rule or a clarification in the index, never by reading the implementation or the app's output; otherwise the checks encode current behavior instead of the story.
3. **Run** the module against a target built from the branch under audit (`docker compose up -d --build`, port 9090) or from `main`, in both space modes and with all variants, as under **Running the checks**.
4. **Triage every failing criterion.** First rule out a defect in the check. Then give the criterion exactly one outcome from the [triage table](#triage), follow that outcome's [recording checklist](#recording-checklists), and record the row, a Revisions entry for a story correction, and the commit or PR link.
5. **Bug sweep:** one run per flag in `PLANTED_BUGS`, plus one run with preset `drift_and_bug`. Put `CONFORMANCE_SWEEP_FLAG=<FLAG>` or `CONFORMANCE_SWEEP_PRESET=drift_and_bug` in front of either command under **Running the checks** (only one of the two variables per run). In sweep mode each check runs once, with that flag or preset applied after `clean` and without any expected failure, so a check the bug breaks fails with an `AssertionError`.
   - Clarifications that make a registered bug detectable are proposed before the sweep, even when the sweep shows no break, because a check that is not yet clarified cannot break. After they are applied, the sweep is rerun for those flags.
   - No new criteria: criteria are added only to replace withdrawn ones. An existing criterion may be clarified where its intent already covers correctness (for example, a card's "price" is the product's price), recorded as `story-corrected` with the ID kept. If review judges the change semantic, the criterion is withdrawn and its replacement carries the rule.
   - For each criterion a flag breaks, decide whether the criterion is meant to catch that bug. If so, add `@pytest.mark.planted_bug("<FLAG>")` to its check and set the row to `planted-bug` with the flag; one criterion may list several flags, comma-separated, each with its own marker. If the break is incidental, add a note only: the row keeps its status and ends as a `conforms` row with a note.
   - A break by a flag that preset `drift_and_bug` enables is never left as a note, because the `drift_and_bug` variant must fail exactly on registered criteria. It becomes a registered `planted-bug`, or, where the criterion does not concern the affected product, the check arranges its data so the bug's trigger does not apply.
   - The failing set of the `drift_and_bug` sweep must equal the union of the per-flag sweeps for its flags. Any difference goes into the sweep PR.
   - A bug that no criterion detects is listed under `### Planted bugs without criterion` with a one-sentence reason and a link to the approving PR. This is allowed only for bugs that preset `drift_and_bug` does not enable; those bugs must be detectable.
6. **Close out:** rerun until the clean runs, the stage variants and the planted-bug variants behave as expected in both space modes. Remaining `pending` rows become `conforms`.
7. **The maintainer decides.** Every outcome, row, Revisions entry and "Planted bugs without criterion" reason is approved by the maintainer in PR review. An agent may write and run the checks, triage and propose outcomes, but it does not decide them: agents draft, humans decide. The PR states the proposed outcome with its evidence (check, variant, space mode, report).

### Triage

Before choosing an outcome, rule out two cases:

- **Check defect:** fix the check; the criterion gets no status from it. A check that fails only because a control's accessible name differs from its visible text, or because it relies on a hook (id, class or `data-test` value) that drift changes, has a defect in the check.
- **Drift-only failure:** a criterion whose `clean` variant passes but whose `stage2`, `stage3`, `stage4` or `drift_and_bug` variant fails (other than an expected failure for a flag the check is marked with) shows a drift defect in the app. It is fixed in the drift layer under `drift-coverage`'s contract and recorded as `app-fixed` with a note naming the stage. It is `story-corrected` only if the criterion itself names a hook that drift changes, and never `planted-bug`.

Otherwise the criterion gets exactly one outcome. A criterion that passes every variant without any change needs no triage and becomes `conforms` at close-out. When several outcomes apply to one criterion, the row records the highest one by **Precedence** and its note mentions the others.

| Outcome | Choose when | Constraints |
|---------|-------------|-------------|
| `story-corrected` | The story over-specifies incidental detail (format of generated identifiers, exact wording beyond the interpretation rules, static strings, response fields nobody relies on), contradicts another in-scope story, or requires a locator hook (id, class, data attribute) that drift stages change by design | Keep the ID if the verified behavior is unchanged or the correction is a clarification, otherwise withdraw and replace it. The Revisions entry keeps the original wording and gives a neutral reason |
| `app-fixed` | The story describes sensible shopper-facing or API-consumer behavior the app lacks or gets wrong, and the fix takes **about half a day or less** | No renaming of cross-change contract names (endpoints, flags, presets, environment variables); no fix that undoes a sibling change's decision, such as `drift-coverage` A3 (server-rendered search results) or `workshop-spaces` D3 (cart and checkout APIs read only the `X-Session-ID` header); such a deviation goes to `story-corrected` or a spin-out. Accessible names kept stable by `drift-coverage` (for example "Add `<product>` to cart") are never removed or changed to satisfy a text criterion. Prefer a story correction for pure wording differences, because visible text is the baseline of the drift contract and of the workshop materials, unless the app contradicts itself. Shared harness and drift contract as in the checklist |
| `planted-bug` | The deviation is a realistic, deterministic defect in a workshop flow that is valuable to detect in Modules 7 and 8 | The clean state gets the correct behavior and the deviation moves behind a new `BUG_*` flag; see [Checklist for a new planted bug](#checklist-for-a-new-planted-bug) |
| spin-out (not a status) | An app fix would take **more than about half a day** | A separate OpenSpec change. The row stays `pending` and the workshop tag waits for it, because the gate blocks. An interim story correction needs explicit maintainer sign-off and a note naming the pending change |

### Recording checklists

Copy the checklist of the chosen outcome into the PR description.

**Check defect** (no status)

- [ ] The check is fixed in its story module; the reason is stated in the PR (for example, it matched an accessible name instead of the visible text, or used a hook that drift changes).
- [ ] The row is unchanged.

**Drift-only failure** (`app-fixed`)

- [ ] The fix is in the drift layer and follows the drift contract of the `app-fixed` checklist below.
- [ ] The row is `app-fixed`, and its note names the failing stage (`stage2`, `stage3`, `stage4` or `drift_and_bug`), the change and the version. It is `story-corrected` only if the criterion names a hook that drift changes; never `planted-bug`.

**`app-fixed`**

- [ ] The fix, within about half a day and within the constraints of the triage table.
- [ ] A regression test in the suite of the code it covers: `backend/tests/unit/`, `backend/tests/integration/`, `backend/tests/contract/` for render states and the drift contract, or `backend/tests/spaces/` for space, cart or order scoping.
- [ ] **Shared harness** (`reproducible-image` D11): the regression test uses the root fixtures by their exact names (`app_client`, `seeded_app_client`, `temp_database`, `pdf_unavailable`, and `fake_weasyprint` whenever it creates an order) or `isolated_app`. It defines no fixture with those names, adds fixtures only in its own suite directory's conftest, creates no other root conftest, and sets no environment variable of the pytest process.
- [ ] **Drift contract**, whenever the fix touches `backend/app/templates/**`, `backend/app/static/app.js` or `backend/app/assets/styles.css`:
  - (a) New or changed elements in a covered flow (for example per-field checkout messages, a product count, the header sign-in button) get ids, classes and `data-test` only through `drift.id`, `drift.cls` and `drift.test`, including `for` and `aria-describedby` targets. **Exception:** the shared uncovered blocks `form-field` (with `form-field__icon`) and `button` with its modifiers `button--primary`, `button--ghost`, `button--text` and `button--lg` stay written literally beside the covered hook and are never added to `COVERED_CLASSES`, because `drift.cls` raises on an unknown key and covering them would break the byte-for-byte stylesheet assertion. Assertion targets get `data-test`. There are no literal ids outside `STABLE_IDS`, `STABLE_IDS` is never widened for covered-flow elements, and no behavior-only `data-*` marker is added.
  - **Single `role="status"`** (part of (a)): no new element anywhere in `base.html` or a page template carries the `role="status"` attribute. The add-to-cart confirmation stays the only element with that attribute on every page, because `showFlash` binds to `document.querySelector('[role="status"]')` and a contract test asserts exactly one per page in every stage. A live result count (such as a product count) gets `aria-live="polite"` on an element without `role="status"`, as the cart badge does; a count that only re-renders on a full filter submit needs no live region. Per-field validation messages are plain text targeted through `aria-describedby` via `drift.id`, or `role="alert"`. In the checkout form they sit inside the field wrappers, never as a second direct-child `<p>` of `form[action="/checkout"]`, whose only direct-child `<p>` is the signed-in note.
  - (b) New keys go into `COVERED_IDS`, `COVERED_CLASSES` or `DATA_TEST_VALUES` and the stage 2–4 `StageSpec` tables under the uniqueness rule, with matching rows in the `## Drift mapping` tables of `docs/WORKSHOP-FEATURES.md`.
  - (c) Every new render state (for example the `POST /checkout` validation-error render or a product not-found page) is added to `COVERED_PAGES` in `backend/tests/contract/test_stage_contract.py`, with its new selectors in `backend/tests/contract/coverage_oracle.py`.
  - (d) `app.js` changes bind only to stable hooks (`form[action="/checkout"]`, `form.elements.<name>`, roles, ARIA attributes and relationships, `href`, and the content data attributes `data-product`, `data-product-name`, `data-category` and `data-chat-prompt`), add no behavior-only `data-*` marker (no `data-price-*` or other removed marker returns), write no `data-*` attribute or id at runtime, change classes only through `classList`, and clone any markup they insert from a `<template>` rendered with `drift`, filled with `textContent`.
  - (e) HTML pages are rendered only while `workshop_view` is active: validation happens inside a route that declares it, and no global exception handler renders HTML.
  - (f) Visible text stays identical in every stage. A visible-text change also updates the smoke-test locators in `backend/tests/browser/test_drift_smoke.py` and `docs/WORKSHOP-FEATURES.md` in the same PR. Accessible names kept stable by `drift-coverage` are never changed to fit a quoted phrase.
  - (g) Verified with `uv run pytest backend/tests` (template scan, script scan, contract tests and docs sync, including the exactly-one-`role="status"` contract test extended to each added render state); `grep -rn 'role="status"' backend/app/templates` returns only the add-to-cart confirmation region in `base.html`; the browser smoke `uv run pytest -m browser backend/tests/browser` passes against the local target (base URL option as under **Running the checks**) for `stage1` to `stage4`; and a regression test for an HTML error or validation page renders it in stages 1 and 2.
- [ ] The row is `app-fixed`, and its note names the change and the version, with a link.
- [ ] Every visible-text change is listed in the PR for the handoff.

**`story-corrected`**

- [ ] The ID is kept when the verified behavior is unchanged or the correction is a clarification. Otherwise the criterion is withdrawn and replaced under the [ID rules](README.md#criterion-ids): the replacement heading gets the next free number, the withdrawn heading is removed, the index gets a withdrawn-table row (ID, version withdrawn, reason, replacement ID) and a current story-table count, the check moves to the replacement ID, and the record drops the withdrawn row and adds the replacement row.
- [ ] A `## Revisions` entry at the end of the story file in the README format: version, criterion, original wording, new wording and reason. A withdrawal with a replacement is one entry for the replacement ID whose reason names the withdrawn ID.
- [ ] **Neutral reason:** the Revisions reason and the withdrawn-table reason are written from the shopper's or API consumer's point of view and never name or hint at a defect, flag, drift stage, locator, conformance status or detection purpose. Any bug motivation goes only into the row's note. The guard rejects story files that contain `BUG_`, `LOCATOR_`, `planted`, `drift`, `CONFORMANCE.md` or `backend/tests`; paraphrases are caught in review.
- [ ] The row is `story-corrected` (or `planted-bug` when a flag also breaks it), with a note and a link.

**`planted-bug`** with a new flag: the [checklist for a new planted bug](#checklist-for-a-new-planted-bug) below. With a flag that is already registered (bug sweep): one `planted_bug` marker per flag on the detecting check, the row `planted-bug` with the flags in `Flag`, and a note that mentions any other applicable status.

**Spin-out** (not a status)

- [ ] A new OpenSpec change for the fix. The row stays `pending` and its note may name the change. The workshop tag waits for the change, because the gate blocks and release mode rejects `pending` rows.
- [ ] An interim story correction only with explicit maintainer sign-off, recorded as `story-corrected` with a note naming the pending change.

### Checklist for a new planted bug

- [ ] Prerequisite: `drift-coverage` is archived, so `openspec/specs/planted-bugs/spec.md` exists (`test -f openspec/specs/planted-bugs/spec.md`). No new planted bug is added before that.
- [ ] The clean state behaves correctly: the fix lands in the clean path, and only the flag brings the deviation back.
- [ ] An entry in `PLANTED_BUGS` in `backend/app/core/workshop.py` with `flag`, `flow`, `trigger`, `defect` and `scope`. The registry also yields the seed row and the preset membership: off in `clean`, on in `buggy`.
- [ ] A row in the `## Planted bugs` table of `docs/WORKSHOP-FEATURES.md` (columns `Flag`, `Flow`, `Trigger` and `Defect`, in registry order; never a separate table), so that `backend/tests/contract/test_docs_sync.py` passes.
- [ ] The `drift-coverage` contract tests that enumerate the registry bugs are updated: `backend/tests/contract/test_presets_api.py` and `backend/tests/contract/test_planted_bugs.py`.
- [ ] `@pytest.mark.planted_bug("<FLAG>")` on the detecting check, and a row `planted-bug` with the flag in `Flag`.
- [ ] The delta `openspec/changes/acceptance-conformance/specs/planted-bugs/spec.md` (new), written only after `drift-coverage` was archived. It holds a MODIFIED "Bug registry" block that copies the whole current requirement from `openspec/specs/planted-bugs/spec.md`, with its header text unchanged and every scenario including "Clean preset", and adds the new key or keys to every scenario of that requirement that enumerates the active registry bugs (today "Buggy preset" and "Stage preset keeps active bugs", which must end up listing the same set of flags), matching the updated `test_presets_api.py` cases of the same names, while "Clean preset" keeps listing no active bugs. It also holds an ADDED requirement with the bug's flow, trigger and defect.
- [ ] The conditional `planted-bugs` entry under Modified Capabilities in `openspec/changes/acceptance-conformance/proposal.md` stays.
- [ ] A facilitator note for the handoff: the flag, its flow, trigger and defect, and the criterion that detects it.
- [ ] Verified: `openspec validate acceptance-conformance --strict --json` reports `"valid": true` and no issue at any level whose message contains "Archive would refuse"; `uv run pytest backend/tests` passes.

## Unreleased

- Image tag: TBD (filled at release: `workshop-<id>`)
- Image digest: TBD (filled after tagging; the authoritative image identifier)
- sha- tag: TBD (filled after tagging; for orientation only, a moving per-commit pointer)
- Story commit: TBD (filled at release: the tagged commit)

| Criterion | Status | Flag | Note |
|-----------|--------|------|------|
| API-005_AC-1 | conforms | | Passes as imported in both space modes: without `X-Session-ID` the empty fallback cart reports `"session": "workshop-demo"` in a named space too (`workshop-spaces` D3), so the candidate needed no fix (task 13.2, [acceptance-conformance](../../openspec/changes/acceptance-conformance/tasks.md)). |
| API-005_AC-2 | conforms | | |
| API-005_AC-3 | conforms | | |
| API-005_AC-4 | conforms | | |
| API-005_AC-5 | conforms | | |
| API-005_AC-6 | conforms | | |
| API-005_AC-7 | conforms | | |
| API-005_AC-8 | conforms | | Passes as imported in both space modes: `DELETE /api/cart/` without `X-Session-ID` answers `{"status": "cleared", "session": "workshop-demo"}` in a named space too, not the space-prefixed storage key (`workshop-spaces` D3), so the candidate needed no fix (task 13.2, [acceptance-conformance](../../openspec/changes/acceptance-conformance/tasks.md)). |
| API-005_AC-9 | conforms | | |
| API-005_AC-10 | conforms | | Passes as imported in both space modes: `GET /api/cart/` without `X-Session-ID` reports `"session": "workshop-demo"` in a named space too (`workshop-spaces` D3), so the candidate needed no fix (task 13.2, [acceptance-conformance](../../openspec/changes/acceptance-conformance/tasks.md)). |
| API-005_AC-11 | conforms | | |
| API-006_AC-1 | conforms | | |
| API-006_AC-2 | conforms | | |
| API-006_AC-3 | conforms | | |
| API-006_AC-4 | conforms | | |
| API-006_AC-5 | conforms | | |
| API-006_AC-6 | conforms | | Passes as imported in both space modes: `documents` lists `/data/pdfs/invoice_<order number>.pdf` and `/data/pdfs/summary_<order number>.pdf` (`reproducible-image` D3); the criterion names only the file names, and the example's `generated_pdfs/` directory is not normative, so the candidate story correction was not applied (task 14.2, [acceptance-conformance](../../openspec/changes/acceptance-conformance/tasks.md)). |
| API-006_AC-7 | conforms | | |
| API-006_AC-8 | conforms | | |
| API-006_AC-9 | conforms | | |
| API-006_AC-10 | conforms | | |
| API-006_AC-11 | conforms | | |
| API-006_AC-12 | conforms | | |
| API-006_AC-13 | conforms | | |
| API-007_AC-1 | conforms | | |
| API-007_AC-2 | app-fixed | | `expires_at` was a naive UTC datetime (e.g. `2026-09-21T23:52:03.537900`), which ISO 8601 reads as local time of an unstated zone and the index's interpretation rules do not read as UTC, so a consumer could not compare it with the current UTC time; `POST /api/auth/login` now returns an aware UTC value with the `Z` designator (same field and digits, so existing parsers keep working), covered by `backend/tests/integration/test_login_expiry.py`, and reading the naive value as UTC by a new interpretation rule was not chosen (Unreleased, task 15.3, [acceptance-conformance](../../openspec/changes/acceptance-conformance/tasks.md)). |
| API-007_AC-3 | conforms | | |
| API-007_AC-4 | conforms | | Passes as imported on four freshly started containers (both space modes, before and after the AC-2 fix): the addresses come back as Home then Studio, in insertion order, because the relationship has no `order_by`, so the candidate `order_by` fix was not applied (task 15.2, [acceptance-conformance](../../openspec/changes/acceptance-conformance/tasks.md)). |
| API-007_AC-5 | conforms | | |
| API-007_AC-6 | conforms | | |
| API-007_AC-7 | conforms | | Passes as imported on four freshly started containers (both space modes, before and after the AC-2 fix): the seeded orders' `created_at` values differ by a few microseconds in insertion order (the newer "processing" order first), not equal, so the candidate explicit seeded timestamps were not added (task 15.2, [acceptance-conformance](../../openspec/changes/acceptance-conformance/tasks.md)). |
| API-007_AC-8 | conforms | | |
| API-007_AC-9 | conforms | | |
| API-007_AC-10 | conforms | | |
| API-007_AC-11 | conforms | | |
| WEB-002_AC-1 | planted-bug | BUG_MISSING_BUTTON, BUG_WRONG_PRICE | Holds in the clean state and in every stage; "price" was clarified as the product's price (story-corrected, ID kept) so that the card price is checked against the catalogue price, and the task 16.1 sweep broke this criterion with each of its two flags and no other criterion with either: with `BUG_MISSING_BUTTON` on, the cards of products 5 and 10 lose their "Add to Cart" button, which the per-card grid check catches, and with `BUG_WRONG_PRICE` on, the cards of products 3, 6, 9 and 12 show the price times 1.15, which only the split price check (marked) catches, while the unclarified check had passed that sweep (Unreleased, tasks 16.1 and 16.2, [acceptance-conformance](../../openspec/changes/acceptance-conformance/tasks.md)). |
| WEB-002_AC-2 | story-corrected | | The quoted group name "Category" did not match the filter group's visible legend "Categories", so the wording was corrected with the ID kept because the verified behavior is unchanged (Unreleased, task 7.3, [acceptance-conformance](../../openspec/changes/acceptance-conformance/tasks.md)). |
| WEB-002_AC-3 | app-fixed | | The price sliders were rounded to whole dollars (minimum $40, not $39.50); `products.html` and `app.js` now use the exact lowest and highest prices with `step="any"` and show the values in cents, covered by `backend/tests/contract/test_catalogue_filters.py` (Unreleased, task 7.3, [acceptance-conformance](../../openspec/changes/acceptance-conformance/tasks.md)). |
| WEB-002_AC-4 | conforms | | |
| WEB-002_AC-5 | conforms | | |
| WEB-002_AC-6 | app-fixed | | The rounded $40 default minimum excluded Insight Smart Notebook ($39.50) from every filtered grid and the page showed no product count; fixed by the exact slider bounds (AC-3) and a product count under "All products" (`drift.test('product-count')`, no live region), covered by `backend/tests/contract/test_catalogue_filters.py` (Unreleased, task 7.3, [acceptance-conformance](../../openspec/changes/acceptance-conformance/tasks.md)). |
| WEB-002_AC-7 | conforms | | |
| WEB-002_AC-8 | conforms | | |
| WEB-002_AC-9 | app-fixed | | A category plus price filter that kept the minimum at its default excluded Insight Smart Notebook ($39.50) because of the rounded $40 minimum; fixed with the exact slider bounds of AC-3, covered by `backend/tests/contract/test_catalogue_filters.py` (Unreleased, task 7.3, [acceptance-conformance](../../openspec/changes/acceptance-conformance/tasks.md)). |
| WEB-002_AC-10 | conforms | | |
| WEB-002_AC-11 | conforms | | |
| WEB-002_AC-12 | conforms | | |
| WEB-002_AC-13 | conforms | | |
| WEB-003_AC-1 | conforms | | |
| WEB-003_AC-2 | conforms | | |
| WEB-003_AC-3 | conforms | | Passes as imported in every variant: the button's `data-product` attribute holds the product id, which satisfies the non-normative `data-product-id` example, and the click adds product 1 to the page's cart, so the candidate story correction was not applied (task 8.2, [acceptance-conformance](../../openspec/changes/acceptance-conformance/tasks.md)). |
| WEB-003_AC-4 | conforms | | |
| WEB-003_AC-5 | planted-bug | BUG_BROKEN_LINKS | Holds in the clean state and in every stage; with `BUG_BROKEN_LINKS` on, the related cards of products 8 and 12 on `/products/1` link to `/products/invalid-<id>`, which serves no detail page, so only the `/products/1` check carries the marker (`/products/12` shows no affected card); the full sweep of task 16.1 confirmed this mapping and broke no other criterion with this flag, including WEB-004_AC-3 and AC-8, whose test-data queries show no affected card (Unreleased, tasks 8.3 and 16.1, [acceptance-conformance](../../openspec/changes/acceptance-conformance/tasks.md)). |
| WEB-003_AC-6 | conforms | | |
| WEB-003_AC-7 | conforms | | |
| WEB-003_AC-8 | conforms | | |
| WEB-003_AC-9 | app-fixed | | `/products/9999` answered with the JSON body `{"detail": "Product not found"}` and `/products/abc` with a JSON 422; the `/products/{product_id}` route now parses the id itself and renders `product_not_found.html` with status 404 while `workshop_view` is active (new covered render state `detail-not-found`, hook `drift.test('product-not-found')`), covered by `backend/tests/contract/test_product_not_found.py` (Unreleased, task 8.3, [acceptance-conformance](../../openspec/changes/acceptance-conformance/tasks.md)). |
| WEB-004_AC-1 | conforms | | |
| WEB-004_AC-2 | conforms | | |
| WEB-004_AC-3 | conforms | | |
| WEB-004_AC-5 | conforms | | |
| WEB-004_AC-6 | story-corrected | | The quoted "Clear search/results" matched no button: the clear button reads "Clear search" on `/products` and "Clear results" on `/`, so the wording was clarified to name both labels with the ID kept because the verified behavior is unchanged (Unreleased, task 9.3, [acceptance-conformance](../../openspec/changes/acceptance-conformance/tasks.md)). |
| WEB-004_AC-7 | conforms | | |
| WEB-004_AC-8 | conforms | | |
| WEB-004_AC-9 | story-corrected | | Replaces WEB-004_AC-4, whose check found no `/api/search` request on submit because the pages load results from the server-rendered `GET /search/results` fragment (`drift-coverage` A3, which an app fix may not undo); the replacement states the API wording (`GET /api/search/` with `query`), checked with httpx, and the endpoint-neutral alternative was not chosen (Unreleased, task 9.3, [acceptance-conformance](../../openspec/changes/acceptance-conformance/tasks.md)). |
| WEB-005_AC-1 | story-corrected | | Passes as imported in every variant; only its cross-reference "(see AC-8)" was updated to AC-10 after AC-8 was withdrawn, so the ID is kept (Unreleased, task 10.3, [acceptance-conformance](../../openspec/changes/acceptance-conformance/tasks.md)). |
| WEB-005_AC-2 | story-corrected | | At 390x844 the header shows only the navigation menu button, so the badge is hidden until the menu is opened (it then shows the updated count); "mobile navigation" was clarified as the opened menu with the ID kept, and an app fix showing the badge in the collapsed mobile header was not chosen (Unreleased, task 10.3, [acceptance-conformance](../../openspec/changes/acceptance-conformance/tasks.md)). |
| WEB-005_AC-3 | conforms | | |
| WEB-005_AC-4 | conforms | | |
| WEB-005_AC-5 | conforms | | |
| WEB-005_AC-6 | conforms | | |
| WEB-005_AC-7 | conforms | | |
| WEB-005_AC-9 | conforms | | |
| WEB-005_AC-10 | story-corrected | | Replaces WEB-005_AC-8, whose cookie-only case failed because the cart API reads only `X-Session-ID` and otherwise uses `workshop-demo` (`workshop-spaces` D3, which an app fix may not undo); withdrawn rather than clarified because a cookie-only API call now expects the fallback cart instead of the cookie's cart (Unreleased, task 10.3, [acceptance-conformance](../../openspec/changes/acceptance-conformance/tasks.md)). |
| WEB-006_AC-1 | planted-bug | BUG_CHECKOUT_TOTAL | Holds in the clean state and in every stage (the tax amount and total come from `drift-coverage`); "Order total" was clarified as subtotal plus shipping plus tax with "Complimentary" counted as 0 (story-corrected, ID kept), and with `BUG_CHECKOUT_TOTAL` on the displayed total omits the tax, which only the split total check (marked) catches; the full sweep of task 16.1 broke no other criterion with this flag, and the `drift_and_bug` sweep failed exactly this criterion and WEB-002_AC-1, the union of its two flags' sweeps (Unreleased, tasks 11.3 and 16.1, [acceptance-conformance](../../openspec/changes/acceptance-conformance/tasks.md)). |
| WEB-006_AC-2 | conforms | | |
| WEB-006_AC-3 | conforms | | |
| WEB-006_AC-4 | app-fixed | | `notanemail` was stopped only by the browser's own tooltip, which puts no message in the page, and `a@b` passed the browser and replaced the page with FastAPI's JSON 422; `POST /checkout` now validates the fields inside its handler and re-renders `checkout.html` with status 422 (form `novalidate`, a form-level alert, the typed values kept) and a message inside each invalid field's wrapper that its `aria-describedby` references (`drift.id`/`drift.test` hooks `checkout-<field>-error`, new covered render state `checkout-post-invalid`), covered by `backend/tests/contract/test_checkout_validation.py`; "cannot be submitted" is read as "no order is placed and the shopper stays on the form" (Unreleased, task 11.3, [acceptance-conformance](../../openspec/changes/acceptance-conformance/tasks.md)). |
| WEB-006_AC-5 | app-fixed | | A one-character name replaced the page with FastAPI's JSON 422 and no message next to the field; `POST /checkout` now validates the fields inside its handler and re-renders `checkout.html` with status 422 (form `novalidate`, a form-level alert, the typed values kept) and a message inside each invalid field's wrapper that its `aria-describedby` references (`drift.id`/`drift.test` hooks `checkout-<field>-error`, new covered render state `checkout-post-invalid`), covered by `backend/tests/contract/test_checkout_validation.py` (Unreleased, task 11.3, [acceptance-conformance](../../openspec/changes/acceptance-conformance/tasks.md)). |
| WEB-006_AC-6 | app-fixed | | A three- or four-character address replaced the page with FastAPI's JSON 422 and no message next to the field; `POST /checkout` now validates the fields inside its handler and re-renders `checkout.html` with status 422 (form `novalidate`, a form-level alert, the typed values kept) and a message inside each invalid field's wrapper that its `aria-describedby` references (`drift.id`/`drift.test` hooks `checkout-<field>-error`, new covered render state `checkout-post-invalid`), covered by `backend/tests/contract/test_checkout_validation.py` (Unreleased, task 11.3, [acceptance-conformance](../../openspec/changes/acceptance-conformance/tasks.md)). |
| WEB-006_AC-7 | story-corrected | | The shop shows `ORD-` plus 8 uppercase hex characters (e.g. `ORD-07AE9433`), not `^ORD-\d{4,}$`; the format was clarified with the ID kept, consistent with API-006_AC-2, and the test data regex and the note were updated with it (Unreleased, task 11.3, [acceptance-conformance](../../openspec/changes/acceptance-conformance/tasks.md)). |
| WEB-006_AC-8 | conforms | | |
| WEB-006_AC-10 | conforms | | |
| WEB-006_AC-11 | app-fixed | | An invalid submission replaced the checkout page with FastAPI's JSON 422, so no message stood next to any field and the shopper left the page; `POST /checkout` now validates the fields inside its handler and re-renders `checkout.html` with status 422 (form `novalidate`, a form-level alert, the typed values kept) and a message inside each invalid field's wrapper that its `aria-describedby` references (`drift.id`/`drift.test` hooks `checkout-<field>-error`, new covered render state `checkout-post-invalid`), covered by `backend/tests/contract/test_checkout_validation.py` (Unreleased, task 11.3, [acceptance-conformance](../../openspec/changes/acceptance-conformance/tasks.md)). |
| WEB-006_AC-12 | story-corrected | | Replaces WEB-006_AC-9, whose badge check failed because the cart badge is empty and hidden while the cart is empty; withdrawn rather than clarified because a count of 0 becomes no count, and an app fix showing "0" was not chosen (Unreleased, task 11.3, [acceptance-conformance](../../openspec/changes/acceptance-conformance/tasks.md)). |
| WEB-007_AC-1 | story-corrected | | The signed-out header on `/`, `/products` and `/cart` shows a "Log in" button, not "Sign in"; the label was clarified with the ID kept, and an app fix renaming the header button to "Sign in" (the app contradicts itself: the dialog title and its submit button say "Sign in") was not applied, because `drift-coverage` keeps the accessible name "Log in" stable and its smoke tests (`backend/tests/browser/test_drift_smoke.py`) locate the button by it (Unreleased, task 12.3, [acceptance-conformance](../../openspec/changes/acceptance-conformance/tasks.md)). |
| WEB-007_AC-2 | story-corrected | | Failed only because the quoted "Sign in" header button is labelled "Log in" (see WEB-007_AC-1); the label was clarified with the ID kept, and the dialog overlays and dims the page in every stage (Unreleased, task 12.3, [acceptance-conformance](../../openspec/changes/acceptance-conformance/tasks.md)). |
| WEB-007_AC-3 | conforms | | |
| WEB-007_AC-4 | story-corrected | | Failed only because the quoted "Sign in" header button is labelled "Log in" (see WEB-007_AC-1); the label was clarified with the ID kept, and after signing in the header shows "Hi, Jamie" in its place (Unreleased, task 12.3, [acceptance-conformance](../../openspec/changes/acceptance-conformance/tasks.md)). |
| WEB-007_AC-5 | conforms | | |
| WEB-007_AC-6 | conforms | | |
| WEB-007_AC-7 | story-corrected | | The dropdown's button reads "Log out", which the quoted "Logout" does not match under the index's whitespace rule, and the header button it brings back reads "Log in"; both labels were clarified with the ID kept (Unreleased, task 12.3, [acceptance-conformance](../../openspec/changes/acceptance-conformance/tasks.md)). |
| WEB-007_AC-8 | conforms | | |
| WEB-007_AC-9 | conforms | | |
| WEB-007_AC-10 | conforms | | |

### Planted bugs without criterion

| Flag | Reason |
|------|--------|
| BUG_SLOW_RESPONSE | Its 1 to 3 s delay on `GET /products` and `GET /api/products/` broke no in-scope criterion in the task 16.1 sweep, because no criterion states a response time and this change adds no criterion for it (design C2), and preset `drift_and_bug` does not enable it; approving PR: pending maintainer approval (17.2), proposed in [acceptance-conformance](../../openspec/changes/acceptance-conformance/tasks.md). |
