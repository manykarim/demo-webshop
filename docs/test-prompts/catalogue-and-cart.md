# Catalogue & Cart Journeys

## Product Grid Interaction

Use #robotmcp to create a test suite and execute it step wise.
It shall

- Open http://localhost:9090/products with headless=False
- Confirm at least six product cards load with image, category badge, and description text
- Assert that cards preserve intrinsic image ratios by checking computed CSS `object-fit: cover`
- Open the first product detail link in the same tab and verify pricing, description, and Add to cart button are visible
- Close Browser

## Add from Listing and Detail

Use #robotmcp to create a test suite and execute it step wise.
It shall

- Open http://localhost:9090/products with headless=False
- Click the primary Add to cart button on two distinct product cards
- Validate the cart badge in the header updates to reflect the summed quantity
- Navigate to `/cart` and ensure both items, quantities, and line subtotals are present
- Close Browser

## Cart Persistence by Session

Use #robotmcp to create a test suite and execute it step wise.
It shall

- Open http://localhost:9090/ with headless=False
- Add a product to the cart and capture the session cookie value `session_id`
- Refresh the page and verify the cart badge still reflects the prior quantity
- Issue a GET request to http://localhost:9090/api/cart/ with header `X-Session-ID` matching the cookie and confirm the response body mirrors the UI state
- Close Browser
