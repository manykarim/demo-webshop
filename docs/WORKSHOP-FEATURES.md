# Workshop Features - Self-Healing Locator Testing

The demo-webshop drifts its locators on demand and plants registered defects, so a
workshop can judge objectively whether a test suite - or an agent healing it -
followed the application or merely papered over a bug.

This document is the contract. It is checked by the contract test suite
(`backend/tests/contract/`): `test_docs_sync.py` compares the tables under
`## Drift mapping` and `## Planted bugs` with the single source of truth,
`backend/app/core/workshop.py`, and fails on a missing, stale or undocumented
row. A hook that drifts without a row here is a bug in the shop, not in the
documentation.

## Stages and precedence

There are four locator stages. Stage 1 is the shop as it ships; stages 2 to 4
rename and restructure the hooks a test suite binds to.

| Stage | Flag | What it does |
|-------|------|--------------|
| 1 | *(none)* | Nothing drifts. Stage 1 is the **absence** of every locator flag, so there is no `LOCATOR_V1`. |
| 2 | `LOCATOR_V2` | Renames covered element ids and CSS class names. `data-test` attributes stay. |
| 3 | `LOCATOR_V3` | Removes **every** `data-test` attribute and renames covered **form-field** ids. Class names stay. |
| 4 | `LOCATOR_V4` | Removes every `data-test` attribute, renames covered ids and class names, and re-nests three components in role-less wrappers. |

**Precedence.** The highest enabled locator flag wins on every page:
`LOCATOR_V4` beats `LOCATOR_V3` beats `LOCATOR_V2`. Enabling `LOCATOR_V2` and
`LOCATOR_V4` together therefore renders stage 4 everywhere, never a mixture.
This is `effective_stage(flags)` in `backend/app/core/workshop.py`, and it is the
only implementation of the rule: `GET /api/workshop/status` reports
`locator_stage: "v<N>"` from the same function.

**Reversible and deterministic.** A stage is a flag value, not a build. For a
given stage the rendered hooks of a page are identical across requests,
sessions, spaces and restarts, so a failing locator is always reproducible.

## Stable contract

Drift never changes what a person or an assistive technology perceives. Every
item below is identical in stages 1 to 4, on every covered page, and is what a
resilient locator should be built on.

| Stays identical | Notes |
|-----------------|-------|
| Visible text | Including button labels, headings and the "Add to cart" text. |
| ARIA roles | Explicit `role` and implicit roles alike. |
| Accessible names | From `aria-labelledby`, `aria-label`, `<label>`, `alt` or content. |
| Label-to-field associations | `label[for]` keeps pointing at its field, whatever the field's id is called in this stage. |
| Form field `name` | `email`, `name`, `address`, `team_size`, `notes`, `query`, `question`, `price_min`, `price_max`. |
| Form `action` and `method` | For example `form[action="/checkout"][method="post"]`. |
| Hyperlink targets | The `href` of `a[href]` and `area[href]`. |
| The order of visible content | Stage 4 adds wrappers; it never moves content past other content. |
| Content `data-*` attributes | `data-product`, `data-product-name`, `data-category` and `data-chat-prompt`. They carry content, not a lookup marker. |
| JS state classes | `is-visible`, `is-success`, `is-error`, `is-info`, `theme-dark`, `site-nav-open`, `has-chat-open`, `chip--selectable`. The script writes state through them, `hidden` and `aria-*`, never through a drifting class. |
| The shared uncovered blocks | `form-field`, `form-field__icon`, `button` and its modifiers `button--primary`, `button--ghost`, `button--text`, `button--lg`. A class an uncovered flow writes literally never drifts. |
| `theme-toggle` and `category-badge` | Uncovered blocks of uncovered flows; the sun/moon icons carry `theme-toggle__icon--sun` and `theme-toggle__icon--moon`. |
| The stable ids | `main-content` (the skip-link target), `price-min-range` and `price-max-range` (the filter sliders, each with an `<output for=…>`), and the newsletter ids `newsletter-email`, `newsletter-hint` and `newsletter-alert`. These six are `STABLE_IDS`; they are the only ids a template may write literally. |
| The workshop space indicator | `p.workshop-space[data-workshop-space="<space>"]` in the site header, with the text `Space: <space>`. The element, its classes, the `data-*` name and the text are produced outside the drift mapping, so they are byte-identical in stages 1 to 4. |
| The shared-mode hint | `p.workshop-space-hint` next to the indicator, with the text `Shared baseline. Use your own space: add ?space=<github-handle> to the URL or send the header X-Workshop-Space.` It is shown on a shared instance in the `default` space only, and is outside drift in the same way. |

