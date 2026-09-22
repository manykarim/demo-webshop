# Checkout & Auth Journeys

## Sign-in Modal and Prefill

Use #robotmcp to create a test suite and execute it step wise.
It shall

- Open http://localhost:9090/ with headless=False
- Launch the login modal by clicking the header account button
- Authenticate with email `jamie@flowlinesupply.com` and password `demo123`
- Navigate to http://localhost:9090/checkout and verify the form auto-populates email, name, address, and team size
- Close Browser

## Checkout Confirmation and Flash Messaging

Use #robotmcp to create a test suite and execute it step wise.
It shall

- Open http://localhost:9090/products with headless=False
- Add one item to the cart and proceed to http://localhost:9090/checkout
- Complete the checkout form with valid data and submit
- Confirm the success state hides the line items, shows next-step guidance, and triggers a toast message "Order confirmed"
- Close Browser

## PDF Artifact Availability

Use #robotmcp to create a test suite and execute it step wise.
It shall

- Reuse the previous checkout run or seed a fresh order programmatically via POST http://localhost:9090/api/checkout
- From the confirmation view, follow the Invoice and Order Summary links and download both PDFs
- Validate each document downloads from its endpoint - `GET /api/docs/orders/{order_id}/invoice.pdf` and `GET /api/docs/orders/{order_id}/summary.pdf` - answering HTTP 200 with content type `application/pdf` and a non-empty body
- Use Robot Framework's PDFLibrary (or equivalent) to assert the invoice contains the purchaser's name and total amount
- Close Browser
