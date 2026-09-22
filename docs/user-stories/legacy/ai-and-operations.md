# AI Assistance and Operations User Stories

## Story 1: Chat with an AI product concierge
- **As a** shopper with targeted questions
- **I want** to ask an embedded AI assistant for product recommendations and policy guidance
- **So that** I can get quick answers without leaving the page

**Acceptance Criteria**
- A floating chat launcher opens an accessible modal with conversation history and a message composer.
- Sending a prompt posts to `/api/ai/ask` with the current session context and renders the structured response.
- The assistant supports both deterministic mock mode and provider-backed responses controlled by environment variables.

## Story 2: Toggle site theme instantly
- **As a** visitor sensitive to light levels
- **I want** a one-click theme toggle that remembers my preference
- **So that** the interface adapts to my lighting conditions across visits

**Acceptance Criteria**
- The toggle switches between light and dark themes by adding or removing the `theme-dark` body class.
- The chosen theme persists via `localStorage` and is reapplied on subsequent loads before the UI flashes.
- Iconography and labels update to reflect the active mode for screen reader users.

## Story 3: Control feature flags safely
- **As a** product operations manager
- **I want** to enable or disable experimental UI features without redeploying the app
- **So that** I can run workshops and demos with predictable configurations

**Acceptance Criteria**
- Feature flags are stored in the database with optional environment overrides prefixed by `WORKSHOP_FLAG_`.
- The admin REST endpoint `PUT /api/admin/flags/<flag_name>` toggles flag state with validation and returns the updated flag.
- Templates and services read flag values at request time to adjust UI variants (e.g., new cart layout cues).

## Story 4: Validate experiences with automated AI testing
- **As a** quality engineer
- **I want** prebuilt Robot Framework suites that exercise critical journeys and AI touchpoints
- **So that** I can catch regressions quickly and update baselines when needed

**Acceptance Criteria**
- Robot suites cover smoke navigation, checkout flows, API contracts, AI chat, PDF rendering, and visual comparisons.
- Test execution artifacts (logs, screenshots, PDFs) export to the `logs/` directory with trace-level logging.
- Engineers can generate additional suites from natural language intents using the MCP tooling provided in `tools/mcp_generate.py`.
