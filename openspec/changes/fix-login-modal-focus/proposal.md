## Why

The first `main` run of the image workflow (run 35699906902, merge commit `9f8c5a1`) failed its `test` job. The browser smoke `test_sign_in_and_account_menu[stage3]` typed the demo password into the **email** field. `openLoginModal()` in `static/app.js` focuses the email input inside `requestAnimationFrame`, so on a slow runner that delayed focus can land after the shopper, or a test, has already focused the password field. The keystrokes then go to the wrong field. The server rejected the malformed email with a 422, and the sign-in alert showed `[object Object]`, because the script renders FastAPI's `detail` with `new Error(detail)` and `detail` is an array of error objects for validation errors. The same rendering pattern is used for add-to-cart and the AI assistant.

Both are real defects: a fast typist and the workshop participants' Robot Framework Browser tests can hit the focus steal, and `[object Object]` tells nobody what went wrong. The failed `test` job also blocks `publish`, so no `edge` image can be tagged until this is fixed.

## What Changes

- Opening the sign-in dialog still moves focus to the email field, but the deferred focus never takes focus away from an element that is already focused inside the dialog.
- Error messages shown by the client script are always readable text. A string `detail` is shown as is; a validation `detail` (an array) is shown as its messages joined; anything else falls back to the existing fixed message. This applies to sign-in, add-to-cart and the AI assistant.
- Regression tests in the browser smoke: one reproduces the focus race deterministically, and one checks that a rejected sign-in shows a readable message.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
None. `.openspec.yaml` sets `skip_specs: true`. The fix restores behaviour that `locator-drift` ("Shop behavior survives drift": sign-in works in every stage) already requires; no requirement changes.

## Impact

- **Code**: `backend/app/static/app.js` (`openLoginModal`, and one shared helper for error text used by sign-in, add-to-cart and the assistant).
- **Tests**: `backend/tests/browser/test_drift_smoke.py` (two regression tests, run in every stage).
- **Rollout**: unblocks `workshop-rollout` group 1. The next `main` run's `test` job must pass for `publish` to tag `edge`.
- **Visible text**: sign-in, add-to-cart and assistant failures now show the server's validation messages instead of `[object Object]`.
