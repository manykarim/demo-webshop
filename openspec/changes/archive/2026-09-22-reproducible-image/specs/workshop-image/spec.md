## Purpose

Defines how the shop is built, versioned, distributed and started as a container, so that local runs, the hosted fallback and CI all run the identical, identifiable application.

## ADDED Requirements

### Requirement: Locked dependency set
The shop's runtime dependencies SHALL be resolved exclusively from a lockfile committed to the repository. An image build MUST fail when the lockfile does not match the declared project dependencies.

#### Scenario: Build with a current lockfile
- **WHEN** an image is built from a commit whose lockfile matches the declared dependencies
- **THEN** the build succeeds and installs exactly the locked versions

#### Scenario: Build with an outdated lockfile
- **WHEN** a declared dependency is changed without updating the lockfile
- **THEN** the image build fails with an error that names the lockfile as out of date

### Requirement: Published multi-architecture image
The shop SHALL be published as a public container image at `ghcr.io/manykarim/demo-webshop` for both `linux/amd64` and `linux/arm64`. A candidate image MUST receive tags only after it has passed every verification the publishing workflow requires for its ref, and the tags MUST be added to that verified digest without rebuilding; a candidate that fails a required verification MUST NOT carry any tag. Every published image MUST be tagged `sha-<short-sha>` for the commit it was built from and MUST carry the `org.opencontainers.image.revision` label with the full commit SHA. When a commit is published more than once (for example from the default branch and from a version or workshop tag), `sha-<short-sha>` names the most recently published image of that commit; a specific image is identified by its digest, `X.Y.Z` or `workshop-<id>`. Images built from a version tag `vX.Y.Z` MUST also carry `X.Y.Z`; images built from a workshop tag `workshop-<id>` MUST also carry `workshop-<id>`. Images built from the default branch MUST carry `edge`.

#### Scenario: Anonymous pull on Apple Silicon
- **WHEN** a user without registry credentials pulls a workshop tag on an arm64 machine
- **THEN** the pull succeeds and the arm64 variant is selected

#### Scenario: Workshop tag publishing
- **WHEN** the git tag `workshop-2026-10` is pushed and every required verification of the candidate image passes
- **THEN** an image tagged `workshop-2026-10` is available for both architectures, its revision label names the tagged commit, and at the time of publishing `sha-<short-sha>` of that commit points to the same digest

#### Scenario: Failed verification publishes no workshop tag
- **WHEN** the git tag `workshop-2026-10` is pushed and a required verification of the candidate image fails
- **THEN** that run publishes no `workshop-2026-10` tag and the candidate digest carries no tag

### Requirement: Container start-up contract
The container SHALL serve the shop over HTTP on port 9090 without additional arguments. It MUST expose a container health check that reports healthy only when the health endpoint answers successfully.

#### Scenario: Default start
- **WHEN** the image is started with only a port mapping for 9090
- **THEN** the home page and `/health` are reachable on that port and the container reports healthy

### Requirement: Seed on first start
When the container starts with an empty data store, the shop SHALL seed products, demo users with their order history, and default feature flags before accepting requests. When the data store already contains seeded data, start-up MUST NOT duplicate or overwrite it.

#### Scenario: Fresh container
- **WHEN** a new container is created without a persisted data store
- **THEN** the product catalogue and demo users are available on the first request

#### Scenario: Restart with existing data
- **WHEN** a container that already holds seeded data and runtime orders is restarted
- **THEN** the product catalogue is not duplicated and runtime orders are still present

#### Scenario: Reset by recreation
- **WHEN** a container without a persisted data store is removed and created again from the same image
- **THEN** only seeded data is present

### Requirement: Version reporting
The running shop SHALL report its version on `GET /health` and `GET /api/workshop/status` as a `version` field. The version MUST equal the image version tag (`X.Y.Z` or `workshop-<id>`) the image was built for, or `dev` for builds without such a tag. Runs from source report `dev` unless the version is supplied through configuration; the shop never derives its version from git.

#### Scenario: Setup check reads the version
- **WHEN** a client requests `/health` from a container started from `workshop-2026-10`
- **THEN** the response has status 200 and contains `"status": "ok"` and `"version": "workshop-2026-10"`

#### Scenario: Local development run
- **WHEN** the shop is started from a source checkout with `WORKSHOP_APP_VERSION` unset, whether or not the checked-out commit carries a version or workshop tag
- **THEN** `/health` reports `"version": "dev"`

#### Scenario: Image without a version tag
- **WHEN** a client requests `/health` from a container started from `edge`, or from a `sha-<short-sha>` image that was built from a branch rather than from a version or workshop tag
- **THEN** the response reports `"version": "dev"`, and the image is identified by its digest and its `org.opencontainers.image.revision` label

### Requirement: Order documents in the container
Inside the container, generated invoice and summary PDFs SHALL be stored with the container's other mutable state under `/data` and SHALL be served only through `/api/docs/orders/{id}/invoice.pdf` and `/api/docs/orders/{id}/summary.pdf`, which render a missing document on request. The static file mount MUST NOT serve generated order documents.

#### Scenario: PDFs inside the container
- **WHEN** a client requests the invoice or summary PDF of a seeded order or of an order created at run time from the published image
- **THEN** the response is HTTP 200 with content type `application/pdf`

#### Scenario: No static URL for order documents
- **WHEN** a shopper completes checkout in a container started from the published image and a client requests `/static/pdfs/invoice_<order_number>.pdf` for that order
- **THEN** the response is HTTP 404, while the same order's `/api/docs/orders/{id}/invoice.pdf` returns HTTP 200 with content type `application/pdf`

### Requirement: Graceful PDF degradation
When the native libraries required for PDF rendering are unavailable, the shop SHALL start and serve all non-PDF functionality. Checkout MUST still create orders. PDF document endpoints MUST respond with HTTP 503 and a message stating that PDF rendering is unavailable in this environment.

#### Scenario: Checkout without PDF libraries
- **WHEN** the shop runs without PDF rendering libraries and a shopper completes checkout
- **THEN** the order is created and confirmed

#### Scenario: Invoice request without PDF libraries
- **WHEN** a client requests an order's invoice PDF in that environment
- **THEN** the response is HTTP 503 with a message that PDF rendering is unavailable
