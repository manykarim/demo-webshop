# Homepage & Search Journeys

## Hero and Navigation Smoke

Use #robotmcp to create a test suite and execute it step wise.
It shall

- Open http://localhost:9090/ with headless=False and viewport 1280x900
- Wait for the Flowline Supply header and hero badge to render
- Capture the primary CTA text and verify it references the seasonal collection
- Toggle the mobile navigation by resizing to 390x844, open the hamburger menu, and assert links for Home, Products, Cart, and Checkout exist
- Close Browser

## Search Results Rendering

Use #robotmcp to create a test suite and execute it step wise.
It shall

- Open http://localhost:9090/ with headless=False
- Enter the query "headphones" in the hero search input and submit
- Verify the inline results list appears with at least one product card containing name, price, and Add to cart button
- Assert that the empty state stays hidden when results are present
- Close Browser

## Search Suggestions Typeahead

Use #robotmcp to create a test suite and execute it step wise.
It shall

- Open http://localhost:9090/ with headless=False
- Focus the hero search input and type "desk" slowly to trigger the suggestion dropdown
- Validate the listbox exposes at least one option with `role=option`, highlighted text, and the query embedded in `<mark>` tags
- Use keyboard ArrowDown and Enter to navigate to the first suggestion and ensure the browser navigates to `/products/<id>`
- Close Browser
