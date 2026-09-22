# Two-stage build of the workshop shop (design D1, D3, D5, D6).
#
# The builder resolves the environment with uv from the committed uv.lock and
# nothing else; the runtime stage carries the resulting virtual environment, the
# application source and the native libraries WeasyPrint needs - but no uv, no
# build cache and no baked database.
#
# Both stages pin the same base image by digest: the explicit Debian codename
# keeps a slim-tag move (bookworm to trixie) from silently changing the OS, and
# the digest keeps two builds of the same commit on the same bits.

# ---------------------------------------------------------------------------
# Builder: create /app/.venv from pyproject.toml + uv.lock
# ---------------------------------------------------------------------------
FROM python:3.12-slim-trixie@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS builder

# The uv release that produced uv.lock; the same release is pinned in
# .github/workflows/image.yml and as [tool.uv] required-version.
COPY --from=ghcr.io/astral-sh/uv:0.8.15 /uv /bin/uv

ENV UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /src

# Only the dependency declaration, so this layer is rebuilt for a lock change
# and reused for every source change.
COPY pyproject.toml uv.lock ./

# --locked fails the build when uv.lock no longer matches pyproject.toml
# (spec: Locked dependency set); --no-dev leaves the test tooling out.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# ---------------------------------------------------------------------------
# Runtime: the environment, the source, and what WeasyPrint loads at run time
# ---------------------------------------------------------------------------
FROM python:3.12-slim-trixie@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS runtime

# Pango and HarfBuzz are loaded by WeasyPrint at run time, fonts-dejavu-core
# keeps text rendering off transitive font packages, and curl is what the image
# health check and Coolify's own checks run inside the container.
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        libharfbuzz-subset0 \
        fonts-dejavu-core \
        curl \
    && rm -rf /var/lib/apt/lists/*

# The runtime user. /data holds every mutable file (database and generated order
# documents) and is the only path this user may write; it is deliberately not
# declared as a VOLUME, so recreating a container resets the demo data.
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid 1000 --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data \
    && chown 1000:1000 /data

COPY --from=builder /app/.venv /app/.venv

# Application code stays owned by root: the runtime user reads it, never writes it.
COPY backend /app/backend
COPY tools /app/tools

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    WORKSHOP_DATABASE_URL=sqlite+aiosqlite:////data/workshop.db \
    WORKSHOP_PDF_OUTPUT_DIR=/data/pdfs

WORKDIR /app
USER 1000
EXPOSE 9090

# The start period covers seeding, which the entrypoint runs before the port opens.
HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=3 \
    CMD curl -fsS http://127.0.0.1:9090/health || exit 1

# The entrypoint prepares /data, seeds, and execs the command below, which then
# becomes PID 1 and receives the stop signals directly. One uvicorn process: the
# feature flag cache is process-local and SQLite has a single writer.
ENTRYPOINT ["python", "-m", "tools.entrypoint"]
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "9090", "--proxy-headers", "--forwarded-allow-ips", "*"]

# Last, so images built for different tags of one commit share every other layer.
ARG APP_VERSION=dev
ENV WORKSHOP_APP_VERSION=$APP_VERSION
