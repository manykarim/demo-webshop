## Why

The four workshop changes (`reproducible-image`, `workshop-spaces`, `drift-coverage`, `acceptance-conformance`) are implemented and verified locally: 1622 tests and 42 browser tests pass, and all 95 acceptance criteria conform in both space modes. The maintainer chose to archive them now, so their requirements become the project's specs. Their remaining 26 tasks cannot be done locally. They need a pull request and real workflow runs, the published GHCR package, the Coolify instance, an Apple Silicon machine, real `v0.2.0` and `workshop-<id>` tags, the maintainer's review of the audit decisions, and the workshop day itself. This change keeps that work tracked in one place, word for word, so archiving loses nothing.

## What Changes

- Move the 26 open tasks of the four archived changes into this change, word for word, each marked with its source change and original task number.
- Order them by rollout phase: pull request and merge, first `main` run and package, Coolify and version tag, review and gating and workshop tag, then workshop day and handoff.
- Record in the design how the moved tasks relate to each other and to their archived sources, because their text still uses the original task numbers and says "this change" for the source change.
- No application code, spec or behaviour changes. Every requirement these tasks verify is already in `openspec/specs/` through the four archived changes.

## Capabilities

### New Capabilities
None. This change adds no behaviour; it tracks verification and rollout of behaviour already specified.

### Modified Capabilities
None. `.openspec.yaml` sets `skip_specs: true`: the tasks verify existing requirements of `workshop-image`, `workshop-spaces`, `locator-drift`, `planted-bugs` and `acceptance-stories` without changing them.

## Impact

- **Repositories**: `manykarim/demo-webshop` (merge, workflow runs, tags); the GHCR package `ghcr.io/manykarim/demo-webshop` (visibility, published tags); the Coolify instance; `manykarim/ai-engineering-robotframework` (handoff issue).
- **People**: the maintainer, for the audit decision review (source `acceptance-conformance` 17.2) and the approval PR for the `BUG_SLOW_RESPONSE` row under "Planted bugs without criterion".
- **Archived sources**: `openspec/changes/archive/*-reproducible-image/`, `*-workshop-spaces/`, `*-drift-coverage/` and `*-acceptance-conformance/` keep the moved tasks unchecked, each with a pointer here.
