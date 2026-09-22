## Context

Motivation and scope: see `proposal.md` (Why, What Changes). Requirements: see `specs/workshop-image/spec.md`. This section only records the current state that shapes *how* the change is built. All facts about this repository were checked against branch `openspec/workshop-plan`. The closing "Consumers" paragraph describes planned downstream use and is not a checked fact.

**Build and dependencies**
- `Dockerfile` (python:3.12-slim, apt Pango/HarfBuzz + curl, `pip install -r requirements.txt`, uid 1000, port 9090, `RUN python -m tools.seed_db` at build time) and `backend/Dockerfile` (python:3.11-slim, no Pango libraries, port 8000, `--proxy-headers --forwarded-allow-ips *`, no seeding) disagree. Coolify currently builds the repository from the root `Dockerfile`. Commit `82cb434` added curl specifically for the health check.
- `requirements.txt` and `pyproject.toml` `[project.dependencies]` are both unpinned. There is no `uv.lock`, no `.dockerignore`, no `.github/workflows/`, no compose file.
- `pyproject.toml` declares a setuptools build backend with no package configuration. Building the project fails: `uv build` on a scratch copy of the working tree reports `Multiple top-level packages discovered in a flat-layout: ['backend', 'openspec']`. A plain `uv sync`, which installs the project, is therefore broken in this working tree today. The failure needs a second top-level package beside `backend/` — here the untracked `openspec/` directory, since setuptools' flat-layout discovery ignores `docs/` and `tools/` — so a checkout of tracked files alone does not hit it, while any working tree with `openspec/` present does.
- A trial `uv lock` of the current dependency list (scratch copy, uv 0.8.15, `requires-python >=3.12`, 2026-09-16) resolved 77 packages with no sdist-only package. Every package with compiled code (among them pydantic-core, uvloop, httptools, greenlet, cffi, pillow, brotli, zopfli) ships cp312/abi3 manylinux wheels for both x86_64 and aarch64. WeasyPrint resolved to 70.0. `uv sync --locked` against an outdated lock fails with ``The lockfile at `uv.lock` needs to be updated, but `--locked` was provided.`` The trial lock contains `8000` inside hashes and URLs three times, so repository-wide greps for the old port must exclude `uv.lock`.
- The repository is public (`gh repo view`), default branch `main`. The GHCR package `ghcr.io/manykarim/demo-webshop` is not found via the API yet.

**Runtime**
- `backend/app/core/config.py` uses paths relative to the working directory: `database_url=sqlite+aiosqlite:///./workshop.db`, `pdf_output_dir=backend/app/static/pdfs`, `base_dir=backend/app` (WeasyPrint `base_url` for `static/img/...` in `templates/pdf/*.html`). The process must run from the source root unless these are overridden. pydantic-settings also reads `.env` from the working directory.
- `.env.example` sets `WORKSHOP_DATABASE_URL=sqlite+aiosqlite:///./workshop.db` (equal to the code default), CORS origins on port 8000 and `WORKSHOP_FEATURE_FLAG_CACHE_SECONDS=10`. Copying it to `.env` is the documented way to configure AI keys.
- `backend/app/core/feature_flags.py` keeps a process-local `TTLCache`, and `set_feature_flag` only clears the cache of the process that handled the write.
- `templates/home.html` renders absolute URLs with `request.url_for(...)`, which depend on proxy headers when the shop runs behind Coolify's TLS proxy.
- `/health` (`backend/app/main.py`) returns `{"status": "ok"}`. `WorkshopStatus` (`backend/app/api/workshop.py`) has no version. `FastAPI(version="0.1.0")` is hard-coded.

**Seeding (idempotency verified)**
`tools/seed_db.py` runs `backend/app/seeds/seed_data.main()`: `init_db()` (create_all), then `seed_products`, `seed_feature_flags`, `seed_users`.

| Function | Behavior when run against an already seeded database | Meets "no duplicate, no overwrite"? |
|---|---|---|
| `ensure_product_columns`, `ensure_order_columns` | `PRAGMA table_info`, `ALTER TABLE` only for missing columns. The models already declare every column these helpers add (`models/product.py`: rating, review_count; `models/order.py`: user_id, shipping/billing_address_id, payment_method_id), so they are no-ops on a fresh database. | Yes |
| `seed_products` | Upsert by SKU: overwrites all fixture fields of existing rows | No duplicates, but overwrites |
| `seed_feature_flags` | Inserts only missing keys, never touches existing values | Yes |
| `seed_users` | Existing user: rewrites name and password hash, bulk-deletes their addresses, payment methods and orders, then recreates the history through `OrderService.create_order` with new ids, new `ORD-<uuid>` numbers and re-rendered PDFs. The bulk `delete(Order)` bypasses the ORM cascade, and no SQLite `PRAGMA foreign_keys` listener exists, so `order_items` rows are orphaned. | **No** |

Runtime orders from `POST /checkout` and `POST /api/checkout` have `user_id = NULL` and survive a re-seed. The seeded history does not.

`seed_users` also mutates process state: `payment_data.pop("billing_address_index", None)` (`seed_data.py:355`) removes the key from the module-level `USERS_FIXTURES`. Any second `seed_data.main()` in the same process, even against a fresh database file, therefore creates payment methods with `billing_address_id = NULL`, which the login response exposes (`api/auth.py:70`). Reproduced: after one `main()`, the payment-method dicts hold only `brand`, `exp_month`, `exp_year` and `last4`. This affects every in-process seed: tests, harness fixtures and a failed seed followed by a retry.

**PDF rendering**
- `backend/app/services/pdf_service.py` imports `weasyprint` at module level. It is imported by `main.py`, `api/checkout.py`, `api/docs.py`, `services/order_service.py`, `seeds/seed_data.py` and `tools/generate_example_pdfs.py`. Without the native Pango libraries, the application cannot be imported at all, and neither can the unit test `backend/tests/unit/test_order_service.py`.
- `PDFService._render_pdf_sync` writes straight to the final path, so a concurrent reader that sees the file exist can serve a half-written PDF.
- `OrderService.create_order` commits the order *before* rendering documents. `generate_documents` builds one full context (`order` with `order_number`, `order_date`, `subtotal`, `tax`, `total`, `status`; `customer`; the cart items) for both templates.
- `api/docs.py` renders a document on demand when its file is missing, but only the invoice branch works today. The summary branch of `_ensure_document` passes an `order` without `order_date` and `tax` and no `customer`, while `templates/pdf/order_summary.html` uses all three (`:152-153`, `:160`, `:197`). A missing `summary_*.pdf` therefore returns 500 (reproduced: `UndefinedError: 'customer' is undefined`). The defect is hidden today because `seed_users` renders both PDFs eagerly through `create_order`, and `api/auth.py:82-83` returns `summary_url` for every seeded order.
- `order_summary.html` also uses `item.image_url`, which neither path supplies, so it renders an empty `src` today.
- Thirty-six generated `invoice_ORD-*`/`summary_ORD-*` PDFs are committed under `backend/app/static/pdfs/`, next to `example_invoice.pdf` and `example_order_summary.pdf`.

