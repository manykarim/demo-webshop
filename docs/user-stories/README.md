# User stories

This directory holds the canonical workshop story set: one Markdown file per user story, each with numbered acceptance criteria written as Given/When/Then. Workshop images tagged `workshop-<id>` are checked against these criteria before the tag is published, so the stories at a workshop tag describe how that image behaves in its clean state.

## Provenance

| Field | Value |
|-------|-------|
| Source repository | [`manykarim/ai-workshop-rbcn-2026`](https://github.com/manykarim/ai-workshop-rbcn-2026) |
| Source path | `docs/RF-MCP/1.3.RF-MCP_Automate_Scenarios/user_stories/webshop/{web,api}/` |
| Source commit | `580e816` (`580e81632e5fef88928e22ab7aaa1911fbd2acaf`, 2026-02-09) |
| Import date | 2026-09-21 |

The nine stories were imported verbatim and keep their source file names, so each file can be compared with its source by a plain file diff. Normalizations applied during the import (they change no criterion):

- Example base URLs: `http://localhost:8000` became `http://localhost:9090`, the port the shop listens on. This touches only the example requests in `API-005_cart_operations.md`, `API-006_checkout_order.md` and `API-007_user_login.md`.

Any later change to a story's wording is listed in that story's `## Revisions` section (see [Criterion IDs](#criterion-ids)).

## Stories

Every top-level file in this directory whose name matches `^(WEB|API|AI)-\d{3}_.+\.md$` is a story in scope. Adding a story file brings it into scope; its row must then be added to this table.

| ID | Title | File | Active criteria |
|----|-------|------|-----------------|
| WEB-002 | Browse Product Catalogue | [WEB-002_browse_product_catalogue.md](WEB-002_browse_product_catalogue.md) | 13 |
| WEB-003 | View Product Detail | [WEB-003_view_product_detail.md](WEB-003_view_product_detail.md) | 9 |
| WEB-004 | Search Products | [WEB-004_search_products.md](WEB-004_search_products.md) | 8 |
| WEB-005 | Manage Cart | [WEB-005_manage_cart.md](WEB-005_manage_cart.md) | 9 |
| WEB-006 | Complete Checkout | [WEB-006_complete_checkout.md](WEB-006_complete_checkout.md) | 11 |
| WEB-007 | User Authentication | [WEB-007_user_authentication.md](WEB-007_user_authentication.md) | 10 |
| API-005 | Cart Operations | [API-005_cart_operations.md](API-005_cart_operations.md) | 11 |
| API-006 | Checkout and Order Creation | [API-006_checkout_order.md](API-006_checkout_order.md) | 13 |
| API-007 | User Login (Authentication) | [API-007_user_login.md](API-007_user_login.md) | 11 |

The set has 95 active criteria in total. "Active criteria" counts the `### AC-<n>: <title>` headings in the story file; withdrawn criteria are not counted.

## Criterion IDs

- A criterion is referenced as `<STORY>_<AC>`, for example `WEB-006_AC-7` for the heading `### AC-7: ...` in `WEB-006_complete_checkout.md`. `AC-<n>` is unique within its story.
- IDs are never reassigned. Once an ID has appeared in a workshop version, it always means the same criterion.
- Removing a criterion always requires an entry in the [withdrawn criteria](#withdrawn-criteria) table. The offline story guard rejects a silent removal: per story, the active and withdrawn numbers must form 1 to the highest number without gaps.
- A correction keeps the ID when the verified behavior is unchanged, or when it is a clarification: it only makes a term already in the criterion precise, in line with the story's evident intent. Examples: a card's "price" is the product's price; "Order total" is subtotal plus shipping plus tax, with a "Complimentary" shipping line counted as 0.
- Any other correction changes what is verified. The criterion is then withdrawn and replaced by the next free number in its story: the highest active or withdrawn number plus 1.
- Withdrawn criteria are removed from the story file and listed in the withdrawn criteria table, with their replacement ID if there is one.
- A story file gets a `## Revisions` section at its end on its first correction. Each correction adds one row with the version, the criterion, the original wording, the new wording and the reason:

  ```markdown
  ## Revisions

  | Version | Criterion | Original wording | New wording | Reason |
  |---------|-----------|------------------|-------------|--------|
  | workshop-<id> | WEB-006_AC-7 | Given ...<br>When ...<br>Then ... | Given ...<br>When ...<br>Then ... | Clarified that ... |
  ```

  The version is the workshop version whose story set first contains the new wording. Line breaks inside a wording are written as `<br>`. A withdrawal with a replacement is recorded in one row whose criterion is the replacement ID, whose original wording is the text of the withdrawn criterion, and whose reason names the withdrawn ID.
- Reasons in the Revisions section and in the withdrawn criteria table are written from the shopper's or API consumer's point of view. They never name or hint at a defect, a feature flag, a drift stage, locator stability, a conformance status or a detection purpose. Write "clarified that the displayed price is the product's price", not "so that a wrong card price is detected".

## Withdrawn criteria

Withdrawn IDs are never used again. The version is the workshop version whose story set first lacks the criterion.

| ID | Version withdrawn | Reason | Replacement ID |
|----|-------------------|--------|----------------|
| WEB-004_AC-4 | Unreleased | The pages load their search results from the shop itself rather than from the search API; the search API is described from the API consumer's side instead. | WEB-004_AC-9 |
| WEB-005_AC-8 | Unreleased | API clients identify their cart with the `X-Session-ID` header; the `session_id` cookie identifies the shopper's cart on the shop's pages. | WEB-005_AC-10 |
| WEB-006_AC-9 | Unreleased | With an empty cart, the navigation shows the cart without an item count rather than a count of 0. | WEB-006_AC-12 |

## Interpretation rules

These rules are binding for the checks in this repository and for downstream conversion of the stories.

- **Quoted UI text** in a criterion (the text on a button, link, heading or label) refers to the element's visible text (its rendered text content), not its accessible name. It is matched ignoring case, as a phrase contained in that text. Before comparing, leading and trailing whitespace is trimmed, and every run of whitespace (spaces, tabs, line breaks and indentation in markup) in both the quoted text and the element text counts as one space. Whitespace is never removed, so a word break matters. Examples:
  - "Add to Cart" matches a button whose visible text is "Add to cart", even though its accessible name is the more specific "Add Aurora Neural Headphones to cart".
  - "Tax" matches "Estimated tax".
  - "Log out" matches a label split in markup as "Log" + line break + "out".
  - "Logout" does not match "Log out".
- **Accessible names** (aria-label, alt, associated label) are used only when a criterion speaks of a label or name, for form fields found by their label, or for a control without visible text, such as the "×" close button of the sign-in dialog. A difference between a quoted phrase and an accessible name is never a deviation and never a reason to change an accessible name.
- **"An error message is displayed"** means a message that appears as a result of the action, in an alert-role element or next to the field. Text that was already on the page before the action does not count.
- "e.g.", "or equivalent", example values and example requests or responses are not normative.
- Notes are not normative. A test data table is normative only where a criterion refers to what it defines, such as credentials or the order number format.

## For downstream consumers

- Take the stories from a `workshop-<id>` tag of this repository. The tag pins the exact story text that the image with the same tag was checked against.
- Convert only the story files `docs/user-stories/<STORY-ID>_*.md`. Name each converted scenario with its criterion ID `<STORY>_<AC>`, for example `WEB-006_AC-7`, so results can be traced back to the criterion.
- Apply the [interpretation rules](#interpretation-rules) above. In particular, quoted UI text is matched against the element's visible text, not its role name or accessible name, so converted Robot Framework or Playwright tests follow the same rule as the checks here.
- Do not use withdrawn IDs; the [withdrawn criteria](#withdrawn-criteria) table lists them with their replacements. Wording changes against the source commit are listed in each story's `## Revisions` section.
- Never copy `CONFORMANCE.md` or the conformance tests (`backend/tests/conformance/`) into a participant repository. They are facilitator material.

## Legacy documents

The directory [`legacy/`](legacy/) holds the three earlier story documents without IDs (`shopping-experience.md`, `checkout-and-orders.md` and `ai-and-operations.md`). They are superseded for the flows covered by WEB-002 to WEB-007 and API-005 to API-007, remain the only description of the home page, AI helper and operations topics, and are neither maintained nor checked against the shop.
