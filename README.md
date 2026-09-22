# AI Testing Workshop Demo

A FastAPI web shop that serves as the system under test for the AI testing
workshop: a product catalogue, cart and checkout, demo accounts with order
history, feature flags that change the UI under your tests, an AI help bot, and
invoice/order-summary PDFs.

The shop runs two ways, and both serve port **9090**:

- from a source checkout with [uv](https://docs.astral.sh/uv/), for working on it;
- from the published container image `ghcr.io/manykarim/demo-webshop`, which is
  what workshop participants use.

Workshop-specific behaviour (locator variations, seeded bugs, AI
non-determinism) is documented in [docs/WORKSHOP-FEATURES.md](docs/WORKSHOP-FEATURES.md).

## Project structure

```
backend/app/        API routers, services, templates, seed data, PDF rendering
backend/tests/      pytest suite
docs/               Workshop features, test prompts, user stories
tools/              Database seeding, container entrypoint, image smoke test
Dockerfile          Two-stage image build (uv + WeasyPrint runtime libraries)
compose.yaml        Development compose file
```

## Development with uv

1. **Install dependencies** - this creates `.venv` from `pyproject.toml` and the
   committed `uv.lock`, so everyone resolves the same versions:

   ```bash
   uv sync
   ```

2. **Seed the database** (products, feature flags, demo users with order history):

   ```bash
   uv run python -m tools.seed_db
   ```

   Seeding is idempotent: it inserts what is missing and no longer refreshes an
   existing database, so running it twice changes nothing. To reset the demo
   data, delete the database file and seed again:

   ```bash
   rm -f workshop.db && uv run python -m tools.seed_db
   ```

3. **Run the API**:

   ```bash
   uv run uvicorn backend.app.main:app --reload --port 9090
   ```

   UI pages are served at <http://localhost:9090>, REST endpoints under `/api/*`,
   OpenAPI docs at `/docs`.

4. **Run the tests**:

   ```bash
   uv run pytest backend/tests
   ```

Copy `.env.example` to `.env` to configure AI credentials and CORS origins.

## Running the container image

The image needs nothing but a port mapping - no volumes, no environment
variables. It seeds itself on first start and reports healthy once the shop
answers on `/health` (roughly 40 seconds at the outside; usually much faster).

```bash
docker run -p 9090:9090 ghcr.io/manykarim/demo-webshop:<tag>
```

All mutable state lives under `/data` inside the container: the SQLite database
at `/data/workshop.db` and generated order documents in `/data/pdfs`.

- **Restarting keeps data.** `docker restart <container>` (or `docker stop` and
  `docker start`) leaves seeded data, your orders and rendered PDFs in place;
  seeding on the next start adds nothing.
- **Recreating resets data.** `docker rm` the container and run a new one to get
  a clean, freshly seeded shop. That is the fastest way back to a known state.
- **Keeping data across recreations** needs a volume. A named volume is the easy
  option, because it inherits the ownership of `/data` from the image:

  ```bash
  docker run -p 9090:9090 -v shopdata:/data ghcr.io/manykarim/demo-webshop:<tag>
  ```

- **A host bind mount must be writable by uid 1000**, the user the image runs as.
  Either hand the directory over, or run as yourself:

  ```bash
  mkdir -p ./shopdata && sudo chown -R 1000:1000 ./shopdata
  docker run -p 9090:9090 -v "$PWD/shopdata:/data" ghcr.io/manykarim/demo-webshop:<tag>
  # or, without chown:
  docker run -p 9090:9090 --user "$(id -u):$(id -g)" -v "$PWD/shopdata:/data" ghcr.io/manykarim/demo-webshop:<tag>
  ```

  If the directory is not writable, the container stops immediately with a
  message naming the path, the effective database URL and both fixes.

## Compose (development)

`compose.yaml` builds the image from this checkout and runs it the way the
published image runs:

```bash
docker compose up --build
docker compose down
```

A `.env` file next to `compose.yaml` is optional and configures AI and CORS
settings. The database and PDF locations are **not** configurable there: compose
pins them to `/data` in the container, so a `.env` written for source runs (for
example a relative database path) cannot move the container's state out of
`/data`. The service declares no volume, so `docker compose restart` keeps the
data and `docker compose up --force-recreate` resets it.

Compose v2.24 or newer is required, because the `.env` file is declared optional.

## Version check and image tags

The running shop reports its version on `/health` and `/api/workshop/status`:

```bash
curl -s localhost:9090/health
# {"status":"ok","version":"workshop-2026-10"}
```

The version is the version tag the image was built for. `edge`, per-commit
images built from a branch, compose builds and source runs all report `dev` -
they are identified by their digest and the `org.opencontainers.image.revision`
label instead.

| Tag | Meaning |
| --- | --- |
| `X.Y.Z` | A released version. Immutable - use this to pin. |
| `workshop-<id>` | The image a given workshop runs on, for example `workshop-2026-10`. Immutable. |
| `sha-<short-sha>` | The most recently published image of that commit. A moving pointer, not a pin. |
| `edge` | The latest build of the default branch. Moves with every push. |

There is deliberately no `latest` tag. For anything you need to reproduce, pin a
version tag or a digest:

```bash
docker run -p 9090:9090 ghcr.io/manykarim/demo-webshop@sha256:<digest>
```

**Rollback** means deploying the previous version tag or a digest recorded
earlier - never rebuilding.

## Order documents (PDFs)

Invoices and order summaries are rendered with WeasyPrint and written to
`WORKSHOP_PDF_OUTPUT_DIR`: `backend/app/static/pdfs` for local runs, `/data/pdfs`
inside the container. That directory is what the `documents` field of the
checkout response reports, and it is `[]` when PDF rendering is unavailable.

Download the documents through the document endpoints, which render a missing
file on demand:

```
GET /api/docs/orders/{order_id}/invoice.pdf
GET /api/docs/orders/{order_id}/summary.pdf
```

These are the only URLs that serve order documents; the static file mount does
not, so do not point tests at static document URLs. Outside the container, where
the native Pango/HarfBuzz libraries are often missing, checkout still creates
orders and the two endpoints answer **503** with a message that PDF rendering is
unavailable in this environment. The image ships those libraries, so PDFs always
render there.

## Feature flags

Feature flags live in the database, with optional `WORKSHOP_FLAG_*` environment
overrides. Toggle them over REST:

```bash
curl -X PUT localhost:9090/api/admin/flags/NEW_CART_UI \
  -H 'Content-Type: application/json' -d '{"enabled": true}'
```

UI templates read the flags dynamically, so a flag changes layout and markup
under a running test - see [docs/WORKSHOP-FEATURES.md](docs/WORKSHOP-FEATURES.md)
for the full list.

## AI help bot

`backend/app/services/ai_service.py` wires `pydantic-ai-slim` with a mock
provider for deterministic runs and an optional OpenAI provider. `POST /api/ai/ask`
returns a typed response:

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
`WORKSHOP_AI_BASE_URL` (or the fallback `BASE_URL`) targets OpenAI-compatible
endpoints such as Azure OpenAI, Groq or Gemini through its OpenAI shim. For
Azure, `.env.example` shows the expected base URL format
(`https://<resource>.openai.azure.com/openai/v1/`); the service applies the
`api-key` header Azure requires by itself.

## Breaking change: dependencies come from uv.lock

The project no longer ships `requirements.txt`; `pyproject.toml` plus the
committed `uv.lock` are the single source of dependency versions, and the image
installs from the lock. If you need a pip-installable list, export one on demand:

```bash
uv export --no-dev --format requirements-txt > requirements.txt
```

## Notes

- The mock AI provider is the default; set real credentials only for local
  experimentation.
- Product imagery is bundled under `backend/app/static/img/` (sourced from
  free-to-use collections on Pexels and Unsplash); swap in your own brand assets
  before launching publicly and review licences for production use.