**The header shape the script binds to** is part of the contract as well, because
`app.js` uses it in every stage and no stage adds a layout variant to the
navigation:

- the mobile navigation toggle is the **only direct-child `button`** of
  `nav[aria-label="Primary navigation"]`, and it sits **outside** the menu its
  `aria-controls` points at;
- the account menu trigger sits **inside** that menu and is the menu's only
  `button[aria-expanded][aria-controls]`; its panel is what its `aria-controls`
  resolves to and carries `hidden`;
- the "Log in" button is the nav's only `button[aria-haspopup="dialog"]` and
  carries no `aria-expanded`;
- the chat launcher is a **direct child of `body`** with
  `aria-haspopup="dialog"` and `aria-controls`, so it is never confused with the
  "Log in" button;
- the search forms carry `role="search"` with `input[name="query"]`, and the
  search results region is `[role="region"][aria-label="Search results"]`;
- the add-to-cart confirmation is the only element with an explicit
  `role="status"` attribute (note that `<output>` carries `status` implicitly, so
  on `/products` a page-wide status locator is ambiguous);
- the account panel's three lists are named `Saved addresses`, `Payment methods`
  and `Recent orders`, and its logout button `Log out`.

The stylesheet is served per stage from `/assets/styles.<digest>.css` and linked
from the page; `/static/styles.css` no longer exists. `/static/app.js` is the
same file in every stage.

## Drift mapping

One table per covered flow. `Kind` is one of `id`, `class-block`, `class-exact`,
`data-test` and `layout`; `—` means unchanged in that stage.

A `class-block` row renames a BEM **block** and every `block__element` and
`block--modifier` name derived from it, so `product-card__media` becomes
`item-card__media` in stage 2 without a row of its own. A `class-exact` row
overrides one specific name and wins over the block rule. A `data-test` row is
`removed` in stages 3 and 4, where the attribute is not rendered at all. A
`layout` row names the stage 4 structural variant of a component; those three
components are the only ones whose DOM nesting changes.

The same stage-1 name can appear twice with different kinds - `auth-modal`,
`chat-widget`, `search-results` and `checkout-alert` are each a covered id *and*
a covered class - and the two drift to different replacements. The `Kind` column
is what tells the rows apart.

### Navigation and cart badge

| Kind | Stage 1 | Stage 2 | Stage 3 | Stage 4 |
|------|---------|---------|---------|---------|
| id | `primary-nav-menu` | `main-nav-list` | — | `nav-drawer` |
| class-block | `badge` | `count-bubble` | — | `cart-pip` |
| class-block | `site-nav` | `main-nav` | — | `topbar-nav` |
| data-test | `cart-count` | — | `removed` | `removed` |

### Sign-in modal and account menu

| Kind | Stage 1 | Stage 2 | Stage 3 | Stage 4 |
|------|---------|---------|---------|---------|
| id | `account-panel` | `user-menu-panel` | — | `profile-flyout` |
| id | `auth-email` | `login-email` | `signin-email` | `account-email` |
| id | `auth-modal` | `signin-overlay` | — | `login-layer` |
| id | `auth-modal-title` | `signin-heading` | — | `login-layer-title` |
| id | `auth-password` | `login-password` | `signin-password` | `account-password` |
| class-block | `account-dropdown` | `user-menu` | — | `profile-menu` |
| class-block | `auth-modal` | `signin-modal` | — | `login-dialog` |
| data-test | `account-logout` | — | `removed` | `removed` |
| data-test | `account-menu-trigger` | — | `removed` | `removed` |
| data-test | `auth-close` | — | `removed` | `removed` |
| data-test | `auth-email-input` | — | `removed` | `removed` |
| data-test | `auth-password-input` | — | `removed` | `removed` |
| data-test | `auth-submit` | — | `removed` | `removed` |
| data-test | `login-button` | — | `removed` | `removed` |

### Home hero search and featured products

