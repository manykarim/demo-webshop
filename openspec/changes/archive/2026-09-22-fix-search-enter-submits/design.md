## Context

See proposal.md, Why. In `setupTypeahead` (`backend/app/static/app.js`), `renderSuggestions` finishes with `setActive(0)`. The keydown handler opens the active suggestion on Enter when `activeIndex >= 0`. `setActive(-1)` wraps to the last option, so it cannot express "nothing active".

## Goals / Non-Goals

**Goals:** Enter submits the typed search unless the shopper has moved into the suggestion list; a deterministic regression test.

**Non-Goals:** changing the suggestion endpoint, the debounce, the markup or the stable hooks.

## Decisions

### D1. Render suggestions with no active option

After rendering, set `activeIndex = -1` and mark every option `aria-selected="false"`, instead of calling `setActive(0)`. ArrowDown then calls `setActive(0)` through the existing handler. This matches the common search-box pattern, where suggestions assist but don't capture Enter. It also removes the timing dependence entirely. Alternatives considered:
- **Keep auto-highlight, but ignore Enter within N ms of rendering.** Rejected: that only moves the race elsewhere.
- **Make Enter always search.** Rejected: it breaks keyboard selection of a suggestion, which the browser smoke covers.

### D2. Test the arrived-suggestions case explicitly

The regression test waits for a visible option before pressing Enter. That is exactly the state in which the old code navigated away, so the test fails against the old code every time, independent of runner speed.

## Risks / Trade-offs

- **[Behaviour change for keyboard users]** A shopper who relied on Enter picking the first suggestion now needs ArrowDown first. → That is the standard pattern, and it's documented in the proposal's Impact for workshop material.
