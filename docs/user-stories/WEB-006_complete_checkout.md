# WEB-006: Complete Checkout

| Field       | Value                                    |
|-------------|------------------------------------------|
| **Story ID**  | WEB-006                                |
| **Title**     | Complete Checkout                      |
| **Priority**  | Critical                               |
| **Component** | Web Frontend, API                      |
| **Labels**    | checkout, order, payment, pdf, form    |

## User Story

**As a** shopper,
**I want to** complete checkout by providing my details,
**So that** I can place an order.

## Acceptance Criteria

### AC-1: Order summary sidebar

**Given** a shopper navigates to the checkout page (`/checkout`)
**When** the page loads and the cart has items
**Then** an order summary sidebar is displayed showing:
  - List of items in the cart with names and prices
  - Subtotal
  - Shipping cost
  - Tax amount
  - Order total (subtotal plus shipping cost plus tax amount, with "Complimentary" shipping counted as 0)

### AC-2: Required form fields

**Given** the checkout page has loaded
**When** the shopper views the checkout form
**Then** the following required fields are present:
  - Email address (input type email)
  - Full name (text input)
  - Address (text input or textarea)

### AC-3: Optional form fields

**Given** the checkout page has loaded
**When** the shopper views the checkout form
**Then** the following optional fields are present:
  - Team size (number input)
  - Special instructions (textarea)

### AC-4: Email validation

**Given** the shopper is filling out the checkout form
**When** the shopper enters an invalid email (e.g., "notanemail")
**Then** a validation error is shown for the email field
**And** the form cannot be submitted

**Given** the shopper enters a valid email (e.g., "test@example.com")
**When** the form is validated
**Then** no error is shown for the email field

### AC-5: Full name validation

**Given** the shopper is filling out the checkout form
**When** the shopper enters a name shorter than 2 characters (e.g., "A")
**Then** a validation error is shown for the name field

**Given** the shopper enters a valid name (e.g., "Test User")
**When** the form is validated
**Then** no error is shown for the name field

### AC-6: Address validation

**Given** the shopper is filling out the checkout form
**When** the shopper enters an address shorter than 5 characters (e.g., "123")
**Then** a validation error is shown for the address field

**Given** the shopper enters a valid address (e.g., "123 Test Street, City")
**When** the form is validated
**Then** no error is shown for the address field

### AC-7: Successful order submission

**Given** the shopper has filled in all required fields with valid data
**And** the cart contains at least one item
**When** the shopper submits the checkout form
**Then** an order is created successfully
**And** a success message is displayed
**And** the success message includes an order number in the format `ORD-` followed by 8 characters from 0-9 and A-F (e.g., `ORD-3F9A1C2B`)

### AC-8: Invoice and summary PDF links

**Given** an order has been successfully placed
**When** the success message is displayed
**Then** the message includes a link to download the invoice PDF
**And** the message includes a link to download the order summary PDF
**And** both links point to valid, downloadable PDF files

### AC-10: Empty cart error on checkout

**Given** the shopper has no items in the cart
**When** the shopper attempts to submit the checkout form
**Then** an error message is displayed: "Your cart is empty"
**And** the order is not created

### AC-11: Validation errors display

**Given** the shopper submits the checkout form with one or more invalid fields
**When** validation is performed
**Then** error messages are displayed next to each invalid field
**And** the form is not submitted
**And** the shopper remains on the checkout page

### AC-12: Cart cleared after successful order

**Given** an order has been successfully placed
**When** the shopper navigates to the cart page (`/cart`)
**Then** the cart is empty
**And** the cart badge in the navigation shows no item count

## Test Data

### Valid Checkout Data

| Field                | Value                      |
|----------------------|----------------------------|
| Email                | test@example.com           |
| Full Name            | Test User                  |
| Address              | 123 Test Street, City      |
| Team Size (optional) | 5                          |
| Special Instructions | Please gift wrap           |

### Validation Edge Cases

