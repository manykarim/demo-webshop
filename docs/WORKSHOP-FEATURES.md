# Workshop Features - Self-Healing Locator Testing

This document describes the workshop features added to the demo-webshop for teaching test automation with self-healing locators, intentional bugs, and AI response variations.

## Overview

The demo-webshop includes toggleable features to simulate real-world testing challenges:

1. **Locator Variations** - Multiple stages that change element IDs, classes, and DOM structure
2. **Intentional Bugs** - Toggleable bugs for testing error detection
3. **AI Response Variations** - Configurable non-determinism in AI responses

## Feature Flags

All workshop features are controlled via feature flags accessible through the admin API.

### Locator Variation Flags

| Flag | Description | Effect |
|------|-------------|--------|
| `LOCATOR_V2` | Stage 2: Change IDs/classes | `product-card` → `item-card`, `auth-email` → `login-email` |
| `LOCATOR_V3` | Stage 3: Remove data-test | Removes all `data-test` attributes from elements |
| `LOCATOR_V4` | Stage 4: Restructure DOM | Adds wrapper divs, changes hierarchy |

### Bug Flags

| Flag | Description | Effect |
|------|-------------|--------|
| `BUG_MISSING_BUTTON` | Hide add-to-cart buttons | Hides button for ~20% of products (id % 5 == 0) |
| `BUG_WRONG_PRICE` | Display wrong prices | Shows 15% higher price for ~33% of products |
| `BUG_BROKEN_LINKS` | Break product links | Creates invalid URLs for ~25% of products |
| `BUG_SLOW_RESPONSE` | Add artificial delays | Adds 1-3 second delay to responses |

### AI Response Flags

| Flag | Description | Effect |
|------|-------------|--------|
| `AI_DETERMINISTIC` | Force mock mode | Always uses deterministic mock responses |
| `AI_RANDOM_DELAYS` | Random response delays | Adds 0.5-2 second random delay |
| `AI_VARIED_RESPONSES` | Vary response text | Cycles through different response templates |

## API Endpoints

### Workshop Status

```bash
GET /api/workshop/status
```

Returns current workshop configuration:
```json
{
  "locator_stage": "v2",
  "active_bugs": ["BUG_WRONG_PRICE"],
  "ai_mode": "deterministic (varied)",
  "all_flags": { ... }
}
```

### Apply Preset

```bash
POST /api/workshop/preset
Content-Type: application/json

{"preset": "stage2"}
```

Available presets:
- `clean` - Reset all workshop features
- `stage1` - Clean slate (no locator changes)
- `stage2` - Changed IDs and classes
- `stage3` - Removed data-test attributes
- `stage4` - Restructured DOM
- `buggy` - All bugs enabled
- `ai_chaos` - AI with delays and variations

### Bulk Flag Update

```bash
POST /api/workshop/flags
Content-Type: application/json

{
  "flags": {
    "LOCATOR_V2": true,
    "BUG_WRONG_PRICE": true
  }
}
```

### List Presets

```bash
GET /api/workshop/presets
```

## Locator Stage Details

### Stage 1 (Default)
Standard element selectors:
- `data-test="product-card"` available
- `id="auth-email"`, `id="chat-input"`
- Class: `product-card`, `button--primary`

### Stage 2 (LOCATOR_V2)
Changed class names and IDs:

| Original | Stage 2 |
|----------|---------|
| `product-card` | `item-card` |
| `product-card__title` | `item-title` |
| `product-card__price` | `item-cost` |
| `button--primary` | `btn-main` |
| `auth-email` | `login-email` |
| `chat-input` | `ai-question` |

### Stage 3 (LOCATOR_V3)
All `data-test` attributes removed. Tests must use:
- CSS selectors
- XPath with text content
- ARIA attributes
- Custom fallback strategies

### Stage 4 (LOCATOR_V4)
DOM restructured with wrapper elements:
```html
<div class="tile-wrapper" data-product-wrapper="1">
  <article class="product-tile">
    <div class="tile-content">...</div>
    <div class="tile-actions">...</div>
  </article>
</div>
```

## Self-Healing Testing Strategy

### Recommended Approach

1. **Start with Stage 1** - Write tests with `data-test` attributes
2. **Move to Stage 2** - Tests should fail, then implement fallback selectors
3. **Move to Stage 3** - Tests should fail, implement text/ARIA-based selectors
4. **Move to Stage 4** - Tests should handle DOM changes

### Example Self-Healing Locator

```python
def find_add_to_cart_button(product_id):
    selectors = [
        f'[data-test="add-to-cart-btn"][data-product="{product_id}"]',
        f'[data-event="add_to_cart"][data-product="{product_id}"]',
        f'[data-event="add-item"][data-product="{product_id}"]',
        f'.product-card button[data-product="{product_id}"]',
        f'.item-card button[data-product="{product_id}"]',
        f'//button[contains(text(), "Add to cart")]',
    ]

    for selector in selectors:
        try:
            element = find_element(selector)
            if element:
                return element
        except:
            continue

    raise ElementNotFound("Add to cart button not found")
```

## Workshop Exercises

### Exercise 1: Basic Test
1. Enable `stage1` preset
2. Write tests using `data-test` attributes
3. Verify all tests pass

### Exercise 2: Handle Class Changes
1. Switch to `stage2` preset
2. Tests will fail
3. Update selectors or add fallbacks
4. Verify tests pass again

### Exercise 3: No Test Attributes
1. Switch to `stage3` preset
2. Tests will fail
3. Implement alternative selectors (text, ARIA, structure)
4. Verify tests pass

### Exercise 4: DOM Restructure
1. Switch to `stage4` preset
2. Tests will fail
3. Handle new wrapper elements
4. Verify tests pass

### Exercise 5: Bug Detection
1. Enable `buggy` preset
2. Write tests that detect:
   - Missing buttons
   - Wrong prices
   - Broken links
3. Verify tests correctly identify bugs

### Exercise 6: AI Testing
1. Enable `ai_chaos` preset
2. Write tests for AI responses that:
   - Handle variable response times
   - Validate response structure (not exact content)
   - Use fuzzy matching for text
