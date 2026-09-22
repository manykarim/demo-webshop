## Why

The workshop turns user stories into OpenSpec acceptance specs that serve two roles: the target for prompt-driven test creation, and the judge that decides whether a self-heal is legitimate or hides a regression. A detailed set of stories for this shop already exists (from the RBCN 2026 workshop: 28 stories, 233 acceptance criteria), but it has never been checked against the application. A first read already shows likely mismatches, e.g. stories expect order numbers matching `ORD-` plus digits while the shop generates eight hexadecimal characters, and stories expect per-field messages for a too-short name or address while the form only has native required/email checks and the server answers with a raw validation error. A judge that disagrees with the application in its clean state would make every workshop exercise ambiguous.

## What Changes

- Import the stories used by workshop labs into this repository as the canonical story set: WEB-002 to WEB-007 (catalogue, product detail, search, cart, checkout, authentication) and API-005 to API-007 (cart, checkout, login), about 95 acceptance criteria, with stable story and criterion identifiers. The older, lighter story files are superseded.
- Audit every in-scope criterion against the shop and resolve each deviation in exactly one way: fix the application, correct the story, or turn it into a flag-controlled planted bug.
- No deviation is allowed in the clean state: with the `clean` preset, every in-scope criterion holds, both in the `default` space that local runs use and in named workshop spaces.
- Locator drift changes no criterion result: the web criteria also hold in drift stages 2–4, and the heal-vs-hide preset `drift_and_bug` breaks exactly the criteria registered for its bugs.
- Record a conformance status per criterion for each workshop image version (`workshop-<id>`).
- Add an automated conformance check that runs against the candidate image digest that would receive the workshop tag, and blocks the tag when an unregistered deviation exists.

## Capabilities

### New Capabilities
- `acceptance-stories`: The canonical, versioned story set with stable identifiers, per-criterion conformance status, the clean-state and drift-stage conformance guarantees, how deliberate deviations must be registered as planted bugs, and the release gate that checks conformance before a workshop tag.

### Modified Capabilities
None. The audit registered no new planted bug: every deviation it kept is controlled by a flag that was already registered, so this change writes no delta for an existing capability.

<!-- `workshop-image` is not modified: the conformance gate is one of the verifications required for workshop tags under that capability, which `reproducible-image` owns. -->

## Impact

- **Docs**: `docs/user-stories/` restructured into one file per story with IDs (imported from `manykarim/ai-workshop-rbcn-2026`, `docs/RF-MCP/1.3.RF-MCP_Automate_Scenarios/user_stories/webshop/`), plus a conformance record.
- **Code**: application fixes as found by the audit (scope unknown until the audit runs; expected areas: checkout validation feedback, product not-found page, catalogue filter bounds), new conformance tests under `backend/tests/conformance/` (suite fixtures only; regression tests for fixes reuse the shared harness fixtures from `reproducible-image`), and no new planted bug flag: the audit mapped the registered flags to existing criteria, so `PLANTED_BUGS`, the `## Planted bugs` table of `docs/WORKSHOP-FEATURES.md` and the `planted-bugs` spec are unchanged and this change has no `specs/planted-bugs/spec.md` delta.
- **Tests config**: `pyproject.toml` registers the markers `ac`, `planted_bug` and `conformance` and extends `drift-coverage`'s `addopts` to `-m 'not browser and not conformance'`. The suite selects its target only through `--base-url`.
- **CI**: the image workflow from `reproducible-image` gains a `conformance` job that tests the untagged candidate digest pushed by `build`, next to `drift-coverage`'s `test` job, once in the `default` space and once in per-check spaces. `publish` needs it and, for `workshop-*` tags, creates no tag at all (`sha-<short>` included) unless both legs pass. On `main` it runs without blocking.
- **Downstream**: the workshop repository converts this story set into its `openspec/specs/shop/*` acceptance specs, preserving criterion IDs for test traceability.
- **Order**: last of the four changes; runs after `drift-coverage` (final UI) and `workshop-spaces` (final cart/order scoping), before the workshop tag. `drift-coverage` is archived before this change starts; since the audit added no planted bug, this change has no `planted-bugs` delta to write or archive. `reproducible-image` may still be active: its task 10.5 checks the image level of this change's first workshop tags before it is archived.