| Field     | Invalid Value    | Error Reason               |
|-----------|------------------|----------------------------|
| Email     | ""               | Required field empty       |
| Email     | "notanemail"     | Invalid email format       |
| Email     | "a@b"            | Incomplete email           |
| Full Name | ""               | Required field empty       |
| Full Name | "A"              | Less than 2 characters     |
| Address   | ""               | Required field empty       |
| Address   | "123"            | Less than 5 characters     |
| Address   | "1234"           | Less than 5 characters     |

### Order Number Format

| Pattern          | Example       | Regex                  |
|------------------|---------------|------------------------|
| `ORD-XXXXXXXX`   | ORD-3F9A1C2B  | `^ORD-[0-9A-F]{8}$`    |

### API Endpoints

| Endpoint       | Method | Body                                          | Response                          |
|----------------|--------|-----------------------------------------------|-----------------------------------|
| `/api/checkout` | POST  | `{ email, name, address, team_size, notes }`  | `{ order_id, pdf_urls }`         |

## Notes

- The order summary sidebar should mirror the cart summary from WEB-005 (same subtotal, shipping, tax format).
- Form validation should occur both client-side (immediate feedback) and server-side (API validation).
- Order numbers are `ORD-` followed by 8 characters from 0-9 and A-F, the same format the order API returns.
- PDF download links should be tested for valid HTTP responses (200 status, correct Content-Type header `application/pdf`).
- After a successful order, the success message should be prominent and clearly visible without scrolling.
- The checkout flow depends on a valid cart session (cross-reference WEB-005 for session identification).
- Test the complete happy path: add item to cart -> navigate to checkout -> fill form -> submit -> verify success.
- Verify that the checkout page is not accessible or shows an appropriate state if the cart is empty on initial load.
- Optional fields (team size, special instructions) should not cause validation errors when left empty.

## Revisions

| Version | Criterion | Original wording | New wording | Reason |
|---------|-----------|------------------|-------------|--------|
| Unreleased | WEB-006_AC-1 | Given a shopper navigates to the checkout page (`/checkout`)<br>When the page loads and the cart has items<br>Then an order summary sidebar is displayed showing:<br>- List of items in the cart with names and prices<br>- Subtotal<br>- Shipping cost<br>- Tax amount<br>- Order total | Given a shopper navigates to the checkout page (`/checkout`)<br>When the page loads and the cart has items<br>Then an order summary sidebar is displayed showing:<br>- List of items in the cart with names and prices<br>- Subtotal<br>- Shipping cost<br>- Tax amount<br>- Order total (subtotal plus shipping cost plus tax amount, with "Complimentary" shipping counted as 0) | Clarified that the order total is the subtotal plus shipping plus tax, with complimentary shipping counted as 0. |
| Unreleased | WEB-006_AC-7 | Given the shopper has filled in all required fields with valid data<br>And the cart contains at least one item<br>When the shopper submits the checkout form<br>Then an order is created successfully<br>And a success message is displayed<br>And the success message includes an order number in the format `ORD-xxxx` (e.g., `ORD-1234`) | Given the shopper has filled in all required fields with valid data<br>And the cart contains at least one item<br>When the shopper submits the checkout form<br>Then an order is created successfully<br>And a success message is displayed<br>And the success message includes an order number in the format `ORD-` followed by 8 characters from 0-9 and A-F (e.g., `ORD-3F9A1C2B`) | Clarified the order number format shoppers see, which is the same as in the order API (API-006 AC-2); the order number format in the test data and notes follows. |
| Unreleased | WEB-006_AC-12 | Given an order has been successfully placed<br>When the shopper navigates to the cart page (`/cart`)<br>Then the cart is empty<br>And the cart badge count in the navigation shows 0 | Given an order has been successfully placed<br>When the shopper navigates to the cart page (`/cart`)<br>Then the cart is empty<br>And the cart badge in the navigation shows no item count | Replaces WEB-006_AC-9: with an empty cart, the navigation shows the cart without an item count rather than a count of 0. |
