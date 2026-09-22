## Purpose

Isolates workshop state (feature flags, carts, orders) per participant so that many participants can share one hosted shop instance without affecting each other, while local single-user runs keep working unchanged.

## ADDED Requirements

### Requirement: Space resolution
Every request handled by an application page or API route SHALL be associated with exactly one workshop space. Static assets (files under `/static` and other mounted asset routes), the generated API documentation and requests that match no route are the same in every space; they are not associated with a space and keep their existing responses. The space MUST be taken from the first non-empty source in this order of precedence: the `X-Workshop-Space` request header, the `space` query parameter, the `workshop_space` cookie, and otherwise the space `default`. Lower-precedence sources MUST NOT be consulted once a higher-precedence source is present. When the `space` query parameter determines the space, the response MUST set a `workshop_space` cookie to that space. A space determined by the header or by a valid cookie MUST NOT cause a `workshop_space` cookie to be set.

#### Scenario: Header wins
- **WHEN** a request carries header `X-Workshop-Space: octocat` and cookie `workshop_space=hubot`
- **THEN** the request is handled in space `octocat`

#### Scenario: Header beats query parameter
- **WHEN** a request carries header `X-Workshop-Space: octocat` and query parameter `space=hubot`
- **THEN** the request is handled in space `octocat` and the response sets no `workshop_space` cookie

#### Scenario: Human switches space via URL
- **WHEN** a browser opens `/?space=octocat`
- **THEN** the page is rendered in space `octocat` and subsequent requests from that browser without the parameter stay in `octocat`

#### Scenario: No space given
- **WHEN** a request carries no header, parameter or cookie
- **THEN** the request is handled in space `default`

#### Scenario: Requests outside space resolution
- **WHEN** the API documentation page `/docs` and an unknown path such as `/no-such-path` are requested with `X-Workshop-Space: -bad--name-`
- **THEN** `/docs` is served as without the header, and the unknown path answers HTTP 404 as without the header, not HTTP 400

### Requirement: Space identifier format
A space identifier SHALL follow the GitHub username format: 1 to 39 characters, only ASCII letters, digits and single hyphens, not starting or ending with a hyphen. Identifiers MUST be treated case-insensitively and normalized to lowercase. A request to an application page or API route whose identifier in the source that determines its space is invalid MUST be rejected with HTTP 400 and a message describing the expected format. Static assets MUST be served regardless of space inputs.

#### Scenario: Mixed-case handle
- **WHEN** a request carries `X-Workshop-Space: OctoCat`
- **THEN** it is handled in space `octocat`

#### Scenario: Invalid identifier
- **WHEN** a page or API request carries `X-Workshop-Space: -bad--name-`
- **THEN** the response is HTTP 400 and explains the allowed format

#### Scenario: Static asset with invalid identifier
- **WHEN** `/static/app.js` is requested with `X-Workshop-Space: -bad--name-`
- **THEN** the asset is served normally

### Requirement: Space-scoped feature flags
Applying a preset, updating flags, or toggling a single flag SHALL change only the flag values of the requesting space. The flag values of the `default` space are the global values. The effective value of a flag for a request MUST be resolved as follows: the environment override if one is set; otherwise, in the `default` space, the global value; otherwise, in any other space, the value set in that space, or the baseline value if the space has not set the flag. The baseline value is the seeded default with preset `clean` applied. A change in the `default` space MUST NOT affect any other space, and a change in any other space MUST NOT affect `default` or other spaces. A flag change MUST be effective for the next request in the same space.

#### Scenario: Preset does not leak
- **WHEN** space `octocat` applies preset `stage2`
- **THEN** pages requested in space `octocat` render stage 2 and pages requested in space `hubot` render the stage configured for `hubot`

#### Scenario: Default space does not leak
- **WHEN** the `default` space applies presets `stage2` and `buggy` and space `octocat` has set no flags
- **THEN** pages requested in space `octocat` render stage 1 without planted bugs

#### Scenario: Immediate effect
- **WHEN** space `octocat` applies preset `stage3` and immediately requests the product listing
- **THEN** the listing is rendered in stage 3

#### Scenario: Environment override
- **WHEN** the shop runs with `WORKSHOP_FLAG_LOCATOR_V2=false` and space `octocat` enables `LOCATOR_V2`
- **THEN** requests in space `octocat` render without stage 2 drift

### Requirement: Space-scoped carts and orders
Carts SHALL be isolated per space and, within a space, per browser session or `X-Session-ID` header. A cart request without a session id MUST use the fallback session `workshop-demo` of its own space, and cart API responses MUST report the session id without any space prefix. Orders created at runtime MUST be visible only within the space that created them, including order history returned at login. Seeded demo order history MUST be visible in every space.

#### Scenario: Same session id in two spaces
- **WHEN** space `octocat` and space `hubot` both add items using `X-Session-ID: demo`
- **THEN** each space's cart contains only its own items

#### Scenario: Cart API without session id
- **WHEN** space `octocat` adds an item through the cart API without `X-Session-ID`
- **THEN** the cart response reports session `workshop-demo` and the item is not in the cart of the `default` space

#### Scenario: Order history isolation
- **WHEN** a demo user places an order in space `octocat` and then logs in from space `hubot`
- **THEN** the login response in `hubot` contains the seeded order history but not the order placed in `octocat`

