# AI Testing Workshop Demo

This repository contains a FastAPI + Robot Framework demo application that showcases AI-assisted testing workflows:

- **DocTest Visual Testing** (`robotframework-doctestlibrary`) compares UI screenshots and PDFs with tolerances and optional LLM review.
- **Self-healing agents** (`robotframework-selfhealing-agents`) capture locator fixes driven by LLM suggestions.
- **AI agent integration** (`robotframework-aiagent` + `pydantic-ai-slim`) powers a typed product help bot with mock and provider-specific modes.
- **MCP generated tests** (`rf-mcp`) transforms natural-language intents into Robot Framework suites.

## Project structure

```
backend/            FastAPI application
  app/              API, services, templates, seeds, and PDF rendering
tests/robot/        Robot Framework resources, suites, baselines, doctests
tools/              Utility scripts (seed DB, MCP generation)
```

## Getting started

1. **Install dependencies with [uv](https://github.com/astral-sh/uv)**

   ```bash
   uv sync
   ```

   This creates/updates `.venv` from `pyproject.toml`.

2. **Initialise Robot Framework Browser**

   ```bash
   uv run rfbrowser init
   ```

   Playwright browsers are required for the visual and UI suites.

3. **Seed the database** (creates products, feature flags, sample PDFs):

   ```bash
   uv run python tools/seed_db.py
   ```

4. **Run the API**:

   ```bash
   uv run uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
   # or start everything with Docker
   docker compose up --build
   ```

The application serves UI pages at `http://localhost:8000` and REST endpoints under `/api/*`.

## Feature flags

Feature flags live in the database with optional `WORKSHOP_FLAG_*` environment overrides. Use the REST endpoint:

```bash
curl -X PUT localhost:8000/api/admin/flags/NEW_CART_UI -d '{"enabled": true}'
```

UI templates read the flags dynamically to demonstrate the impact on layout (e.g., new cart banner or mobile preview notice).

## AI help bot

`backend/app/services/ai_service.py` wires `pydantic-ai-slim` with a mock provider for deterministic CI runs and an optional OpenAI provider. The `/api/ai/ask` endpoint returns typed responses:

```json
{
  "question": "...",
  "provider": "mock",
  "answer": {
    "product": "Catalogue",
    "summary": "...",
    "highlights": []
  }
}
```

Set `WORKSHOP_AI_PROVIDER=openai` and `WORKSHOP_AI_API_KEY=` to switch providers.
You can also provide `WORKSHOP_AI_BASE_URL` (or fallback `BASE_URL`) to target OpenAI-compatible endpoints such as Azure OpenAI, Groq, Gemini via their OpenAI shim, etc. For Azure, the `.env` example demonstrates the expected base URL format (`https://<resource>.openai.azure.com/openai/v1/`); the service automatically applies the `api-key` header required by Azure.

## PDFs and visual baselines

`PDFService` renders invoices and order summaries using WeasyPrint. Generated PDFs land in `backend/app/static/pdfs/`. Robot suites compare these with baselines in `tests/robot/baselines/` using both strict and AI-assisted comparisons (`Compare Pdf Documents With LLM`).

Homepage, product detail, and cart baselines (`PNG`) enable visual regression checks with `DocTest.VisualTest`. Update baselines as the UI evolves.

## Robot Framework suites

- `01_smoke.robot` – UI navigation with self-healing agents.
- `02_checkout.robot` – API-driven checkout and PDF assertions.
- `03_feature_flags.robot` – Toggle flags via REST and confirm UI results.
- `04_api_contract.robot` – Contract checks for products, cart, checkout, and AI endpoints.
- `05_visual_ui.robot` / `06_visual_pdf.robot` – Visual AI-assisted comparisons.
- `07_ai_chat.robot` – Exercises the AI help bot and `robotframework-aiagent` for typed responses.
- `08_doctests.robot` – Runs doctest specifications covering RAG ranking, totals, and prompt shaping.
- `09_mcp_generated_runner.robot` – Uses `tools/mcp_generate.py` to build suites from natural language.

Execute all suites with:

```bash
uv run robot tests/robot/suites
```

The generated suites appear in `tests/robot/generated/`.

## MCP intent generation

Create a suite from natural language:

```bash
uv run python tools/mcp_generate.py \
  --intent "Add two items to the cart and check out" \
  --output tests/robot/generated/intent_checkout.robot \
  --stepwise
```

The script writes a ready-to-run Robot suite referencing shared keywords.

## Notes

- Visual and AI comparisons rely on baseline assets provided under `tests/robot/baselines/`. Regenerate them once the app UI is final.
- `robotframework-browser` requires `rfbrowser init` after installation to download Playwright browsers.
- The mock AI provider is the default; set real credentials only for local experimentation.
- Product imagery is bundled under `backend/app/static/img/` (sourced from free-to-use collections on Pexels and Unsplash); swap in your own brand assets before launching publicly and review licences for production use.
