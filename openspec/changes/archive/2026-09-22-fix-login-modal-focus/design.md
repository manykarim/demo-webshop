## Context

See proposal.md, Why. `openLoginModal()` (`backend/app/static/app.js`) shows the overlay and calls `window.requestAnimationFrame(() => emailInput.focus())`. Playwright's `fill()` focuses its target and then inserts the text. If the frame callback runs between those two steps, the text goes to the email field. The failing CI log shows the email box holding `jamie@flowlinesupply.comdemo123`. The error path does `throw new Error(detail || fallback)` in three places. `new Error([...])` stringifies to `[object Object]`.

## Goals / Non-Goals

**Goals:** no focus steal after the dialog opens; readable error text on every script-rendered failure; a deterministic regression test for the race.

**Non-Goals:** redesigning the modal or its markup. The stable hooks and the drift contract stay unchanged, so the template and script scans keep passing.

## Decisions

### D1. Keep the initial focus, but never steal it

The deferred callback focuses the email input only if `document.activeElement` is not already inside the dialog. Opening the dialog still lands focus on the email field, which is good for keyboard users and was the original intent. A field the user or a test has already focused keeps focus. Alternatives considered:
- **Focus synchronously.** Rejected: the overlay has just been unhidden, and focusing in the same task is unreliable while layout is pending, which is presumably why the frame delay exists.
- **Drop the auto-focus.** Rejected: it would silently change keyboard behaviour for real shoppers.

### D2. One helper turns `detail` into text

`errorText(detail, fallback)` returns `detail` if it is a non-empty string. If `detail` is an array, it returns the entries' `msg` fields joined with `; `, dropping entries without `msg`. Otherwise it returns `fallback`. The three call sites use it. Alternative considered: special-casing sign-in only. Rejected, because add-to-cart and the assistant have the identical bug.

### D3. Make the race deterministic in the test

A browser test replaces `window.requestAnimationFrame` with a queue through `page.add_init_script`. It opens the dialog, focuses and fills the password field, and only then runs the queued callbacks. It asserts that the password field is still focused and the email field is still empty. Against the old code, the flush moves focus to the email field and the test fails every time. A timing-based test would pass or fail at random.

## Risks / Trade-offs

- **[Init script changes page timing]** The queued `requestAnimationFrame` applies only to that one test's page, and the test flushes the queue explicitly. → Other tests keep the real implementation.
- **[Validation messages are technical]** Pydantic messages such as "value is not a valid email address" are shown as they are. → They are readable and accurate. Wording can be improved later without touching the helper's contract.