### Requirement: Space reset
The shop SHALL provide `POST /api/workshop/reset`, which acts on the requesting space. For a space other than `default` it MUST remove the flag values set in that space, so the space falls back to the baseline values, empty that space's carts, and delete the orders created at runtime in that space. For the `default` space it MUST restore the global flags to their seeded defaults with preset `clean` applied, empty the carts that belong to no space, and delete the runtime orders of `default`. Seeded data and the flag values, carts and orders of other spaces MUST remain unchanged.

#### Scenario: Reset one space
- **WHEN** the `default` space has stage 3 active, space `octocat` has stage 2 active, items in the cart and one runtime order, and `octocat` calls reset
- **THEN** space `octocat` renders stage 1 with an empty cart and no runtime orders, and space `hubot` is unchanged

### Requirement: Active space indicator
When a page is rendered in a space other than `default`, or in any space while shared mode is enabled, the page SHALL display the active space identifier. In shared mode, a page rendered in the `default` space MUST also tell the viewer how to select a personal space. The indicator MUST NOT be affected by locator drift stages.

#### Scenario: Participant checks their space
- **WHEN** a browser opens the home page in space `octocat`
- **THEN** the page shows that the active space is `octocat`

#### Scenario: Default space in local mode
- **WHEN** shared mode is not enabled and a page is rendered in space `default`
- **THEN** no space indicator is shown

#### Scenario: Default space on the shared instance
- **WHEN** a shared-mode instance renders a page for a request without header, parameter or cookie
- **THEN** the page shows that the active space is `default` and explains how to select a personal space with `?space=<github-handle>`

### Requirement: Local mode compatibility
When shared mode is not enabled, requests in the `default` space SHALL behave as before spaces existed: flag, preset and reset operations are allowed without credentials and act on the global state.

#### Scenario: Local participant applies a preset
- **WHEN** a locally running shop without shared mode receives a preset request without space or token
- **THEN** the preset is applied and affects all subsequent requests without a space

### Requirement: Shared mode protections
When `WORKSHOP_SHARED_MODE` is enabled, the shop SHALL require `Authorization: Bearer <WORKSHOP_ADMIN_TOKEN>` for workshop control operations that act on the `default` space, which holds the global state: applying a preset (`POST /api/workshop/preset`), bulk flag updates (`POST /api/workshop/flags`), single flag updates (`PUT /api/admin/flags/{key}`) and reset (`POST /api/workshop/reset`), answering HTTP 401 otherwise. Shop requests in the `default` space, such as browsing, cart changes and checkout, and reads of workshop status, presets and flags MUST NOT require the token. The shop MUST refuse to start in shared mode without an admin token configured. The AI helper MUST use its mock provider regardless of provider configuration. Endpoints MUST NOT list existing spaces or return any space identifier other than the requesting space's.

#### Scenario: Participant forgets the space header
- **WHEN** a shared-mode instance receives a preset request without space and without token
- **THEN** the response is HTTP 401 and no flag changes

#### Scenario: Participant uses their space
- **WHEN** a shared-mode instance receives a preset request with `X-Workshop-Space: octocat` and no token
- **THEN** the preset is applied to space `octocat`

#### Scenario: Shopping in the default space stays open
- **WHEN** a shared-mode instance receives an add-to-cart request and a checkout request without space and without token
- **THEN** neither request is rejected with HTTP 401

#### Scenario: Default-space reset without token
- **WHEN** a shared-mode instance receives a reset request without space and without token
- **THEN** the response is HTTP 401 and no data is removed

#### Scenario: Misconfigured start
- **WHEN** the shop is started with shared mode enabled and no admin token
- **THEN** start-up fails with an error naming the missing setting

#### Scenario: Real AI provider configured
- **WHEN** a shared-mode instance is configured with a non-mock AI provider and a shopper asks the AI helper
- **THEN** the answer is produced by the mock provider

### Requirement: Shared deployment capacity
The shared fallback deployment SHALL serve the target number of concurrent participant spaces running workshop flows. The target is the number of registered participants × 1.25, with a default of 40. By default one shared-mode instance, running as a single process, serves the whole target. If a load test of a single instance at the target fails, participants are split across N independent shared-mode instances by the first character of their handle, and each instance MUST then serve its assigned share of registered participants × 1.25. Every handle character (`a`-`z` and `0`-`9`) MUST then be assigned to exactly one instance. The load test that demonstrates this capacity, run on the build that is deployed for the workshop, MUST show a 95th percentile page response time below 1 second and no server errors, excluding responses deliberately delayed by planted bugs. An earlier load-test run made to tune the deployment is not capacity evidence and is not bound by that bar. Requests in a load test MUST NOT observe workshop state (flags, carts, orders, space indicator) from another space; in particular, an order document requested for an order created in another space MUST answer HTTP 404.

#### Scenario: Load test at target concurrency
- **WHEN** the target number of simulated participants (default 40) each run catalogue, cart, checkout and preset-switching flows in their own space against one instance
- **THEN** p95 page response time is below 1 second, no HTTP 5xx responses occur, and no cross-space state is observed

#### Scenario: Load test after scale-out
- **WHEN** the single-instance load test at the target fails and participants are split across N instances by the first character of their handle
- **THEN** every handle character maps to exactly one instance, and each instance, loaded with its assigned share × 1.25 simulated participants, has p95 page response time below 1 second, no HTTP 5xx responses and no cross-space state
