> **Legacy document, superseded.** For the flows covered by the stories WEB-002 to WEB-007 and API-005 to API-007 (catalogue, product detail, search, cart, checkout and sign-in), this file is superseded by the story set in [`docs/user-stories/`](../README.md). It is still the only description of the home page, AI helper and operations topics. This file is neither maintained nor gated: nothing verifies that the shop still behaves as described here.

# Checkout and Orders User Stories

## Story 1: Review cart contents
- **As a** shopper preparing to purchase
- **I want** to review the items, quantities, and totals in my cart
- **So that** I can confirm everything is correct before I check out

**Acceptance Criteria**
- The cart page lists all line items with images, unit prices, quantities, and subtotals.
- Users can adjust quantities or remove items, triggering cart recalculation via `/api/cart` endpoints.
- The order summary card updates totals instantly and reflects feature-flagged UI enhancements when enabled.

## Story 2: Complete checkout with minimal friction
- **As a** busy buyer
- **I want** a streamlined checkout form that captures only necessary details
- **So that** I can place my order quickly without confusion

**Acceptance Criteria**
- The checkout page requests contact info, shipping details, and optional team size in a single view.
- Form validation surfaces inline feedback for required fields and blocks submission until errors are resolved.
- Submitting the form calls `/api/checkout` and, on success, displays a confirmation state with next-step guidance.

## Story 3: Receive confirmation artifacts
- **As a** buyer who needs records
- **I want** to download a PDF invoice or order summary right after checkout
- **So that** I can share the receipt with finance or store it for reference

**Acceptance Criteria**
- Successful checkout triggers WeasyPrint generation of invoice and order summary PDFs.
- Download links are shown on the confirmation screen and return the generated assets from `/static/pdfs/`.
- Robot Framework regression tests compare PDFs with baselines to detect rendering drift.

## Story 4: Resume checkout with saved account context
- **As a** returning customer with a stored profile
- **I want** the checkout form to pre-fill my details after I sign in
- **So that** I avoid retyping shipping information every visit

**Acceptance Criteria**
- Logging in via the modal stores an auth payload in local storage and updates the account region UI.
- Visiting the checkout page hydrates the form with the customer’s name, email, and primary address pulled from the stored state.
- Signing out clears stored data and resets the form to blank values.