| Kind | Stage 1 | Stage 2 | Stage 3 | Stage 4 |
|------|---------|---------|---------|---------|
| id | `search-results` | `results-list` | — | `finder-results` |
| id | `search-suggestions` | `suggest-list` | — | `typeahead-options` |
| class-block | `hero__search` | `banner-search` | — | `masthead-search` |
| class-block | `product-grid` | `item-collection` | — | `tile-rack` |
| class-block | `search-results` | `results-panel` | — | `finder-panel` |
| data-test | `search-clear` | — | `removed` | `removed` |
| data-test | `search-input` | — | `removed` | `removed` |
| data-test | `search-submit` | — | `removed` | `removed` |

### Listing and cards

| Kind | Stage 1 | Stage 2 | Stage 3 | Stage 4 |
|------|---------|---------|---------|---------|
| class-block | `product-card` | `item-card` | — | `product-tile` |
| class-exact | `product-card__add` | `btn-main` | — | — |
| class-exact | `product-card__cta` | `item-actions` | — | — |
| class-exact | `product-card__price` | `item-cost` | — | — |
| class-exact | `product-card__title` | `item-title` | — | — |
| data-test | `add-to-cart-btn` | — | `removed` | `removed` |
| data-test | `product-card` | — | `removed` | `removed` |
| data-test | `product-count` | — | `removed` | `removed` |
| data-test | `product-link` | — | `removed` | `removed` |
| data-test | `product-price` | — | `removed` | `removed` |
| data-test | `view-details-link` | — | `removed` | `removed` |
| layout | `product-card` | — | — | `wrapped` |

### Product detail

| Kind | Stage 1 | Stage 2 | Stage 3 | Stage 4 |
|------|---------|---------|---------|---------|
| class-block | `product-hero` | `detail-hero` | — | `item-showcase` |
| data-test | `detail-add-to-cart` | — | `removed` | `removed` |
| data-test | `product-not-found` | — | `removed` | `removed` |
| layout | `product-hero-actions` | — | — | `wrapped` |

### Cart

| Kind | Stage 1 | Stage 2 | Stage 3 | Stage 4 |
|------|---------|---------|---------|---------|
| class-block | `cart-item` | `basket-line` | — | `bag-row` |
| class-block | `cart-summary` | `basket-totals` | — | `bag-totals` |
| data-test | `cart-item` | — | `removed` | `removed` |
| data-test | `cart-total` | — | `removed` | `removed` |

### Checkout form, summary and result

| Kind | Stage 1 | Stage 2 | Stage 3 | Stage 4 |
|------|---------|---------|---------|---------|
| id | `checkout-address` | `order-address` | `buyer-address` | `payment-address` |
| id | `checkout-address-error` | `order-address-error` | — | `payment-address-error` |
| id | `checkout-alert` | `order-alert` | — | `payment-alert` |
| id | `checkout-email` | `order-email` | `buyer-email` | `payment-email` |
| id | `checkout-email-error` | `order-email-error` | — | `payment-email-error` |
| id | `checkout-email-hint` | `order-email-hint` | — | `payment-email-hint` |
| id | `checkout-name` | `order-name` | `buyer-name` | `payment-name` |
| id | `checkout-name-error` | `order-name-error` | — | `payment-name-error` |
| id | `checkout-notes` | `order-notes` | `buyer-notes` | `payment-notes` |
| id | `checkout-team-size` | `order-team-size` | `buyer-team-size` | `payment-team-size` |
| class-block | `checkout-alert` | `order-notice` | — | `payment-notice` |
| class-block | `checkout-form` | `order-form` | — | `payment-form` |
| class-block | `checkout-summary` | `order-totals` | — | `payment-totals` |
| data-test | `checkout-address-error` | — | `removed` | `removed` |
| data-test | `checkout-address-input` | — | `removed` | `removed` |
| data-test | `checkout-email-error` | — | `removed` | `removed` |
| data-test | `checkout-email-input` | — | `removed` | `removed` |
| data-test | `checkout-name-error` | — | `removed` | `removed` |
| data-test | `checkout-name-input` | — | `removed` | `removed` |
| data-test | `checkout-notes-input` | — | `removed` | `removed` |
| data-test | `checkout-result` | — | `removed` | `removed` |
| data-test | `checkout-submit` | — | `removed` | `removed` |
| data-test | `checkout-subtotal` | — | `removed` | `removed` |
| data-test | `checkout-tax` | — | `removed` | `removed` |
| data-test | `checkout-team-size-input` | — | `removed` | `removed` |
| data-test | `checkout-total` | — | `removed` | `removed` |
| layout | `checkout-field` | — | — | `grouped` |

