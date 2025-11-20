# AI Concierge & Feature Flags

## AI Chat Mock Provider

Use #robotmcp to create a test suite and execute it step wise.
It shall

- Open http://localhost:9090/ with headless=False
- Launch the chat widget and send the prompt "Recommend a headset for hybrid teams"
- Wait for the mock provider response and assert the JSON payload returned by POST http://localhost:9090/api/ai/ask includes `provider="mock"`
- Verify the assistant reply renders inside the chat transcript and is appended to `chat-history`
- Close Browser

## Theme Toggle Persistence

Use #robotmcp to create a test suite and execute it step wise.
It shall

- Open http://localhost:9090/ with headless=False
- Toggle the theme switch to light mode and confirm the `theme-dark` class is removed from `<body>`
- Reload the page and ensure the stored theme preference persists without flashing the previous theme
- Close Browser

## Feature Flag Rollout Verification

Use #robotmcp to create a test suite and execute it step wise.
It shall

- Send a PUT request to http://localhost:9090/api/admin/flags/NEW_CART_UI with payload `{ "enabled": true }`
- Reload http://localhost:9090/cart with headless=False and check for the presence of the feature-flagged callout banner
- Toggle the flag back to false and verify the banner disappears after refresh
- Close Browser
