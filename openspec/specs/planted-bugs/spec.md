# planted-bugs Specification

## Purpose
Provides registered, deterministic, flag-controlled defects in each workshop flow that tests must detect and self-healing must not mask, independently combinable with locator drift stages.

## Requirements

### Requirement: Bug registry
Every planted bug SHALL be defined by a flag key, the affected flow, a deterministic trigger, and the observable defect. All planted bugs MUST be disabled by default and by preset `clean`, and enabled by preset `buggy`. Presets `stage1`, `stage2`, `stage3` and `stage4` MUST NOT change any planted-bug flag, so preset `clean` is the only preset that clears all planted bugs. The workshop status endpoint MUST report the active planted bugs by flag key.

#### Scenario: Buggy preset
- **WHEN** preset `buggy` is applied
- **THEN** the status endpoint lists `BUG_MISSING_BUTTON`, `BUG_WRONG_PRICE`, `BUG_BROKEN_LINKS`, `BUG_SLOW_RESPONSE` and `BUG_CHECKOUT_TOTAL` as active

#### Scenario: Clean preset
- **WHEN** preset `clean` is applied
- **THEN** the status endpoint lists no active planted bugs and reports stage `v1`

#### Scenario: Stage preset keeps active bugs
- **WHEN** preset `stage1` is applied after preset `buggy`
- **THEN** the status endpoint still lists `BUG_MISSING_BUTTON`, `BUG_WRONG_PRICE`, `BUG_BROKEN_LINKS`, `BUG_SLOW_RESPONSE` and `BUG_CHECKOUT_TOTAL` as active and reports stage `v1`

### Requirement: Catalogue bugs
With `BUG_MISSING_BUTTON` enabled, product cards for products whose id is divisible by 5 SHALL show no add-to-cart button. With `BUG_WRONG_PRICE` enabled, product cards for products whose id is divisible by 3 MUST show a price 15% above the actual price, while the cart, checkout and created orders use the actual price. With `BUG_BROKEN_LINKS` enabled, product cards for products whose id is divisible by 4 MUST link to a product page that does not exist. With `BUG_SLOW_RESPONSE` enabled, responses for the product listing page (`/products`) and the product list API (`GET /api/products/`) MUST be delayed by 1 to 3 seconds; other responses MUST NOT be delayed.

#### Scenario: Price mismatch is detectable in one run
- **WHEN** `BUG_WRONG_PRICE` is enabled and a shopper adds product 3 to the cart from the product listing
- **THEN** the price shown on the product card differs from the unit price shown in the cart

#### Scenario: Missing button
- **WHEN** `BUG_MISSING_BUTTON` is enabled
- **THEN** the card for product 5 has no add-to-cart button and the card for product 4 has one

#### Scenario: Slow catalogue
- **WHEN** `BUG_SLOW_RESPONSE` is enabled and a client requests `/products` and then `/cart`
- **THEN** the `/products` response takes at least 1 second and the `/cart` response is not delayed

### Requirement: Consistent checkout totals
With `BUG_CHECKOUT_TOTAL` disabled, the checkout summary SHALL show subtotal, tax amount and total for a non-empty cart, where the total equals subtotal plus tax, and all three MUST equal the values of the order created from that cart and its invoice.

#### Scenario: Summary matches the order
- **WHEN** a shopper with a non-empty cart opens checkout and places the order
- **THEN** the subtotal, tax and total shown in the checkout summary equal those of the created order

### Requirement: Checkout total bug
With `BUG_CHECKOUT_TOTAL` enabled, the checkout summary for any non-empty cart SHALL show a total that differs from the displayed subtotal plus the displayed tax, while subtotal and tax are shown correctly. The created order and its invoice MUST keep correct totals.

#### Scenario: Inconsistent summary
- **WHEN** `BUG_CHECKOUT_TOTAL` is enabled and a shopper with a non-empty cart opens checkout
- **THEN** the displayed total is not equal to the displayed subtotal plus the displayed tax

#### Scenario: Order stays correct
- **WHEN** `BUG_CHECKOUT_TOTAL` is enabled and the shopper places the order
- **THEN** the created order's total equals its subtotal plus tax

### Requirement: Bugs combine with drift
Planted bugs SHALL behave identically in every locator stage. Preset `drift_and_bug` MUST enable `LOCATOR_V4`, `BUG_WRONG_PRICE` and `BUG_CHECKOUT_TOTAL` and MUST disable every other locator and planted-bug flag, whatever flags were set before it.

#### Scenario: Heal-vs-hide preset
- **WHEN** preset `drift_and_bug` is applied
- **THEN** the status endpoint reports stage `v4` and exactly `BUG_WRONG_PRICE` and `BUG_CHECKOUT_TOTAL` as active, pages render stage 4, product 3's card shows the wrong price, the checkout summary total is inconsistent, and neither the card price nor the checkout summary total is matched by its stage-1 `data-test` or class selector while role and text locators still find both

### Requirement: Workshop controls not advertised
Workshop control endpoints (status, presets, flags, reset, and feature flag administration) SHALL NOT appear in the published OpenAPI schema or interactive API documentation. They MUST remain callable.

#### Scenario: Agent explores the API schema
- **WHEN** a client reads `/openapi.json`
- **THEN** no path under `/api/workshop/` or `/api/admin/` is listed

#### Scenario: Facilitator applies a preset
- **WHEN** a client posts preset `stage2` to the workshop presets endpoint
- **THEN** the preset is applied as before