### Chat widget

| Kind | Stage 1 | Stage 2 | Stage 3 | Stage 4 |
|------|---------|---------|---------|---------|
| id | `chat-input` | `assistant-question` | `chat-question` | `concierge-question` |
| id | `chat-widget` | `assistant-panel` | — | `concierge-dock` |
| class-block | `chat-launcher` | `assistant-launcher` | — | `concierge-button` |
| class-block | `chat-message` | `assistant-message` | — | `concierge-bubble` |
| class-block | `chat-widget` | `assistant-widget` | — | `concierge-panel` |
| data-test | `chat-input` | — | `removed` | `removed` |
| data-test | `chat-launcher` | — | `removed` | `removed` |

### Add-to-cart confirmation

| Kind | Stage 1 | Stage 2 | Stage 3 | Stage 4 |
|------|---------|---------|---------|---------|
| id | `flash-message` | `toast-message` | — | `notice-banner` |
| class-block | `flash` | `toast` | — | `notice` |

## Planted bugs

Every planted bug is a registered entry of `PLANTED_BUGS` in
`backend/app/core/workshop.py`: a flag key, the flow it damages, a deterministic
trigger and the observable defect. All of them are seeded **disabled**, are
turned on together by preset `buggy`, and are the only thing preset `clean`
clears. They are independent of the locator stage: a bug behaves identically in
stages 1 to 4, which is what makes "did the suite heal or did it hide the bug?"
answerable.

| Flag | Flow | Trigger | Defect |
|------|------|---------|--------|
| `BUG_MISSING_BUTTON` | Catalogue | product id % 5 == 0 | card has no add-to-cart button |
| `BUG_WRONG_PRICE` | Catalogue | product id % 3 == 0 | card price × 1.15, rounded to cents |
| `BUG_BROKEN_LINKS` | Catalogue | product id % 4 == 0 | card links to `/products/invalid-<id>`, which is not a product page (4xx) |
| `BUG_SLOW_RESPONSE` | Catalogue | every request to `GET /products` or `GET /api/products/` | 1 to 3 s delay |
| `BUG_CHECKOUT_TOTAL` | Checkout | any non-empty cart | displayed total omits tax |

`BUG_WRONG_PRICE` damages the **card** only: the cart, the checkout summary, the
created order and its documents keep the real price, so the mismatch is
detectable in a single run. `BUG_CHECKOUT_TOTAL` damages the **displayed** total
only: subtotal and tax stay correct, and the created order and its invoice add up.

`GET /api/workshop/status` reports the active bugs by flag key, in registry
order, as `active_bugs`.

## Presets

A preset is **absolute for the flag groups it owns**: it writes every flag of
that group, so its result never depends on what ran before it, and it leaves the
other groups alone, so presets compose. The three groups are the locator flags,
the planted-bug flags and the AI flags.

| Preset | Owns | Effect |
|--------|------|--------|
| `clean` | locator + bugs + AI | The reset: every locator flag off, every planted bug off, `AI_DETERMINISTIC` on. |
| `stage1` | locator | Every locator flag off. **Bugs are left as they are** - `clean` is the reset, not `stage1`. |
| `stage2` | locator | `LOCATOR_V2` on, the other locator flags off. |
| `stage3` | locator | `LOCATOR_V3` on, the other locator flags off. |
| `stage4` | locator | `LOCATOR_V4` on, the other locator flags off. |
| `buggy` | bugs | All five registered bugs on. Locator flags untouched, so `stage3` then `buggy` gives stage 3 with every bug. |
| `drift_and_bug` | locator + bugs | Stage 4 plus exactly `BUG_WRONG_PRICE` and `BUG_CHECKOUT_TOTAL`; every other locator and bug flag off. The heal-vs-hide exercise. |
| `ai_chaos` | AI | `AI_DETERMINISTIC` off, `AI_RANDOM_DELAYS` and `AI_VARIED_RESPONSES` on. |

