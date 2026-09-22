# locator-drift Specification

## Purpose
Provides controlled, reversible, deterministic UI locator drift across every workshop flow, together with a contract of what stays stable per stage, so that self-healing results can be judged objectively.

## Requirements

### Requirement: Drift stages and presets
The shop SHALL support four locator stages: stage 1 (no drift), stage 2, stage 3 and stage 4; stage 1 is the absence of locator flags, so there is no `LOCATOR_V1` flag. Preset `stage1` MUST turn every locator flag off, and presets `stage2`, `stage3` and `stage4` MUST select exactly that stage by enabling that stage's locator flag and disabling the other locator flags. Presets own flag groups: `stage1` to `stage4` SHALL set only locator flags and MUST leave every non-locator flag, including planted-bug flags, unchanged, while preset `clean` MUST turn every locator flag off as well, so `stage1` and `clean` both reset the stage and `clean` is the only preset that also clears the planted bugs. When flags for more than one stage are enabled, the highest stage MUST apply on every page. The workshop status endpoint MUST report the active stage.

#### Scenario: Switching stages
- **WHEN** preset `stage3` is applied after preset `stage2`
- **THEN** every page renders stage 3 and the status endpoint reports stage `v3`

#### Scenario: Conflicting flags
- **WHEN** both `LOCATOR_V2` and `LOCATOR_V4` are enabled
- **THEN** every page, including the product card, renders stage 4

### Requirement: Flow coverage
Drift SHALL apply in stages 2 to 4 to the elements used by the workshop flows: primary navigation including the cart link and cart count badge, the sign-in modal and account menu, the home page hero search and featured products, the product listing and product cards, the product detail page, the cart page, the checkout form, checkout summary and checkout result message, and the AI chat widget.

#### Scenario: Cart badge drifts
- **WHEN** stage 2 is active
- **THEN** the cart count badge in the navigation is no longer matched by `.site-nav__link--cart .badge`

#### Scenario: Checkout form drifts
- **WHEN** stage 2 is active
- **THEN** the checkout email input is no longer matched by `#checkout-email`

#### Scenario: Sign-in modal drifts
- **WHEN** stage 2 is active
- **THEN** the sign-in email input is no longer matched by `#auth-email`

### Requirement: Stage contract
Each stage SHALL change only the locator hooks listed for it and MUST keep all of the following identical to stage 1 on every covered page: visible text, ARIA roles, accessible names, label-to-field associations, form field `name` attributes, link targets, and the order of user-visible content.
- Stage 2 MUST rename element ids and CSS class names of covered elements and MUST keep `data-test` attributes.
- Stage 3 MUST remove all `data-test` attributes and MUST rename element ids of covered form fields.
- Stage 4 MUST remove all `data-test` attributes, rename element ids and CSS class names of covered elements, and change the DOM nesting of product cards, the product detail purchase actions and the checkout form fields by adding or replacing role-less wrapper elements.

#### Scenario: Stage 2 keeps semantics
- **WHEN** the checkout page is rendered in stage 1 and in stage 2
- **THEN** the visible text, roles, accessible names, field labels and field names are identical, while the ids of the form fields and the class name of the checkout form differ

#### Scenario: Stage 3 removes test hooks
- **WHEN** the product listing is rendered in stage 3
- **THEN** no element carries a `data-test` attribute and every product card still shows the same name, price and "Add to cart" button text as in stage 1

#### Scenario: Stage 4 restructures
- **WHEN** the product listing is rendered in stage 4
- **THEN** product cards are nested in different wrapper elements than in stage 1, and a locator based on visible text and role still finds each card's add-to-cart button

#### Scenario: Stage 4 restructures checkout
- **WHEN** the checkout page is rendered in stage 4
- **THEN** each checkout form field is nested in different wrapper elements than in stage 1, and its label still names it

### Requirement: Deterministic drift
For a given stage, the rendered locator hooks of a page SHALL be identical across requests, sessions, spaces and restarts.

#### Scenario: Repeated requests
- **WHEN** the product listing is requested twice in stage 2, from different sessions
- **THEN** both responses contain the same ids, classes and structure

### Requirement: Shop behavior survives drift
All interactive behavior of the shop SHALL work identically in every stage, including adding to cart with badge update and confirmation message, sign-in and account menu, checkout autofill after sign-in, search suggestions, mobile navigation, theme toggle, and the AI chat widget.

#### Scenario: Add to cart in stage 3
- **WHEN** a shopper clicks "Add to cart" on a product card in stage 3
- **THEN** the cart badge count increases and the confirmation message names the product

#### Scenario: Checkout autofill in stage 4
- **WHEN** a signed-in demo user opens the checkout page in stage 4
- **THEN** the email, name and address fields are prefilled as in stage 1

### Requirement: Documented drift mapping
The repository SHALL document, for each stage, every locator hook that changes and its replacement, and the documentation MUST match the implemented behavior.

#### Scenario: Documentation check
- **WHEN** the automated contract tests run
- **THEN** every id and class change rendered in stages 2 to 4 is listed in the drift mapping documentation
