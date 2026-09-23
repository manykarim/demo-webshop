## Why

Both `conformance` legs of the first `main` run ([run 35699906902](https://github.com/manykarim/demo-webshop/actions/runs/35699906902)) failed one criterion, WEB-004_AC-8, in a different variant in each leg (`stage2` in one, `drift_and_bug` in the other). The check typed "headphones" and pressed Enter, but landed on the product page of "Aurora Neural Headphones" instead of the search results. The typeahead highlights the first suggestion as soon as suggestions arrive (`renderSuggestions` ends with `setActive(0)`), and Enter with a highlighted suggestion opens that product. So the same keystroke searches or navigates depending on whether Enter comes before the 300 ms debounce and the suggestion fetch. WEB-004_AC-3 requires that submitting the search form, including by pressing Enter, shows the results. The conformance gate caught a real defect, intermittently.

## What Changes

- No suggestion is highlighted when suggestions appear. ArrowDown and ArrowUp still move into the list (ArrowDown now selects the first suggestion), and Enter opens a suggestion only after the shopper has moved to one. Otherwise Enter submits the typed search.
- A browser regression test waits until the suggestions are visible, presses Enter, and expects the search results on the same page.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
None. `.openspec.yaml` sets `skip_specs: true`. The fix restores behaviour that `acceptance-stories` already requires through WEB-004_AC-3 and AC-8; no requirement changes.

## Impact

- **Code**: `backend/app/static/app.js` (`renderSuggestions` in the typeahead).
- **Tests**: `backend/tests/browser/test_drift_smoke.py` (one regression test in every stage). The existing keyboard-selection test keeps passing: it presses ArrowDown once, which now selects the first suggestion instead of the second.
- **Rollout**: the `conformance` gate must be reliably green before any `workshop-*` tag (`workshop-rollout` group 4).
- **Behaviour visible to participants**: typing a query and pressing Enter always searches. Robot Framework suites that pressed Enter to open the first suggestion must press ArrowDown first.
