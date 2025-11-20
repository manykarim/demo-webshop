# API Contract & Data Integrity

## Products Catalogue Contract

Use #robotmcp to create a test suite and execute it step wise.
It shall

- Send a GET request to http://localhost:9090/api/products
- Validate the response status is 200 and the payload contains an array of product objects with keys `id`, `name`, `price`, and `image_url`
- Assert that each product price is greater than zero and image URLs resolve with a HEAD request
- Persist the first product ID for subsequent steps

## Search Endpoint Reliability

Use #robotmcp to create a test suite and execute it step wise.
It shall

- Invoke http://localhost:9090/api/search/?query=keyboard
- Verify the response matches the schema `{ results: [ { id, name, description, price, image_url } ] }`
- Confirm that each result ID corresponds to a product from the catalogue endpoint validated earlier
- Log execution time and raise a warning if the call exceeds 500 ms

## Cart API Session Isolation

Use #robotmcp to create a test suite and execute it step wise.
It shall

- Create two distinct session identifiers and add different products to each cart via POST http://localhost:9090/api/cart/items
- Ensure GET http://localhost:9090/api/cart/ respects the `X-Session-ID` header and returns only the items for that session
- Validate totals computed by the response align with the sum of line items returned