**Tests**
`backend/tests/` holds two unit tests (`unit/test_workshop.py`, `unit/test_order_service.py`), an empty `integration/` package and no `conftest.py`. The three later changes each plan integration or contract tests against a temporary database.

**Repository hygiene relevant to tooling**
Line endings are mixed: 36 tracked files have CRLF in the index (for example `README.md`, `backend/app/main.py`), and there is no `.gitattributes`. The maintainer works from a Windows checkout. `.gitignore` covers `.env` at any depth but not `workshop.db`.

**Consumers (out of scope, for orientation only; planned downstream use, not a checked fact)**
The participant repository `manykarim/ai-engineering-robotframework` today holds a single initial commit whose tracked files are `LICENSE` and `README.md`, plus untracked workshop preparation notes under `docs/` and empty openspec scaffolding: no compose file, setup check, CI workflow or Robot Framework configuration exists there yet. The workshop material is expected to pin one image tag in its compose file, setup check and CI service container, and to define one profile for a local run (`http://localhost:9090`) and one for the hosted Coolify instance (hosted URL plus the `X-Workshop-Space` header that `workshop-spaces` introduces); the intended naming is a `robot.toml` with `local` and `coolify` profiles, which is not fixed yet. Nothing in this change depends on that. The surface it must keep stable is a pinnable tag, port 9090 and the `X-Workshop-Space` header.

## Goals / Non-Goals

**Goals:**
- One build definition whose output is identical for local runs, the Coolify fallback and GitHub Actions service containers, with no per-consumer flags or commands.
- Build once, push the candidate by digest, and add every tag (the commit tag included) only after the candidate has been verified, so later gates (see `acceptance-conformance`) can block tags without rebuilding.
- All mutable state of a running container lives in one directory, so "recreate = fresh data" holds by construction.
- Seeding is safe to run on every start, against databases created by older images, and repeatedly within one process.
- The missing-PDF-library case is handled at one boundary, the PDF service, without masking other rendering errors.
- One shared test harness whose fixtures the later changes reuse by name instead of each building their own.

**Non-Goals:**
- Bit-for-bit reproducible image digests. "Reproducible" here means the same locked dependency set, base image and behavior. Image timestamps and labels may differ between builds.
- A migration framework (Alembic), another database engine, multiple workers or horizontal scaling. Capacity for the shared instance belongs to `workshop-spaces`.
- A `latest` tag, Windows containers or architectures other than amd64 and arm64.
- Image signing, SBOM publication, or automated dependency or base-image update PRs.
- Space isolation, shared mode and admin token (`workshop-spaces`); drift and planted bugs (`drift-coverage`); the conformance gate itself (`acceptance-conformance`); anything in the participant repository.
- Normalizing line endings across the existing code base.
- Cleaning stale references in `docs/user-stories/` (`acceptance-conformance` moves those files to `legacy/`) or removing the unused `visual_baseline_dir` setting (pydantic-settings rejects unknown `WORKSHOP_*` entries in a `.env`, so dropping the field would break existing `.env` files).

## Decisions

### D1. One multi-stage Dockerfile; the environment is installed by uv from the committed lock

The root `Dockerfile` is rewritten. `backend/Dockerfile` and `requirements.txt` are deleted.

