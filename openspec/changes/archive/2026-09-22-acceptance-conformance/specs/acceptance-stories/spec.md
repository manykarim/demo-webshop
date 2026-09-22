## Purpose

Maintains a canonical, versioned set of user stories whose acceptance criteria are verified to hold for each workshop-tagged shop image (`workshop-<id>`), so downstream workshops can use them as an unambiguous oracle for tests and self-healing.

## ADDED Requirements

### Requirement: Canonical story set
The repository SHALL contain the workshop story set as one document per story in a single documented location. Each story MUST have a stable story identifier (e.g. `WEB-006`) and each acceptance criterion a stable identifier within its story (e.g. `AC-7`), written as Given/When/Then. The in-scope set MUST include WEB-002 to WEB-007 and API-005 to API-007. Identifiers MUST NOT be reused for a different criterion once they appear in a workshop version.

#### Scenario: Downstream conversion
- **WHEN** a downstream workshop repository imports the story set at a `workshop-<id>` tag
- **THEN** every in-scope acceptance criterion can be referenced by `<story-id>_<criterion-id>`, e.g. `WEB-006_AC-7`

#### Scenario: Criterion withdrawn
- **WHEN** a criterion is removed from a story in a later version
- **THEN** its identifier is marked withdrawn and not assigned to another criterion

### Requirement: Conformance status per criterion
For each workshop image version (`workshop-<id>`), every in-scope acceptance criterion SHALL have exactly one recorded status: `conforms`, `app-fixed`, `story-corrected`, or `planted-bug` with the flag key of each planted bug that produces the deviation.

#### Scenario: Conformance record lookup
- **WHEN** a facilitator looks up `WEB-006_AC-7` for version `workshop-2026-10`
- **THEN** exactly one status is recorded for it, with the flag key of each related planted bug if the status is `planted-bug`

### Requirement: Clean-state conformance
The clean state is: preset `clean` applied in the space under test, no `WORKSHOP_FLAG_<KEY>` environment overrides, and every flag that preset `clean` does not set (`NEW_CART_UI`, `MOBILE_UI_V1`, `SEARCH_V2`) at its seeded default. In the clean state, every in-scope acceptance criterion SHALL hold against every image published with a `workshop-<id>` tag, both in the `default` space and in a named workshop space. Other published tags (`X.Y.Z`, `edge`, `sha-<short-sha>`) carry no conformance guarantee. Deviations from a story MUST NOT exist in the clean state; a deviation kept deliberately MUST be controlled by a registered planted bug flag and appear only while that flag is enabled.

#### Scenario: Clean run
- **WHEN** the conformance checks run in the clean state against the candidate image for a `workshop-<id>` tag
- **THEN** every in-scope criterion passes

#### Scenario: Default and named spaces
- **WHEN** the conformance checks run in the clean state once in the `default` space and once in named workshop spaces
- **THEN** every in-scope criterion passes in both runs

#### Scenario: Registered deviation
- **WHEN** a criterion has status `planted-bug` with flag `BUG_CHECKOUT_TOTAL` and that flag is enabled
- **THEN** the criterion's check fails, and it passes again once the flag is disabled

#### Scenario: Target not in clean state
- **WHEN** the conformance checks run in the `default` space against a target where `NEW_CART_UI` is enabled globally, or run in either the `default` space or a named workshop space against a target where `WORKSHOP_FLAG_BUG_WRONG_PRICE=true` is set
- **THEN** the run reports a setup error naming that flag instead of a criterion failure

### Requirement: Drift-stage conformance
Locator drift SHALL NOT change the result of any in-scope web criterion. With preset `stage2`, `stage3` or `stage4` applied on top of the clean state, every in-scope web criterion MUST hold. Drift changes rendered pages only, so these presets are exercised for every in-scope web criterion whose check drives the rendered page; a web criterion that is checked through the API alone is verified once, in the clean state, and carries no stage variant. With preset `drift_and_bug` applied on top of the clean state, exactly the web criteria whose recorded flags include a bug that this preset enables MUST fail, and every other in-scope web criterion whose check drives the rendered page MUST hold. Every planted bug enabled by preset `drift_and_bug` MUST be recorded on at least one criterion with status `planted-bug`.

#### Scenario: Stage presets
- **WHEN** the web conformance checks run with preset `stage2`, `stage3` or `stage4` applied after `clean`
- **THEN** every in-scope web criterion whose check drives the rendered page passes

#### Scenario: Heal-vs-hide preset
- **WHEN** the web conformance checks run with preset `drift_and_bug` applied after `clean`
- **THEN** exactly the web criteria recorded with `BUG_WRONG_PRICE` or `BUG_CHECKOUT_TOTAL` fail, and every other web criterion whose check drives the rendered page passes

#### Scenario: Heal-vs-hide bugs are detectable
- **WHEN** a workshop version is released
- **THEN** every planted bug enabled by preset `drift_and_bug` is recorded on at least one criterion with status `planted-bug`

### Requirement: Executable conformance checks
Each in-scope acceptance criterion SHALL be covered by at least one automated check that identifies the criterion it verifies. The checks MUST be runnable against a running image by base URL, and MUST NOT be Robot Framework suites, so the repository does not publish ready-made solutions to workshop labs.

#### Scenario: Run against a container
- **WHEN** a maintainer runs the conformance checks with the base URL of a locally started image
- **THEN** a report lists each criterion identifier with its result: `pass`, `fail`, or `error` when a setup or precondition failure prevented the check from running

#### Scenario: Coverage check
- **WHEN** the conformance checks are collected
- **THEN** every in-scope criterion identifier from the story set is referenced by at least one check

### Requirement: Workshop tag gate
A workshop image tag SHALL only be published when the conformance checks pass for the candidate image in the clean state, the drift-stage variants hold, and every planted-bug criterion passes in the clean state and fails while any one of its recorded flags is enabled. A criterion whose result is `error` MUST count as not passing and MUST block the tag, like a failing criterion. The checks MUST run against the candidate image digest to which the workshop tag is then added, not against a separately built image. The gate is a required verification for workshop tags in the sense of the `workshop-image` capability.

#### Scenario: Unregistered deviation blocks the tag
- **WHEN** a `workshop-*` git tag is pushed and a criterion without `planted-bug` status fails in the clean state
- **THEN** no image with that workshop tag is published and the workflow reports the failing criterion identifiers
