## Why

The shop becomes the system under test for a full-day workshop where every participant runs it locally, a self-hosted Coolify instance serves as fallback, and GitHub Actions runs it as a service container. Today none of those can be guaranteed to run the same thing: there are two diverging Dockerfiles (Python 3.12/port 9090/Pango vs. Python 3.11/port 8000/no Pango), `requirements.txt` is completely unpinned, there is no lockfile, no published image, and no way to tell which version is running. Version drift is the most common cause of workshop-day failures, so the shop needs one reproducible, versioned artifact before any workshop feature is built on top of it.

## What Changes

- One container image definition replaces the two existing Dockerfiles; the image listens on port 9090 and reports health.
- Dependencies are resolved from a committed lockfile; builds fail when the lockfile is out of date. `requirements.txt` is removed. **BREAKING** for anyone installing via `pip install -r requirements.txt`.
- The minimum Python version rises from 3.11 to 3.12 (`requires-python >=3.12`, new `.python-version`), matching the image. **BREAKING** for Python 3.11 development environments.
- Demo data is seeded when the container starts, instead of being baked in at build time; recreating a container yields fresh data. Seeding only inserts missing data, never overwrites existing rows and no longer pre-renders PDFs; documents of seeded orders render on first request. As a result, `python -m tools.seed_db` no longer refreshes an existing database; delete `workshop.db` to reset. **BREAKING** for development workflows that re-run the seed to reset data.
- A GitHub Actions workflow builds multi-architecture images (amd64 + arm64) once and pushes each candidate to GHCR by digest without any tag. Workshop, semantic-version, `edge` and commit tags are added to that digest only after every verification required for its ref has passed: this change's native amd64 and arm64 smoke test, plus the `test` job that `drift-coverage` adds and, for workshop tags, the `conformance` job that `acceptance-conformance` adds. A candidate that fails a verification carries no tag at all, not even the commit tag. The package is public.
- The running version is reported by the health and workshop status endpoints so participant setup checks can validate versions, not just presence.
- Inside the image, generated invoice and summary PDFs are written to `/data/pdfs` and served only through `/api/docs/orders/{id}/invoice.pdf` and `/summary.pdf`, which render a missing invoice or summary on demand; `/static/pdfs/` no longer serves them, and the file paths in the checkout API's `documents` field change to match. This keeps all mutable state in `/data` and keeps per-order documents out of the public static mount. Local non-container runs are unchanged. The generated order PDFs committed under `backend/app/static/pdfs/` are removed from version control; only the two `example_*.pdf` files remain. **BREAKING** for clients that fetch order PDFs from `/static/pdfs/`.
- PDF rendering degrades gracefully when native rendering libraries are missing (non-container development runs): the shop still works, checkout returns an empty `documents` list, and PDF endpoints answer with a clear "unavailable" error.
- `README.md` is rewritten to match reality (port 9090, uv, image usage; stale references to missing Robot Framework suites and tools removed from the README), the checkout test prompt no longer checks files under `static/pdfs`, and a development compose file is added. Stale Robot Framework and tooling references in `docs/user-stories/` are left to `acceptance-conformance`, which moves those files to `legacy/`.

## Capabilities

### New Capabilities
- `workshop-image`: How the shop is built, versioned, distributed and started as a container: locked dependencies, published multi-arch tags, seed-on-start, health and version reporting, order documents served only through the document endpoints inside the container, and graceful PDF degradation outside the container.

### Modified Capabilities
<!-- None: no specs exist yet in this repository. -->

## Impact

- **Files**:
  - `Dockerfile` (rewritten); `backend/Dockerfile` and `requirements.txt` (removed)
  - `pyproject.toml` (uv dependency groups, Python 3.12); new `uv.lock` and `.python-version`
  - new `.dockerignore`; `.gitignore`; the 36 generated `invoice_ORD-*`/`summary_ORD-*` PDFs under `backend/app/static/pdfs/` (removed from version control); `.env.example` (CORS port 9090, database URL note)
  - new `compose.yaml` and `.github/workflows/image.yml`
  - `backend/app/core/config.py` (`app_version`); `backend/app/main.py` (health/version); `backend/app/api/workshop.py` (status version)
  - `backend/app/services/pdf_service.py` (lazy import, atomic writes), `backend/app/services/order_service.py` (shared document context, `build_order`) and `backend/app/api/docs.py` (on-demand rendering of both documents, 503)
  - `backend/app/seeds/seed_data.py` (insert-if-missing seeding without PDF rendering; `tools/seed_db.py` itself is unchanged but no longer refreshes an existing database)
  - new `tools/entrypoint.py` (container entrypoint), `tools/smoke_image.py` and `tools/resolve_image_version.py`
  - new shared test harness: the root `backend/tests/conftest.py` with the canonical fixtures and `backend/tests/harness.py`; new integration and unit tests under `backend/tests/`
  - `README.md`; `docs/test-prompts/checkout-and-auth.md`
- **APIs**: `GET /health` and `GET /api/workshop/status` gain `version`. The PDF document endpoints can answer 503 outside the container, and a missing summary now renders instead of failing. Inside the image, `/static/pdfs/` no longer serves order PDFs and the checkout `documents` paths point to `/data/pdfs/...`.
- **Dependencies**: `requires-python >=3.12`; the `dev` extras move to the uv `[dependency-groups] dev` group, resolved through `uv.lock`.
- **Systems**: GHCR package `ghcr.io/manykarim/demo-webshop` (new, public). Coolify switches from building the repository to deploying a tagged image.
- **Downstream**: the workshop repository (`ai-engineering-robotframework`) will pin an image tag in its compose file, setup check and CI service container (none of these exist there yet). `workshop-spaces`, `drift-coverage` and `acceptance-conformance` reuse the shared test harness's fixtures by name, adding only suite-specific conftest files in their own test subdirectories, and extend the workflow job graph defined here: `drift-coverage` adds `test` and `acceptance-conformance` adds `conformance` to `publish.needs`.
- **Order**: first of four changes; `workshop-spaces` and `drift-coverage` build on it, `acceptance-conformance` gates the workshop tag. This change stays active until task 10.5 has checked the image of the first gated workshop tag, and is archived afterwards.