`drift_and_bug` is the interesting one: the card price and the checkout total are
both wrong, and both of their stage-1 `data-test` and class selectors are gone,
so a suite must find them by role, label or text *and* still report the defect.

```bash
curl -X POST http://localhost:9090/api/workshop/preset \
  -H 'Content-Type: application/json' -d '{"preset": "drift_and_bug"}'
```

## Control endpoints

The workshop controls are **not advertised**: no path under `/api/workshop/` or
`/api/admin/` appears in `/openapi.json` or in the interactive API
documentation, so an agent exploring the schema does not find a switch that
would make a failing test pass. They remain fully callable.

| Endpoint | Purpose |
|----------|---------|
| `GET /api/workshop/status` | Active stage (`locator_stage`), active bugs (`active_bugs`), AI mode and all flag values. |
| `GET /api/workshop/presets` | The presets above with their descriptions. |
| `POST /api/workshop/preset` | Apply one preset, for example `{"preset": "stage2"}`. |
| `POST /api/workshop/flags` | Set individual flags, for example `{"flags": {"LOCATOR_V2": true}}`. |
| `POST /api/workshop/reset` | Drop everything this space set and start clean again. |
| `GET`/`PUT /api/admin/flags` | Read and write single feature flags. |

Their responses are readable without a token and name the active bugs by flag
key. Workshop material therefore applies presets from a suite setup or a script
whose output the participant's coding agent does not read, and tells agents not
to call `/api/workshop/*` or `/api/admin/*` while diagnosing a failure.

