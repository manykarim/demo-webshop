## 1. Fixes

- [x] 1.1 In `backend/app/static/app.js`, change the deferred focus in `openLoginModal()` so the frame callback focuses the email input only when `document.activeElement` is not inside the dialog (design D1). Verify that `uv run pytest backend/tests/unit/test_script_scan.py backend/tests/unit/test_template_scan.py` still passes.
- [x] 1.2 Add `errorText(detail, fallback)` to `backend/app/static/app.js` (design D2) and use it at the three `throw new Error(detail || …)` sites (sign-in, add-to-cart, assistant). Verify that `grep -n "new Error(detail ||" backend/app/static/app.js` returns nothing and the script scan still passes.

## 2. Regression tests

- [x] 2.1 Add `test_login_focus_is_not_stolen` to `backend/tests/browser/test_drift_smoke.py` (design D3), running in every stage. Verify that it passes, and that it fails when 1.1 is temporarily reverted.
- [x] 2.2 Add `test_rejected_sign_in_shows_readable_error` to `backend/tests/browser/test_drift_smoke.py`: submitting `jamie@flowlinesupply.comdemo123` / `demo123` keeps the dialog open, and its alert has non-empty text that does not contain `[object Object]`. Verify that it passes, and that it fails when 1.2 is temporarily reverted.

## 3. Full verification and rollout

- [x] 3.1 Run `uv run pytest backend/tests` and `uv run pytest -m browser` locally, the browser suite three times in a row, and verify that all runs are green.
- [ ] 3.2 Open a pull request, confirm the `check` and `build` jobs (including the browser smoke) are green, merge it, and confirm that the next `main` run's `test` job passes and `publish` runs. Record the run URL in the pull request.
- [ ] 3.3 Archive this change with `openspec archive fix-login-modal-focus -y`, and verify that `openspec list` no longer shows it and that `openspec/specs/` is unchanged.