- **Base image:** `python:3.12-slim-trixie`, pinned by digest, used for both stages. The explicit Debian codename prevents silent OS jumps like the slim tag's move from bookworm to trixie.
- **Builder stage:** `COPY --from=ghcr.io/astral-sh/uv:<pinned X.Y.Z> /uv /bin/uv`. Environment: `UV_PYTHON_DOWNLOADS=never` (always use the image's CPython), `UV_COMPILE_BYTECODE=1`, `UV_LINK_MODE=copy`, `UV_PROJECT_ENVIRONMENT=/app/.venv`. Copy only `pyproject.toml` and `uv.lock`, then run `uv sync --locked --no-dev` with a BuildKit cache mount. `--locked` makes an outdated lock fail the build with the message above, which names `uv.lock` (spec: *Locked dependency set*). Copying the source after this step keeps the dependency layer cached across code changes.
- **Runtime stage:** install the same apt library set as today (`libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0`), plus `fonts-dejavu-core` so PDF text rendering does not depend on transitive font packages, plus `curl`. Use `--no-install-recommends` and remove the apt lists. Create user uid/gid 1000, copy `/app/.venv` from the builder, copy `backend/` and `tools/` owned by root (read-only for the runtime user), and set `PATH=/app/.venv/bin:$PATH`, `PYTHONUNBUFFERED=1`, `WORKDIR /app`, `USER 1000`, `EXPOSE 9090`.
- uv is not present in the runtime image.

Alternatives considered:
- **pip with a `uv export` requirements file:** two sources of truth that can drift unless an extra check keeps them aligned.
- **pip-tools pins:** no universal multi-platform lock and no dependency groups.
- **Single stage with uv in the final image:** workable, but carries the uv binary and build cache into every pull for no runtime benefit.
- **Alpine or distroless:** WeasyPrint needs glibc Pango and HarfBuzz, and musl wheels are less available.
- **Python 3.11** (as in `backend/Dockerfile`): the root Dockerfile that Coolify uses today is already on 3.12.

### D2. uv project metadata

- `[project.optional-dependencies] dev` moves to `[dependency-groups] dev`. `uv sync` includes the group and `--no-dev` excludes it. `drift-coverage` adds its test dependencies (`pytest-playwright`, `beautifulsoup4`) to this group and introduces `[tool.pytest.ini_options]` (its tasks 1.2 and 7.1); `acceptance-conformance` adds no package — `httpx` is already a runtime dependency and it reuses `pytest-playwright` from this group — and only extends that `[tool.pytest.ini_options]` table with its markers and default deselection (its task 3.1). `workshop-spaces` adds `locust` in a separate `loadtest` group, which neither `uv sync` nor the image installs by default.
- `[project.dependencies]` stays as unpinned names or lower bounds. Exact versions exist only in `uv.lock`. Upgrades are deliberate (`uv lock --upgrade-package <name>`), reviewed as lock diffs.
- `[tool.uv] package = false`, and the unused setuptools `[build-system]` is removed. The shop is an application that always runs from its source root and is never distributed as a wheel. This also fixes the verified flat-layout discovery failure. Rejected alternatives:
  - Configuring `[tool.setuptools.packages.find]`: builds an artifact nobody uses.
  - Passing `--no-install-project` on every command: easy to forget in docs and CI.
- `requires-python = ">=3.12"` and a committed `.python-version` of `3.12`, so development environments use the same minor version as the image and the lock contains no Python 3.11 forks that no build exercises.
- The lock stays universal: `[tool.uv]` has no `environments` key. uv records such a restriction in `uv.lock` as top-level `supported-markers`, so its absence is the check. `resolution-markers` and `required-markers` can appear in a universal lock and are not a failure.
- **uv version:** the exact uv release that produced `uv.lock` is pinned in the Dockerfile and in the workflow (`astral-sh/setup-uv`). `[tool.uv] required-version` sets a minimum for developers. Lock validation across different uv releases is the most likely source of a false "outdated lockfile" failure.
- `pyproject.toml` `version` is informational and is not read at runtime (see D6).

### D3. All mutable state under `/data`; no declared volume

- The image creates `/data` owned by uid 1000 and sets `WORKSHOP_DATABASE_URL=sqlite+aiosqlite:////data/workshop.db` and `WORKSHOP_PDF_OUTPUT_DIR=/data/pdfs`. `pdf_output_dir` is an existing setting, so no new configuration surface is added. Local, non-container defaults stay unchanged (`./workshop.db`, `backend/app/static/pdfs`).
- The Dockerfile does **not** declare `VOLUME /data`. A declared volume becomes an anonymous volume, and `docker compose up` carries anonymous volumes over when it recreates a service. That breaks the *Reset by recreation* scenario, because the database would silently persist. Users who want persistence mount a volume explicitly.
- **Order documents (decided by the maintainer):** inside the image, generated invoice and summary PDFs are written to `/data/pdfs` and served only through `/api/docs/orders/{id}/invoice.pdf` and `/summary.pdf`; `/static/pdfs/` no longer serves them (spec: *Order documents in the container*). Rationale: all mutable state stays in one directory, so recreation resets documents together with the database; the application code stays read-only for the runtime user; and per-order documents stay out of the public static mount, which would expose other participants' invoices by file name once `workshop-spaces` isolates orders. The change is **BREAKING** for clients that fetch order PDFs from `/static/pdfs/`. Consequences:
  - The checkout confirmation page (`backend/app/main.py:314-315`) and the order history returned by `POST /api/auth/login` (`invoice_url`/`summary_url`, `backend/app/api/auth.py:82-83`) link to `/api/docs/orders/{id}/invoice.pdf` and `/summary.pdf`. These keep working, and with D8 they also render a missing summary.
  - `POST /api/checkout/` does not link. Its `documents` field lists server-side file paths built from `pdf_output_dir` (`backend/app/api/checkout.py`, `services/order_service.py`). Locally these stay `backend/app/static/pdfs/invoice_<order_number>.pdf` and `summary_<order_number>.pdf`. Inside the image they become `/data/pdfs/invoice_<order_number>.pdf` and `/data/pdfs/summary_<order_number>.pdf`. The file names are unchanged; the list is empty when rendering is unavailable (D8). These are server paths, not URLs, and this is a visible change to the response. `acceptance-conformance` triages API-006 AC-6 (document paths) against it in its task 14.2.
  - Three documents refer to the old location: `docs/user-stories/checkout-and-orders.md:30` uses the `/static/pdfs/` URL (`acceptance-conformance` supersedes that story set); `docs/test-prompts/checkout-and-auth.md:32` checks files under `backend/app/static/pdfs/` (rewritten by task 8.3); `README.md:84` names `backend/app/static/pdfs/` as the output directory (corrected by the README rewrite, task 8.2).
  - Later changes do not treat `backend/app/static/pdfs` as the PDF location of the image, and they detect stray generated files with a marker-and-`find` check (D11), which also works for gitignored files and for `/data/pdfs`.

Alternative considered: keep writing PDFs into the source tree and `chown` it to uid 1000. Rejected because it makes the application code writable by the runtime user and splits state across two places.

### D4. Seed at container start through a Python entrypoint, with insert-if-missing semantics

**Seed semantics.** `seed_data.main()` becomes safe on every run:
1. `init_db()` runs, then the `ensure_*_columns` helpers always run. They are no-ops on fresh databases (verified above) and are the hook `workshop-spaces` uses for its order `space` column on persisted databases.
2. **Products:** insert missing SKUs and never update existing rows.
3. **Feature flags:** unchanged (already insert-missing). A newer image started on a persisted database gains new flags, for example `BUG_CHECKOUT_TOTAL`, without resetting runtime values.
4. **Users:** insert missing emails. Addresses, payment methods and seeded order history are created only together with a new user and committed as one unit per user. The seeding path must not use the intermediate commit inside `OrderService.create_order`, so a crash cannot leave a half-seeded user that a later start would skip; it builds the order objects with the module-level `build_order` helper (D8), which needs no session and no `PDFService`, so seeding constructs neither an `OrderService` — whose constructor requires a `PDFService` — nor a renderer. Seeding treats `USERS_FIXTURES`, `PRODUCT_FIXTURES` and the flag fixtures as read-only: indexes are read with `.get`, and model arguments are built from a filtered copy (for example `{k: v for k, v in payment_data.items() if k != "billing_address_index"}`). Nothing in seeding calls `pop`, `del` or item assignment on fixture data, so repeated in-process runs (tests, harness fixtures, a retry after a failed seed) produce identical data, including billing-address links.
5. Seeding does not pre-render PDFs. Documents of seeded orders render on first request through `api/docs.py`. This keeps start-up fast and independent of the native PDF libraries. It relies on D8: `api/docs.py` builds both render contexts with the same helper as checkout, and `PDFService` writes atomically.

Consequence for development: `python -m tools.seed_db` no longer refreshes an existing database. To reset, delete `workshop.db`. This follows directly from the spec's "MUST NOT duplicate or overwrite".

**Entrypoint.** A new module `tools/entrypoint.py` is wired as `ENTRYPOINT ["python", "-m", "tools.entrypoint"]`, with the uvicorn command in `CMD`. It:
1. derives the database directory from the configured URL and exits with an actionable message if uid 1000 cannot write it. The message names the directory, the effective database URL, the uid and the fix, so a misconfigured URL can be told apart from bind-mount ownership,
2. runs the seed routine and disposes the engine,
3. calls `os.execvp` on the `CMD` arguments.

uvicorn replaces the entrypoint as PID 1 and receives stop signals directly. Because seeding lives in the entrypoint, an overridden command (for example a Coolify custom start command) still gets seeded. A seed failure exits non-zero before the port opens, so the container never reports healthy with partial data.

Alternatives considered:
- **Build-time seeding (today):** a mounted empty volume starts unseeded, and a database is baked into an image layer.
- **Seeding in the FastAPI lifespan:** couples demo data to every app start, including tests and `--reload` development runs.
- **POSIX shell entrypoint:** with CRLF files already committed and a Windows checkout, a CRLF shebang script fails with an obscure "not found". Python tolerates CRLF and reuses the seed code directly.
- **"Seed only if the products table is empty":** a partially failed seed would never complete, and new fixtures from newer images would never reach persisted databases.

### D5. Runtime process: one uvicorn process on 9090, proxy headers, image health check

- `CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "9090", "--proxy-headers", "--forwarded-allow-ips", "*"]`, with no `--workers` (a single process). Reasons:
  - The feature flag cache is process-local, so several workers would see flag changes inconsistently for up to `feature_flag_cache_seconds`.
  - SQLite has a single writer.
  - `workshop-spaces` removes the cache, but scale-out stays its concern.
- The proxy headers are carried over from `backend/Dockerfile` so absolute URLs (the `home.html` JSON-LD) use the external scheme and host behind Coolify.
- `HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=3 CMD curl -fsS http://127.0.0.1:9090/health || exit 1`. curl stays because Coolify's health checks run curl or wget inside the container. The start period covers seeding. GitHub Actions waits for service containers that define a health check, so participant workflows need no extra `--health-cmd` options.
- Port 9090 is the only port in the image, compose, README and docs.

Alternatives considered:
- **Gunicorn with uvicorn workers:** multiple processes (see above).
- **A Python-based health check without curl:** Coolify expects curl or wget.

### D6. Version from a build argument

- `Settings.app_version: str = "dev"` is read from `WORKSHOP_APP_VERSION`. The shop never derives its version from git, so a source run reports `dev` even on a tagged commit.
- `/health` returns `{"status": "ok", "version": settings.app_version}`. `WorkshopStatus` gains `version`, and `workshop-spaces` later adds `space` beside it. `FastAPI(version=...)` uses the same setting so the OpenAPI `info.version` matches.
- In the Dockerfile, `ARG APP_VERSION=dev` and `ENV WORKSHOP_APP_VERSION=$APP_VERSION` are the **last** instructions of the runtime stage, so images for different tags of the same commit share every cached layer.
- The workflow derives `APP_VERSION`:
  - `refs/tags/workshop-<id>` → `workshop-<id>`
  - `refs/tags/vX.Y.Z` → `X.Y.Z`
  - anything else → `dev`

  `edge` and branch images therefore report `dev`, as the spec requires (*Image without a version tag*), including a `sha-<short>` image of a `main` commit that is deployed as a candidate. The exact commit is identified by the `org.opencontainers.image.revision` label and the image digest. A deployment that must show a real version on `/health` deploys an `X.Y.Z` or `workshop-<id>` tag.
- OCI labels come from `docker/metadata-action` (source, revision, created). `org.opencontainers.image.version` is set explicitly to `APP_VERSION` so label and endpoint agree.

Alternatives considered:
- **Reading the version from `pyproject.toml` or the package metadata:** requires bumping a file per tag, cannot express `workshop-<id>`, and is a second source of truth.
- **A `VERSION` file baked into the image:** equivalent, but the environment variable is the agreed cross-change contract and is trivially overridable for local experiments.

### D7. Workflow `.github/workflows/image.yml`: build once, push by digest, verify, then tag

Triggers: push to `main`; tags matching `v[0-9]+.[0-9]+.[0-9]+` and `workshop-*`; `pull_request`; `workflow_dispatch`. Permissions: `contents: read`, `packages: write`. Every action is pinned by full commit SHA with a version comment. Concurrency is grouped per ref, and only pull requests cancel in-progress runs.

| Trigger | Pushed by `build` | Tags added by `publish` after verification | `APP_VERSION` |
|---|---|---|---|
| push `main` | candidate digest only (untagged) | `sha-<short>`, `edge` | `dev` |
| tag `vX.Y.Z` | candidate digest only (untagged) | `sha-<short>`, `X.Y.Z` | `X.Y.Z` |
| tag `workshop-<id>` | candidate digest only (untagged) | `sha-<short>`, `workshop-<id>` (only after the `acceptance-conformance` gate as well) | `workshop-<id>` |
| `workflow_dispatch` | as a push to that ref | on `main` and tag refs: as a push to that ref; on any other branch: `sha-<short>` only | as resolved for the ref |
| pull request | nothing (amd64 only, loaded locally) | nothing | `dev` |

Tags are computed by `docker/metadata-action`: `type=sha,prefix=sha-,format=short`, `type=semver,pattern={{version}}`, `type=match,pattern=^workshop-.*$,group=0`, `type=edge,branch=main`, with `flavor: latest=false`. The `latest=false` flavor is needed because metadata-action otherwise adds `latest` for semver tags. A `workshop-<id>` that is not a valid Docker tag (`[A-Za-z0-9_.-]`, at most 128 characters in total) fails the workflow early. The computed tags are only job outputs of `build`; `build-push-action` receives the labels but no tags.

**Job graph.** The full target graph, which the later changes extend rather than restate, is:

`check` → `build` → (`smoke` matrix, `test`); `smoke` → `conformance`; (`build`, `smoke`, `test`, `conformance`) → `publish`

`conformance` (`acceptance-conformance`) needs `build` and `smoke`, so a candidate that fails `smoke` never starts its two long conformance legs; `build` is inside the last group because `publish` reads its outputs, which matches `publish.needs` exactly.

`build` exposes three job outputs with fixed names: `digest` (the pushed index digest, `sha256:…`), which every job that needs the image reads; `app_version` (the resolved `APP_VERSION`), which `smoke` passes to the smoke script as the expected version; and `tags` (the computed tag list, one full image reference per line), which `publish` promotes and no other job reads. Jobs that need the image run `ghcr.io/manykarim/demo-webshop@${{ needs.build.outputs.digest }}`. They log in to GHCR read-only, because the package stays private until Migration Plan step 2 and the candidate can only be addressed by digest.

Verifications required before `publish` may tag a candidate:

| Ref | `smoke` (this change) | `test` (`drift-coverage`) | `conformance` (`acceptance-conformance`) |
|---|---|---|---|
| push `main` | required | required | runs, not required |
| tag `vX.Y.Z` | required | required | does not run |
| tag `workshop-<id>` | required | required | required |
| `workflow_dispatch` | required | required | runs; required only on a `workshop-*` tag ref |
| pull request | steps inside `build` | steps inside `build` | does not run |

This change creates `check`, `build`, `smoke` and `publish` with `publish.needs: [build, smoke]` (`build` is listed because `publish` reads its outputs) and an explicit condition from the start: `if: ${{ !cancelled() && github.event_name != 'pull_request' && needs.build.result == 'success' && needs.smoke.result == 'success' }}`. The explicit form is needed once a need can be skipped or can fail without blocking, because the implicit `success()` would then skip `publish`. Each later change adds its job to `publish.needs` and one success condition to that expression. After `drift-coverage` (its task 16.2) and `acceptance-conformance` (its task 6.2), the final job reads:

- `needs: [build, smoke, test, conformance]`
- `if: ${{ !cancelled() && github.event_name != 'pull_request' && needs.build.result == 'success' && needs.smoke.result == 'success' && needs.test.result == 'success' && (needs.conformance.result == 'success' || !startsWith(github.ref, 'refs/tags/workshop-')) }}`

On pull requests nothing is pushed and a `load: true` image exists only inside `build`, so pull-request checks of later changes run as steps inside `build`, after the smoke phases and against the same loaded amd64 container; their separate jobs are skipped on pull requests.

Jobs:
1. **`check`:** `setup-uv` (pinned version), `uv lock --check`, `uv sync --locked`, `uv run pytest backend/tests`. This catches lock drift in seconds and is where the later changes' unit, integration and contract tests run.
2. **`build`** (needs `check`): `tools/resolve_image_version.py` and `docker/metadata-action` compute `APP_VERSION` and the tag list. Outside pull requests: `setup-qemu`, `setup-buildx`, GHCR login with `GITHUB_TOKEN`, `build-push-action` for `linux/amd64,linux/arm64` with `cache-from`/`cache-to: type=gha,mode=max`, the `APP_VERSION` build argument, the metadata labels and `outputs: type=image,name=ghcr.io/manykarim/demo-webshop,push-by-digest=true,name-canonical=true,push=true`. It pushes the candidate by digest without any tag, sets the job outputs `digest`, `app_version` and `tags`, and writes the digest, ref, `APP_VERSION` and the computed tag list to `$GITHUB_STEP_SUMMARY`, so every run leaves a record of which image it built and which tags it computed, including a run whose `publish` is skipped. On pull requests it builds amd64 only with `load: true`, runs `tools/smoke_image.py` against the loaded image, and runs a dry run of the tag mapping for a simulated `workshop-*` ref (a local, never-pushed git tag, `resolve_image_version.py` and metadata-action with `context: git`), which proves the mapping before merge without publishing anything.
3. **`smoke`** (needs `build`, not on pull requests): a matrix on `ubuntu-24.04` and `ubuntu-24.04-arm`. Native arm64 hosted runners are available because the repository is public. The job starts `image@digest` with only `-p 9090:9090`, waits for `healthy`, then runs `tools/smoke_image.py` (stdlib only; takes a base URL, an expected version and a state file that the three phases share, each with a default):
   - home page 200,
   - `/health` returns `ok` and the expected version,
   - demo login, and `invoice.pdf` and `summary.pdf` of every seeded order 200 `application/pdf` (lazy rendering, D8),
   - API add-to-cart with `X-Session-ID`, API checkout, `invoice.pdf` and `summary.pdf` 200 `application/pdf`, and 404 for that order's `/static/pdfs/invoice_<order_number>.pdf`,
   - `docker restart`, then the product count and seeded order numbers are unchanged, and the runtime order and a seeded summary are still served,
   - `docker rm -f` and a new container, then only seeded data is present.

   This covers the *Container start-up contract*, *Version reporting* (`dev` on `main` runs), *Seed on first start* and *Order documents in the container* scenarios on both architectures.
4. **`publish`** (needs `build` and every verification job required for the ref, see the table above; not on pull requests): takes the tag list from `build`'s `tags` output (`sha-<short>` always, plus `edge`, `X.Y.Z` or `workshop-<id>` when present), so the tag names are derived once, and runs one `docker buildx imagetools create` with a `-t` per tag on the verified digest, without rebuilding. Because the list always contains `sha-<short>`, a dispatch on another branch needs no extra condition for an empty human-readable tag. It then runs `docker logout ghcr.io` and an anonymous `docker buildx imagetools inspect` of each created tag that asserts both platforms and that the digest equals the tested one, so a private package fails the run instead of failing on workshop day.

`acceptance-conformance`'s spec requires that no workshop-tagged image exists when its gate fails, which a single `build-push` step with all tags cannot guarantee. With push-by-digest, a candidate that fails `smoke`, `test` or, on a workshop tag, `conformance` carries no tag at all, `sha-<short>` included.

Trade-offs:
- **`sha-<short>` is a moving per-commit pointer**, as the spec states. A `main` build and a tag build of the same commit have different digests because `APP_VERSION` differs, and whichever `publish` finishes last owns `sha-<short>`. The `edge` image can therefore lose its `sha-` tag once a tag build of the same commit is published. The authoritative identifiers are the digest (the `build` job output and step summary) together with the `org.opencontainers.image.revision` label. Deployments, rollbacks and records use `X.Y.Z`, `workshop-<id>` or a digest, never `sha-<short>`.
- **Untagged versions accumulate in GHCR:** every candidate is pushed by digest, and a failed candidate or an image whose `sha-`/`edge` tag moved on stays as an untagged version. Accepted; cleanup is an open question.
- **QEMU builds arm64 in the `build` job.** The trial lock shows no source builds are needed, so emulation only unpacks wheels and apt packages. The build duration is recorded on the pull request (amd64 baseline), on the first `main` run (multi-arch, cold cache) and on the `v0.2.0` run (multi-arch, warm cache). If the warm-cache multi-arch `build` job takes more than 15 minutes, switch `build` to a native per-architecture matrix (push each architecture by digest, then merge the index) without changing tags or the later jobs.

Alternatives considered:
- **One `build-push` step pushing all tags:** simplest, but it publishes unverified tags and leaves no gate point.
- **Pushing `sha-<short>` from `build` before verification:** the commit tag would name unverified or gate-failed candidates, and the later of two runs of one commit would silently re-point it.
- **Version-suffixed commit tags for tag builds (`sha-<short>-<version>`):** breaks the canonical `sha-<short-sha>` tag name of the cross-change contract.
- **A concurrency group per commit to order publishes:** GitHub keeps only one pending run per group, so a `main` run, a `v` tag and a `workshop-` tag of the same commit could cancel one another.
- **Rebuilding per tag after tests:** a second build is not guaranteed to be identical to what was tested.
- **Native arm64 build runners from day one:** more workflow complexity for a build that currently has no compilation.
- **Rehearsing a `workshop-*` tag on the canonical package before the gate exists:** publishes a permanent, public `workshop-*` image that no gate checked. The mapping is proven by unit tests and the pull-request dry run instead, the same promotion mechanism is verified live on `v0.2.0` (task 10.4), and task 10.5 checks the images of the gated workshop tags that `acceptance-conformance` pushes, including the computed tag list and `APP_VERSION` of the blocked rehearsal tag's `build` step summary, which confirms the `type=match` rule on a real `workshop-*` ref without publishing it.

### D8. Lazy PDF rendering with a narrow degradation path, one render context and atomic writes

- `pdf_service.py` no longer imports `weasyprint` at module level. A memoized loader imports it on first use. `ImportError` or `OSError` (missing native libraries surface as `OSError` from cffi) marks rendering unavailable and logs the reason once.
- `PDFService.render_pdf` raises a dedicated `PDFRenderingUnavailable` error in that state.
- `PDFService._render_pdf_sync` renders into a unique hidden temporary file in the output directory (`.<output_name>.<uuid>.tmp`) and moves it onto the target with `os.replace`; on any error it removes the temporary file and re-raises. A file that exists is always complete, for eager and lazy rendering alike. With one uvicorn process (D5), no lock is needed: two concurrent first renders of the same document produce identical output and replace one another atomically.
- **One order builder.** A module-level `build_order(...)` in `services/order_service.py` returns an unsaved `Order` with its items from the customer details and the cart state, without a session, a commit or a `PDFService`. `OrderService.create_order` uses it and keeps its commit-then-render flow; seeding uses it directly (D4), which is how it drops `PDFService` without changing `OrderService.__init__`.
- **One render context.** A module-level `build_document_context(order)` in `services/order_service.py` builds the context for both templates from a persisted `Order` with its `items` loaded: `order` (`order_number`, `order_date`, `subtotal`, `tax`, `total`, `status`), `customer` (`name`, `email`, `address`) and `items` (`product_id`, `name`, `quantity`, `unit_price`, `total_price`, and `image_url` as an empty string, which keeps today's empty `src` in `order_summary.html`). `OrderService.generate_documents` and both branches of `api/docs.py` use it, and the hand-built dicts in `api/docs.py` are deleted. Invoice and summary contexts can no longer drift apart, and a document rendered on demand is identical to the one rendered at checkout.
- `OrderService.create_order` catches **only** `PDFRenderingUnavailable` from document generation and returns an empty document list. The order is already committed and the confirmation renders as usual. Any other rendering exception propagates as today, so real PDF defects are not hidden.
- The seeding path skips document rendering entirely (D4).
- `api/docs.py` looks up the order first (404 stays 404), then answers `503` with `{"detail": "PDF rendering is unavailable in this environment"}` when rendering is unavailable, even if a stale file exists. Otherwise it returns the existing file or renders the missing one with the shared context.
- The existing unit tests become importable without Pango. New tests simulate the unavailable loader for the checkout and 503 scenarios, and a fake `weasyprint` that records the HTML covers on-demand rendering of both documents without native libraries.
- `weasyprint` stays a regular runtime dependency. Its Python package installs everywhere, and only the native libraries are missing on typical developer machines.

Alternatives considered:
- **Keep the eager import and document a Pango install for macOS and Windows:** heavy setup for a feature most development tasks do not touch.
- **A pure-Python fallback renderer:** two renderers produce different documents, which is poison for PDF assertions.
- **An optional extra for PDF support:** does not remove the need for graceful behavior and complicates the lock.
- **Keep pre-rendering PDFs during seeding:** hides the broken summary branch instead of fixing it, makes start-up depend on the native libraries and slows every container start.
- **A per-path `asyncio.Lock` in `api/docs.py`:** avoids a duplicate render but not a half-written file seen by another reader; the atomic replace covers both cases.

### D9. Build context hygiene

- `.dockerignore` excludes `.git`, `.github/`, `.venv`, `**/.env`, `**/*.db`, `openspec/`, `docs/`, `backend/tests/`, `.claude/`, `**/__pycache__` and `backend/app/static/pdfs/{invoice,summary}_ORD-*.pdf`. Patterns are matched from the root of the build context, so the `.env` and database patterns use `**/` to cover nested copies.
- The builder copies only `pyproject.toml` and `uv.lock`, and the runtime stage copies only `backend/` and `tools/`, so a root `.env` or `workshop.db` never reaches an image layer; that COPY list is what keeps them out today. `.dockerignore` still matters in three ways:
  - it keeps the build context small (no `.git`, `.venv`, `docs/`, `openspec/`) and keeps local secrets and databases out of the context sent to the builder, which may be remote or a CI cache;
  - within the copied trees, it keeps `backend/tests/`, `**/__pycache__`, generated order PDFs and nested files such as `backend/.env` or `backend/workshop.db` (created when the app is run from that directory) out of the image. pydantic-settings reading from `/app` would not load a nested `.env`, but its secrets would still sit in an image layer;
  - it guards against a future broad `COPY . .`.
- Rule for later changes: a change that adds a root directory which the image does not copy extends `.dockerignore` with it in the same task that creates the directory, and verifies it with the context probe of task 6.3. `workshop-spaces` adds `loadtest/`; `acceptance-conformance` adds `conformance-report/` and `test-results/`. `.github/`, created by this change, is excluded for the same reason.
- The 36 generated order PDFs are removed from version control, and `.gitignore` gains patterns for them and `workshop.db`. The `example_*.pdf` files produced by `tools/generate_example_pdfs.py` stay.

### D10. Development compose file and documentation

- `compose.yaml` defines one service built from the repository (`build: .`, `APP_VERSION` build argument defaulting to `dev`), port `9090:9090`, an optional `.env` (`env_file` with `required: false`) and no volume. The health check comes from the image. Pulling a published image is the participant repository's job, not this compose file's.
- The service also sets `environment:` with `WORKSHOP_DATABASE_URL: sqlite+aiosqlite:////data/workshop.db` and `WORKSHOP_PDF_OUTPUT_DIR: /data/pdfs`, repeating the image values on purpose. In Compose, `environment` takes precedence over `env_file`. A developer's `.env` is meant for AI and CORS settings and may hold paths for source runs (for example `./workshop.db`, which resolves to the root-owned `/app` in the container and makes the entrypoint exit). The image decides where state lives, so any `.env`, including one copied before this change, cannot move state out of `/data`.
- `.env.example`: CORS origins move from port 8000 to 9090. `WORKSHOP_DATABASE_URL` is commented out with a note that it applies to source runs only, where `./workshop.db` is already the code default, and that the image and compose always use `/data/workshop.db`. Local `uv run` behavior does not change. `WORKSHOP_FEATURE_FLAG_CACHE_SECONDS` is left for `workshop-spaces` to remove.
- `README.md` is rewritten:
  - remove references to `tests/robot`, `tools/mcp_generate.py`, robotframework-selfhealing-agents, doctestlibrary, robotframework-aiagent and `rfbrowser init`,
  - document the uv development workflow (`uv sync`, `uv run python -m tools.seed_db`, `uv run uvicorn ... --port 9090`, `uv run pytest`),
  - document image usage (`docker run -p 9090:9090 ghcr.io/manykarim/demo-webshop:<tag>`), compose (`.env` configures AI and CORS settings; database and PDF locations are fixed to `/data` in the container), the version check via `/health` (`edge` and other images built from a branch report `dev`), and the tag scheme (`sha-<short-sha>` as a moving per-commit pointer; pin `X.Y.Z`, `workshop-<id>` or a digest),
  - document PDFs: generated files land in `WORKSHOP_PDF_OUTPUT_DIR` (`backend/app/static/pdfs` for local runs, `/data/pdfs` in the image, which is what the checkout `documents` field reports, or `[]` when rendering is unavailable), and are downloaded through `/api/docs/orders/{id}/invoice.pdf` and `/summary.pdf`, not `/static/pdfs/`,
  - add a breaking-change note for former `pip install -r requirements.txt` users (`uv export --no-dev --format requirements-txt` on demand),
  - link `docs/WORKSHOP-FEATURES.md`.
- `docs/test-prompts/checkout-and-auth.md` asserts PDFs through the document endpoints. Stale Robot Framework and tooling references in `docs/user-stories/` (`ai-and-operations.md`, `checkout-and-orders.md`) stay for `acceptance-conformance`, which moves those files to `legacy/`; the pull request description records this hand-off.

### D11. One shared test harness

- `backend/tests/harness.py` is a plain module with no fixtures and no top-level import from `backend.app`. Its context manager `isolated_app(tmp_dir, *, seed_users=False)` imports the app inside the function, patches `settings.database_url` to a SQLite file in `tmp_dir` and `settings.pdf_output_dir` to `tmp_dir/pdfs`, and resets the `async_engine` and `async_session_factory` globals of `backend/app/core/db.py` (through `pytest.MonkeyPatch.context()`). It clears the process-local flag cache (`_cache` in `backend/app/core/feature_flags.py`, while that module has one) on enter and on exit, because the cache outlives a test's database and would otherwise hand one test's flag values to the next. It runs `init_db()` and the seeders in one `asyncio.run` (catalog and flags, or all of `seed_data.main()` when `seed_users=True`: products, flags, demo users with addresses, payment methods and order history), disposes the engine, yields a `TestClient` entered as a context manager, and on exit clears `app.dependency_overrides` and restores every patched value. It is scope-agnostic, so function-, package- and session-scoped fixtures can use it.
- `harness.py` also declares the process-wide test environment: `SCRUBBED_ENV_VARS` (this change: `WORKSHOP_APP_VERSION`), `SCRUBBED_ENV_PREFIXES` (this change: `WORKSHOP_FLAG_`) and `PINNED_ENV_VARS` (this change: empty), applied by `pin_test_environment(environ, tmp_dir)`, which removes the scrubbed variables, sets the pinned ones and points `WORKSHOP_DATABASE_URL` and `WORKSHOP_PDF_OUTPUT_DIR` into `tmp_dir`. A later change whose setting must be neutral in every test, before any app import, adds entries to these declarations instead of writing environment code in a conftest.
- The root `backend/tests/conftest.py` is loaded before any test under `backend/tests` is collected. At module top, before any app import, it calls `pin_test_environment(os.environ, <tempfile.mkdtemp() directory>)`, so a test that imports the app outside the harness never touches `./workshop.db` or `backend/app/static/pdfs`, and `pytest_unconfigure` removes that directory. It imports the app only inside fixture bodies, so live test runs of later changes do not import it at collection. It provides the canonical function-scoped fixtures:
  - `temp_database`: patched settings and engine globals on a temporary SQLite file, no client and no seeding; yields the database file path (`pathlib.Path`);
  - `app_client`: `isolated_app(tmp_path)`, products and flags seeded, no users;
  - `seeded_app_client`: `isolated_app(tmp_path, seed_users=True)`, full seeding including the demo users `jamie@flowlinesupply.com` and `alex.productlead@example.com` with their order history;
  - `pdf_unavailable`: the PDF loader reports rendering as unavailable;
  - `fake_weasyprint`: a fake `weasyprint` module that writes `%PDF-` bytes; yields the list of rendered HTML strings in render order.
- **Rules for later changes.** `workshop-spaces`, `drift-coverage` and `acceptance-conformance` reuse these fixtures and `isolated_app` by their exact names. They never define a fixture with one of these names, never create a second root-level conftest, and never reset the engine globals or set environment variables of the pytest process before the app is imported in their own code; the only way they change the root harness is by adding entries to the environment declarations in `harness.py`. Suite-specific fixtures and helpers go only in conftest files of their own test subdirectories (for example `backend/tests/contract/`, `backend/tests/browser/`, `backend/tests/conformance/`). A package- or session-scoped fixture that needs its own database builds on `isolated_app` with `tmp_path_factory`. Passing explicit environment variables to a subprocess (for example a uvicorn server or a fresh interpreter started by a test) is not affected by this rule.
- Generated `workshop.db` and `*_ORD-*.pdf` files are git-ignored (D9), so plain `git status` cannot show a test that writes into the repository. Isolation is checked with a marker file and `find`: `touch "$marker"` before the run, then `find . \( -path ./.venv -o -path ./.git \) -prune -o \( -name '*.db' -o -name '*_ORD-*.pdf' \) -newer "$marker" -print` prints nothing. The same check works for `/data/pdfs` in a container and is the one the later changes use.

Alternatives considered:
- **A separate harness per suite (own engine reset or environment setup):** two harnesses patching the same globals in one `pytest` process interfere, and fixtures with the same name but different seeding shadow each other.
- **Environment variables set before the app is imported, in suite conftests:** `settings` and the engine globals exist once per process and pytest's collection order decides which suite imports the app first, so a second setup in the same run would silently share or override them. The root conftest is the only place that sets the environment, driven by the declarations in `harness.py`.

## Risks / Trade-offs

- [QEMU arm64 build is slow] → The trial lock shows wheels for every compiled package on aarch64, so nothing compiles. GHA layer cache (`mode=max`) plus the dependency layer being keyed only on `pyproject.toml` and `uv.lock` keeps rebuilds short. Build durations are recorded (D7). If the warm-cache multi-arch `build` job, first measured on the `v0.2.0` run, exceeds 15 minutes, switch to the native per-architecture matrix. arm64 is already smoke-tested natively.
- [The GHCR package is private by default after the first push] → A one-time manual visibility change (Migration Plan). The anonymous-inspect step in `publish` fails loudly until it is done. Re-run the failed job afterwards.
- [Seeding is not idempotent today (verified)] → Insert-if-missing semantics with one commit per user and read-only fixtures (D4). Tests run the seed twice and assert unchanged product, flag, user and order counts, unchanged seeded order numbers, survival of a runtime order, unchanged fixtures, and correct billing-address links after a retry and after two fresh databases in one process. The restart phase of `smoke` checks the same in the image.
- [`ALTER TABLE` helpers misbehave on a fresh database] → Verified no-ops, because the models declare all added columns. The seed test starts from an empty SQLite file.
- [WeasyPrint or Pango behaves differently on arm64] → Same Debian packages on both architectures. `smoke` renders runtime and seeded invoices and summaries on a native arm64 runner for every push.
- [Lockfile platform markers leave a platform without wheels, or uv version skew rewrites the lock] → The lock is universal (no `environments` restriction, so no `supported-markers` in `uv.lock`). `check` runs `uv lock --check` with the pinned uv. `required-version` stops older local uv releases. The Dockerfile uses the same pinned uv.
- [Bind-mounted `/data` owned by root makes the database unwritable for uid 1000] → The entrypoint checks writability and prints the fix (`chown 1000` or `--user`) together with the effective database URL. Named volumes inherit the image directory's ownership. The README documents both.
- [A developer's `.env` redirects the database out of `/data` under compose] → `compose.yaml` pins both storage paths in `environment:` (D10), and `.env.example` no longer sets the database URL.
- [Container restart keeps data, only recreation resets] → Intended by the spec (*Restart with existing data*, *Reset by recreation*). The README states it explicitly. Coolify is configured without persistent storage.
- [The base image or apt packages change underneath a tag] → The base image is pinned by digest. Published version tags are immutable artifacts. Rebuilding an old commit may pick up newer apt package revisions, which is accepted and covered by `smoke`.
- [`sha-<short>` points to a different image than a record expects] → By design it names the most recently published build of a commit (spec, D7). Records, deployments and rollbacks use the digest, `X.Y.Z` or `workshop-<id>`; tasks compare digests with the `build` job output.
- [A single uvicorn process limits throughput on the shared fallback] → Required for flag consistency and SQLite (D5). Load testing and scale-out are owned by `workshop-spaces`.
- [`WORKSHOP_APP_VERSION` can be overridden at run time and misreport the version] → Accepted. Deployments must not set it (runbook). The OCI labels and the image digest remain authoritative.
- [Removing `requirements.txt` breaks pip-based installs] → Documented as BREAKING in the proposal and README, with the `uv export` escape hatch.
- [Documents of seeded orders are rendered lazily, so the first invoice or summary request for a seeded order is slower, and the summary branch of `api/docs.py` is broken today] → The slower first request is acceptable (hundreds of milliseconds per document). The broken summary context is fixed by the shared `build_document_context` helper, half-written files are prevented by the atomic replace (D8), and integration tests plus the `fresh` and `restarted` smoke phases fetch seeded invoices and summaries on both architectures. Runtime checkout still renders eagerly as today.

## Migration Plan

1. Merge the change into `main`. The workflow runs `check`, `build`, `smoke` and `publish`; `build` pushes the candidate by digest and `publish` adds `sha-<short>` and `edge`. The first `publish` run fails at the anonymous-inspect step because the new package is private.
2. **One-time:** set the package `ghcr.io/manykarim/demo-webshop` to public in the GitHub package settings and confirm it is linked to the repository through the source label. Re-run the failed `publish` job. Manually verify from a machine without credentials: `docker logout ghcr.io`, then `docker pull ghcr.io/manykarim/demo-webshop:edge` on amd64 and on Apple Silicon, `docker run -p 9090:9090 ...`, `curl localhost:9090/health`.
3. Switch the Coolify application from building the repository to the Docker image `ghcr.io/manykarim/demo-webshop:edge`:
   - port 9090, health check path `/health`,
   - no persistent storage (remove any existing volume so the first start seeds fresh),
   - no `WORKSHOP_APP_VERSION` override.

   Verify `/health` (`version: dev`) and that the running digest matches the `edge` digest.
4. Push git tag `v0.2.0`. Verify the image `0.2.0` exists for both architectures, has the digest the run's `build` job reported, and reports `"version": "0.2.0"`. Switch Coolify to `0.2.0`.
5. Downstream: the participant repository will pin a tag. `workshop-spaces` and `drift-coverage` build on this image; `drift-coverage` adds the `test` job and `acceptance-conformance` the `conformance` job to `publish.needs` (D7). `workshop-<id>` tags are cut only after `acceptance-conformance` adds its gate, and no rehearsal image is ever published under a `workshop-*` name.
6. **Workshop-tag image checks (task 10.5).** When `acceptance-conformance` pushes its blocked rehearsal tag (its task 18.1) and its first real `workshop-<id>` (its task 18.3), this change checks the image level of those runs: the blocked candidate digest carries no tag; the promoted digest equals the run's `build` output, `sha-<short>` resolves to it right after the run, the revision label names the tagged commit, and an anonymous pull on Apple Silicon selects arm64 and reports the workshop version. `acceptance-conformance` checks only the gate behavior and refers to task 10.5.
7. **Archive** this change with `openspec archive reproducible-image` after task 10.5. No other change modifies the `workshop-image` capability, so keeping this change active until then blocks nothing.

**Rollback:**
- **Deployment:** redeploy the previous version tag (`X.Y.Z` or `workshop-<id>`) or a recorded digest in Coolify, or revert the pinned tag in consumers. Never roll back by `sha-<short>`, which can move. Version tags are never deleted, so every earlier version stays pullable.
- **Workflow or Dockerfile:** revert the merge commit on `main`, and Coolify keeps running the last good tag. Before step 3 has happened, Coolify still builds from the repository and is unaffected by the new workflow.
- **Faulty image:** a bad `X.Y.Z` or `workshop-<id>` is superseded by a new tag, not deleted.

## Open Questions

- **Tag mutability for `workshop-<id>`:** when a fix is needed shortly before a workshop, is the git tag re-pushed (the workflow rebuilds and re-promotes the same name) or is a new id cut? Either works with D7. This is a release-process decision.
- **Git revision on `/health`:** should `/health` also report the git revision (additive field) to tell `edge` builds apart without inspecting labels?
- **Update automation:** should Dependabot or Renovate propose updates for the base image digest, pinned action SHAs and `uv.lock`, and on what cadence?
- **Provenance attestations:** keep buildx's default attestations? They add an `unknown/unknown` entry to the index in the GHCR UI. Pulls are unaffected.
- **Untagged candidate cleanup:** should a scheduled job delete untagged GHCR versions older than some age? Any cleanup must never delete a digest that a record (for example `CONFORMANCE.md`) or a deployment pins.