Every control endpoint acts on the **space of the request**, `POST
/api/workshop/reset` included, and on a shared instance a write to the `default`
space answers `401` without the facilitator token. Spaces, the reset response and
that `401`, and the `space` and `version` fields of the status response, are
described in [Workshop spaces](#workshop-spaces).

## Workshop spaces

Every request runs inside a **workshop space**: its own feature flags, its own carts and its own runtime orders. On a shared instance each participant works in a personal space, so switching a preset or filling a cart never changes anybody else's shop. The seeded catalogue, the demo users and their seeded order history are identical in every space.

### Choosing a space

A request takes its space from the first source that carries a value: the `X-Workshop-Space` header, then the `space` query parameter, then the `workshop_space` cookie. When none of them does, the request runs in `default`. The header wins even when the URL also carries `?space=`, so tooling that sets the header in one place stays in its space whatever link it follows. An empty value counts as "not provided" and falls through to the next source.

A space id is a GitHub handle: 1 to 39 characters from `a`-`z` and `0`-`9`, with single hyphens between them, never at the start or the end and never doubled. Ids are case-insensitive, so `OctoCat` and `octocat` are the same space. Anything else is answered with `400` and the format explanation, on every route. Once a source carries a value the lower ones are not consulted at all, so an invalid header is never rescued by a valid cookie.

`default` is reserved. It is the baseline space that every request without a marker lands in, and therefore what participants and agents see when their tooling forgets to send a space. Participants whose handle the format rejects - a legacy handle with a doubled or trailing hyphen - and the participant whose handle is literally `default` use a variant such as `<handle>-ws`.

### Staying in a space in a browser

Only the query parameter sets a cookie. A visit to `/?space=octocat` answers with `workshop_space=octocat; Path=/; Max-Age=2592000; SameSite=Lax; HttpOnly`, so for the next 30 days that browser stays in `octocat` while following ordinary links. Switch back with `?space=default`, which sets the cookie to `default`. A request that only carries the header sets no cookie. A `workshop_space` cookie whose value is not a valid id is answered with `400` and expired in the same response, so a tampered cookie cannot lock a browser out: the next request resolves to `default` again.

### A new or reset space starts clean

A space nobody has touched, and a space right after a reset, starts from the clean baseline: stage 1 locators, no bugs, deterministic AI, an empty cart and no runtime orders. Flag values a space never set come from that baseline and never from the `default` space, so a facilitator demoing a preset in `default` drags nobody along, and one participant cannot move another participant's stage.

Reset your own space with:

```bash
curl -X POST http://localhost:9090/api/workshop/reset -H 'X-Workshop-Space: octocat'
```

It removes that space's flag values, cart items and runtime orders - seeded demo history is untouched - and reports what it removed together with the state it left behind:

```json
{
  "space": "octocat",
  "removed_flags": 3,
  "removed_cart_items": 1,
  "removed_orders": 1,
  "locator_stage": "v1",
  "active_bugs": [],
  "ai_mode": "deterministic"
}
```

### Carts and the fallback session

The cart API identifies a cart by the `X-Session-ID` header; a request without one uses the shared fallback session `workshop-demo`, which exists in every space. The fallback is what makes quick examples work without bookkeeping, and it stays isolated: carts are stored per space, so two participants who both send no session id, or who both send `workshop-demo`, still have separate carts. The cart API reports back the session id you sent, or `workshop-demo`, without a space prefix, so a test that compares the reported session with the one it sent passes in every space.

### Shared mode and the facilitator token

A shared instance runs with `WORKSHOP_SHARED_MODE=true` and a `WORKSHOP_ADMIN_TOKEN`, and it forces the mock AI provider. Shared mode protects the baseline, not the participants: writes that would change the `default` space - `POST /api/workshop/preset`, `POST /api/workshop/flags`, `POST /api/workshop/reset` and `PUT /api/admin/flags/<key>` - then need the facilitator token. Writes inside your own space never need a credential, and reads and the shop itself (catalogue, cart, checkout) are never guarded.

A preset call without a space answers `401` with `WWW-Authenticate: Bearer` and a body that says how to get a space:

```json
{
  "detail": "This is a shared workshop instance. Changing the default space needs the facilitator token. Use your own space: add `?space=<github-handle>` to the URL or send the header `X-Workshop-Space: <github-handle>`."
}
```

The cure is a space, not the token:

```bash
curl -X POST http://localhost:9090/api/workshop/preset \
  -H 'X-Workshop-Space: octocat' -H 'Content-Type: application/json' \
  -d '{"preset": "stage2"}'
```

The token stays with the facilitators, who use it only to check that guard during a rehearsal and to restore `default` if it was changed by mistake:

```bash
curl -X POST http://localhost:9090/api/workshop/reset -H 'Authorization: Bearer <token>'
```

### Status reports the space and the version

`GET /api/workshop/status` answers for the space of the request and reports it next to the build version, so a test can assert that it really is in its own space and against which build:

```json
{
  "version": "dev",
  "space": "octocat",
  "locator_stage": "v2",
  "active_bugs": [],
  "ai_mode": "deterministic",
  "all_flags": { "LOCATOR_V2": true, "BUG_SLOW_RESPONSE": false }
}
```

`version` is the image version (`dev` for an untagged build, otherwise the version tag); `space` is the resolved space id, never another one - no endpoint reports any space but the caller's.

### The space indicator

Every page rendered in a space other than `default` carries an indicator in the layout: `<p class="workshop-space" data-workshop-space="octocat">Space: octocat</p>`. On a shared instance it is on every page, including `default`, where it reads `Space: default` and is followed by the hint "Shared baseline. Use your own space: add ?space=&lt;github-handle&gt; to the URL or send the header X-Workshop-Space." - the fastest way to notice that your tooling lost its space. Because the indicator differs between a local run and the shared instance, visual checks mask `[data-workshop-space]` and `.workshop-space-hint`, or keep one set of baselines per profile.

### Agents, new browser contexts and sign-in

A space travels in a header, a URL or a cookie, so anything that starts with none of them lands in `default`: a new browser context, an incognito window, a fresh container, a second agent session, a curl in another terminal. Give each of them the header, or open `?space=<handle>` once and let the cookie carry it. In Browser Library and Playwright, `extraHTTPHeaders` on the context is the one place to set the header for a whole suite; the context sends those headers to every origin it talks to, so use a context that only talks to the workshop shop.

After switching spaces, sign in again. The sign-in snapshot lives in `localStorage` under `flowline_auth_state` and is per origin, not per space, so a browser that switched space keeps a stale signed-in state while its order history now comes from the new space.

### Who consumes this

The workshop repository's `coolify` profile is the consumer of all of the above: it points the suites at the shared instance and sets `X-Workshop-Space` in one place, so every test run, agent and browser context of a participant works in that participant's space. Operating that instance - deploying the image, the environment, resets, rollback and the load test - is `docs/COOLIFY-RUNBOOK.md`.

