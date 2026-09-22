## 1. Fix

- [x] 1.1 In `backend/app/static/app.js`, replace the `setActive(0)` at the end of `renderSuggestions` with `activeIndex = -1` and set `aria-selected="false"` on every rendered option (design D1). Verify that `uv run pytest backend/tests/unit/test_script_scan.py backend/tests/unit/test_template_scan.py` passes.

## 2. Regression test

- [x] 2.1 Add `test_enter_searches_after_suggestions_arrive` to `backend/tests/browser/test_drift_smoke.py` (design D2): on `/`, type "headphones", wait until an option is visible and none is selected, press Enter, and expect the "Search results" region to be visible on `/`. Verify that it passes in every stage, and that it fails when 1.1 is temporarily reverted.

## 3. Verification and rollout

- [x] 3.1 Run `uv run pytest backend/tests`, `uv run pytest -m browser` three times in a row, and the WEB-004 conformance module against a locally built image in both space modes. Verify that all runs are green.
- [ ] 3.2 Open a pull request, confirm `check` and `build` are green, merge it, and confirm that both `conformance` legs of the next `main` run pass all 95 criteria.
- [ ] 3.3 Archive this change with `openspec archive fix-search-enter-submits -y`, and verify that `openspec/specs/` is unchanged.
