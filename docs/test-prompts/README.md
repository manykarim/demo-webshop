# Automated Test Prompt Library

This directory contains ready-to-use prompt briefs for #robotmcp (and related) agents to generate automated test suites against the Flowline Supply demo webshop. Each markdown file focuses on a specific area of the application so you can mix and match scenarios during workshops.

## Available Prompts

| File | Focus |
| ---- | ----- |
| `homepage-and-search.md` | Homepage hero smoke tests, navigation toggle, instant search, and typeahead suggestions. |
| `catalogue-and-cart.md` | Product grid coverage, add-to-cart flows, and session-backed cart validation. |
| `checkout-and-auth.md` | Login modal verification, checkout confirmation, and PDF artifact assertions. |
| `ai-and-flags.md` | AI concierge interactions, theme persistence, and feature-flag rollout toggles. |
| `api-contracts.md` | REST API contract checks for products, search, and cart session isolation. |

Use these prompts verbatim or adapt the steps to fit your workshop agenda. Each section already specifies that the agent should create and execute suites stepwise, mirroring the style used across the broader testing playbooks.
