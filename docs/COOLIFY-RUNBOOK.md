# Coolify runbook: the shared workshop instance

How the shared demo-webshop is deployed, verified, load-tested, reset and rolled
back on Coolify. It runs the **published image**, never a build from this
repository, in shared mode, where every participant works in their own workshop
space (`docs/WORKSHOP-FEATURES.md`, section *Workshop spaces*).

Placeholders used below: `<coolify-host>` is the public hostname of the
deployment, `<digest>` an image digest (`sha256:…`), `<id>` the workshop id in a
`workshop-<id>` tag, `<handle>` a participant's GitHub handle and `<token>` the
value of `WORKSHOP_ADMIN_TOKEN`. Every command assumes:

```bash
HOST=https://<coolify-host>
```

## 1. Application setup

Create the application in Coolify as **Docker Image** (not "Public Repository",
not a build pack): Coolify must never build this project.

- Image repository: `ghcr.io/manykarim/demo-webshop`
- Exposed port: `9090`
- Health check: HTTP `GET /health`, expected status 200. The body is
  `{"status":"ok","version":"<version>"}`; the container is healthy in roughly
  10 s.
- Start command: none. The image's entrypoint creates `/data`, seeds the store
  and starts one uvicorn process.

### Which image reference to deploy

| Situation | Reference |
|---|---|
| Candidate (validation, load test) | `ghcr.io/manykarim/demo-webshop@<digest>` |
| The workshop itself | `ghcr.io/manykarim/demo-webshop:workshop-<id>` |
| Rollback | a `X.Y.Z` or `workshop-<id>` tag, or a digest recorded in section 8 |

A **candidate digest** is the `digest` output of the `build` job, shown in the
step summary of that commit's `main` run of `image.yml`, and it may only be
deployed once the same run's `publish` job has succeeded: `build` pushes the
candidate untagged, `publish` tags it after every verification passed.

Never deploy `edge` or `sha-<short>`. `edge` moves with every push to `main`,
and `sha-<short>` is re-pointed by a later build of the same commit, so a
redeploy or a rollback would silently pull a different build than the one that
was tested and recorded.

## 2. Environment

Set exactly these three variables (Coolify → the application → *Environment
Variables*, runtime, not build-time):

| Variable | Value |
|---|---|
| `WORKSHOP_SHARED_MODE` | `true` |
| `WORKSHOP_ADMIN_TOKEN` | a secret, generated with `openssl rand -hex 32` |
| `WORKSHOP_AI_PROVIDER` | `mock` |

Mark `WORKSHOP_ADMIN_TOKEN` as a secret so Coolify masks it in the UI, and keep
it with the facilitators. Shared mode without a non-empty token refuses to
start: the deployment fails with a log line naming `WORKSHOP_ADMIN_TOKEN`. That
is a configuration error, not a crash to investigate.

### Never set these

- **`WORKSHOP_DATABASE_URL`, `WORKSHOP_PDF_OUTPUT_DIR`** — the image defaults
  `/data/workshop.db` and `/data/pdfs` are the only locations the container's
  uid 1000 can write, and they are outside the `/static` mount. A value copied
  from `.env.example`, such as `./workshop.db`, resolves inside the root-owned
  `/app` and the entrypoint refuses to start; a PDF directory below
  `backend/app/static` would publish every order PDF through `/static`, to every
  space.
- **`WORKSHOP_FLAG_*`** — an environment override freezes that flag for *every*
  space, so participants could no longer switch stages or bugs in their own
  space.
- **`WORKSHOP_APP_VERSION`** — the version is baked into the image at build
  time. Overriding it makes `/health` report something other than the build that
  is running, which is exactly what the deploy check relies on.
- **`WEB_CONCURRENCY`, `--workers`, a custom start command** — the instance runs
  as a single process. The SQLite store, the connection-pool tuning and the
  load-test evidence all assume one process.

## 3. Storage

No persistent volume, no bind mount, nothing mounted on `/data`. A redeploy is
therefore a **full reset**: a fresh `/data`, a freshly seeded catalogue and demo
users, and every participant space gone.

The rehearsal (section 9) checks that the Coolify action actually recreates the
container: an order created before the redeploy must answer 404 afterwards.

## 4. The `default` space rule

**Never change the `default` space on the shared instance.** Participants'
spaces are unaffected by it — a space that never set a flag reads the clean
baseline, not `default` — but `default` is what every participant, agent or
browser context that forgot its space sees.

- Facilitator demos run in a facilitator space:
  `$HOST/?space=<facilitator-handle>`, or with the header
  `X-Workshop-Space: <facilitator-handle>`.
- The token is used only for the rehearsal's 401 checks and to restore `default`
  with a reset if it was changed by mistake. It is never handed to participants.

## 5. Procedures

### 5.1 Deploy and verify

1. Set the image reference (section 1) and deploy.
2. Wait for the health check to turn green, then verify:

```bash
curl -s $HOST/health
```

- for a `X.Y.Z` or `workshop-<id>` deployment, `version` equals the deployed
  tag;
- for a candidate deployed by digest, the answer is
  `{"status":"ok","version":"dev"}` — an image without a version tag reports
  `dev`, so the build is identified by its digest and its revision label
  instead:

```bash
# what is really running: Coolify's application page shows the pulled
# reference, and on the host
docker ps --format '{{.ID}} {{.Image}}' | grep demo-webshop
docker image inspect --format \
  '{{index .RepoDigests 0}} {{index .Config.Labels "org.opencontainers.image.revision"}}' \
  "$(docker inspect --format '{{.Image}}' <container id>)"

# the commit the candidate was built from, without pulling anything
docker buildx imagetools inspect --format '{{json .Image}}' \
  ghcr.io/manykarim/demo-webshop@<digest> \
  | jq -r '[.. | objects | select(has("Labels"))
            | .Labels["org.opencontainers.image.revision"] // empty] | unique | .[]'
```

The candidate is a multi-platform index (`linux/amd64`, `linux/arm64`), so
`{{json .Image}}` prints one image config per platform; the jq filter above
collects the revision label of all of them and must print the candidate commit
once.

The running digest must equal the recorded `build` digest, and the
`org.opencontainers.image.revision` label must equal the candidate commit.

3. Check the environment in Coolify: `WORKSHOP_SHARED_MODE`,
   `WORKSHOP_ADMIN_TOKEN` and `WORKSHOP_AI_PROVIDER` are set, and neither
   `WORKSHOP_DATABASE_URL` nor `WORKSHOP_PDF_OUTPUT_DIR` appears anywhere in the
   variable list.

4. Shared-mode guard — a write to `default` is refused, the same write in a
   space works:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST $HOST/api/workshop/preset \
  -H 'Content-Type: application/json' -d '{"preset": "stage2"}'          # 401

curl -s -o /dev/null -w '%{http_code}\n' -X POST $HOST/api/workshop/preset \
  -H 'X-Workshop-Space: smoke-a' -H 'Content-Type: application/json' \
  -d '{"preset": "stage2"}'                                             # 200
```

The 401 carries `WWW-Authenticate: Bearer` and a body naming `?space=` and
`X-Workshop-Space`.

5. Indicator — a test space shows its own id, a page without a space shows the
   shared baseline with the hint:

```bash
curl -s "$HOST/?space=smoke-a" | grep -o 'data-workshop-space="[^"]*"'   # smoke-a
curl -s "$HOST/" | grep -o 'data-workshop-space="[^"]*"'                 # default
curl -s "$HOST/" | grep -c 'workshop-space-hint'                         # 1
```

6. Baseline is untouched — status without a space reports stage `v1` and no
   active bugs:

```bash
curl -s $HOST/api/workshop/status | jq -c '{space, locator_stage, active_bugs}'
# {"space":"default","locator_stage":"v1","active_bugs":[]}
```

7. PDFs are writable — check out in the test space and fetch that order's
   invoice:

```bash
curl -s -o /dev/null -X POST $HOST/api/cart/items \
  -H 'X-Workshop-Space: smoke-a' -H 'Content-Type: application/json' \
  -d '{"product_id": 1, "quantity": 1}'

ORDER=$(curl -s -X POST $HOST/api/checkout/ \
  -H 'X-Workshop-Space: smoke-a' -H 'Content-Type: application/json' \
  -d '{"name": "Smoke Test", "email": "smoke@example.com",
       "address": "1 Smoke Street, Test City"}' | jq -r .order.id)

curl -s -o /dev/null -w '%{http_code}\n' \
  -H 'X-Workshop-Space: smoke-a' "$HOST/api/docs/orders/$ORDER/invoice.pdf"  # 200
curl -s -o /dev/null -w '%{http_code}\n' \
  -H 'X-Workshop-Space: smoke-b' "$HOST/api/docs/orders/$ORDER/invoice.pdf"  # 404
```

8. Clean up the smoke spaces (section 5.3), or redeploy.

### 5.2 Roll back

Redeploy the previous **version tag** (`X.Y.Z` or `workshop-<id>`) or a digest
recorded in section 8 — never `sha-<short>`, never `edge`. Then run the checks
of 5.1: a tag must report its version in `/health`, a digest must report `dev`
with the recorded digest and revision label.

**The shared-mode guard survives every rollback.** Workshop spaces entered the
shop in `4fa4613`, before the first image was ever published, so every tag in
the registry — `0.2.0` included — carries `spaces.py` and the guard. Shared mode
itself is `WORKSHOP_SHARED_MODE` on the Coolify application, not something baked
into the image, so it outlives the container. A preset POST without a space
therefore answers **401 on every rollback target**, and a 200 means shared mode
was switched off in the environment, not that an older build is running.
Rehearsed against `0.2.0` on 2026-09-22 (section 8).

### 5.3 Reset one space

```bash
curl -s -X POST $HOST/api/workshop/reset -H 'X-Workshop-Space: <handle>'
```

It removes that space's flag values, cart items and runtime orders and reports
what it removed. The space is then back at stage `v1` with no bugs and an empty
cart. Only the `default` space needs the token:

```bash
curl -s -X POST $HOST/api/workshop/reset -H 'Authorization: Bearer <token>'
```

### 5.4 Reset everything

Redeploy. There is no volume (section 3), so the container starts with an empty
`/data`, re-seeds the catalogue and the demo users, and every participant space,
cart and runtime order is gone. Verify with a runtime order id from before the
redeploy: `$HOST/api/docs/orders/<id>/invoice.pdf` must answer 404.

## 6. Load test

The load test lives in this repository (`loadtest/locustfile.py`) and runs from a
machine **outside** the Coolify host network, so the path under test is the one
participants use. Each simulated user works in its own `load-00N` space and
continuously checks that it sees no other space's flags, cart, indicator or
order.

```bash
mkdir -p reports
uv run --group loadtest locust -f loadtest/locustfile.py --headless \
  -H https://<coolify-host> -u 40 -r 4 -t 10m \
  --csv reports/<kind>-<date> --html reports/<kind>-<date>.html
```

- `-u` is the target: registered participants × 1.25, default 40. `-t` is at
  least `10m`.
- Locust must stay a **single process**: no `--processes`, no workers. The
  cross-space order check uses a registry in process memory.
- Exit code 0 means the run passed: p95 of HTML and API requests below 1000 ms
  (requests named `[slow-bug]` are excluded, because the planted bug delays them
  on purpose), zero 5xx, zero `leak:` failures and zero failed `asset:`
  requests. Any `leak:` row or 5xx is a defect to fix, never a reason to scale
  out.
- Keep the CSV and HTML reports outside git and attach them to the pull request;
  record the run in section 8.
- Afterwards **redeploy** to remove the `load-*` spaces.
- `uv run --group loadtest locust -f loadtest/sequence_check.py --headless -H $HOST -u 1 -r 1 --csv reports/sequence`
  is the quick scripted variant: one user, a fixed preset sequence, no orders.

### Early run versus gating run

| | Early run | Gating run |
|---|---|---|
| When | right after `workshop-spaces` merges | T-1 week, after `drift-coverage` and `acceptance-conformance` merged |
| Target | the merge commit's candidate, by digest | the release-candidate commit's candidate, by digest |
| Purpose | tune `pool_size`/`max_overflow`, rehearse the procedures | the capacity evidence, and the scale-out decision |
| `[slow-bug]` | only the naming is checked — the bug has no delay yet | the `[slow-bug]` rows must show a minimum response time of at least 1000 ms |
| Bar | a failed p95 is a warning for the gating run | p95 must be below 1 s; leaks and 5xx are defects |

The gating run is capacity evidence only for the build it ran against. Any
application change merged afterwards, including pool tuning, requires a new
gating run on the new commit. If the `workshop-<id>` tag later points at
application code that differs from the tested commit, repeat the gating run on
the tag.

## 7. Scale-out contingency

Only if the gating run of a single instance fails on p95 (not on leaks or 5xx —
those are defects): run N independent instances, each set up exactly as above,
each in shared mode with its own token.

Participants are split by the **first character of their handle**, so that each
of `a`-`z` and `0`-`9` belongs to exactly one instance and nobody has to think
about which URL is theirs. Record the split, the registered count per instance
and the published URLs:

| Instance | Handle characters | Registered | URL |
|---|---|---|---|
| 1 | | | `https://<coolify-host>` |
| 2 | | | `https://<coolify-host-2>` |

Check the split with a script over that table before publishing it: it must
print each of the 36 characters exactly once with its instance and exit non-zero
on a missing or duplicate character, for example

```bash
# SPLIT: one "<instance> <characters>" line per instance
printf '1 abcdefghijklm\n2 nopqrstuvwxyz0123456789\n' | awk '
  { for (i = 1; i <= length($2); i++) { c = substr($2, i, 1)
      if (c in owner) { print "duplicate: " c; bad = 1 } else owner[c] = $1 } }
  END { split("abcdefghijklmnopqrstuvwxyz0123456789", all, "")
        for (i = 1; i <= 36; i++) { c = all[i]
          if (c in owner) print c " -> " owner[c]; else { print "missing: " c; bad = 1 } }
        exit bad }'
```

Then load-test every instance with that instance's registered handles × 1.25
users (while registrations are incomplete, at least the target divided by N,
rounded up). When the instances share a Coolify host, run them **at the same
time**, because they share CPU, memory and disk. Every run must exit 0; record
one row per instance in section 8 and keep the failed single-instance row.

## 8. Records

### Capacity record

One row per load-test run.

| Kind | Image reference | Commit (revision label) | Digest | `drift_and_bug` listed | Users | Duration | p95 excl. `[slow-bug]` | 5xx | Leaks |
|---|---|---|---|---|---|---|---|---|---|
| early | `ghcr.io/manykarim/demo-webshop@sha256:5989aa13` | 36e729a (`dev`) | `sha256:5989aa139c8e79d93e14f073ec162dd2c3d28c19071371c2b31516913f4d5896` | yes | 40 | 10 min | 1700 ms — over the 1000 ms bar | 0 | 0 |

The early run answers the two questions that matter for the workshop: 9286
requests produced **no 5xx and no `leak:` failure**, so space isolation holds
under 40 concurrent shoppers, including the order documents that Cloudflare
once served across spaces.

Its p95 is over the bar, and the cause is the client, not the shop. Images are
5323 of the 9286 requests and **16.8 GB of the run's 17.0 GB**, because every
product image is a 3.16 MB file; the run therefore pulled 227 Mbit/s for ten
minutes and the HTML and API requests queued behind that traffic on the same
link. Measured from the same machine while the shop was idle, a page answers in
0.11 s and `/api/products/` in 0.09 s, and the image itself is a Cloudflare
`HIT` that never reaches the origin. The database is not the constraint either:
`POST /api/cart/items` stayed at a 370 ms p95 across 353 writes, so
`pool_size=20` and `max_overflow=20` were left unchanged in
`backend/app/core/db.py`.

Run the gating test from a host with real bandwidth, or fix the image weight
first. A p95 measured over a saturated client link says nothing about how the
shop will behave on workshop day.

### Rehearsal record

One row per rehearsed or executed procedure.

| Date | Procedure | Deployment (image reference) | Outcome | Notes |
|---|---|---|---|---|
| 2026-09-22 | 5.3 Reset one space | `edge@sha256:5989aa13` | Pass | `load-001` was driven to stage `v3` with a cart item first; the reset reported 11 flags, 2 cart items and 8 orders removed, then status `v1` with an empty cart |
| 2026-09-22 | 5.1 Redeploy | `edge@sha256:5989aa13` | Pass | Runtime orders 149 (`load-001`) and 148 (`imgfix-before`), both 200 before, answered 404 within 5 s of the deployment finishing; `load-001` read `v1` with an empty cart |
| 2026-09-22 | 5.2 Roll back to a version tag | `ghcr.io/manykarim/demo-webshop:0.2.0` | Pass, against a corrected expectation | `/health` reported `0.2.0` after ~15 s. A preset POST without a space answered **401, not 200**: `0.2.0` is commit `06e6700`, which already contains `spaces.py`, and `WORKSHOP_SHARED_MODE` lives in the environment. Section 5.2 said otherwise and has been corrected |
| 2026-09-22 | 5.2 Redeploy the candidate by digest | `edge@sha256:5989aa13` | Pass | `/health` reported `dev` after ~20 s, the application's image tag matched the recorded digest, a preset POST without a space returned 401 with `WWW-Authenticate: Bearer` and the `X-Workshop-Space` hint, the same POST in `load-001` returned 200, and `default` still read `v1` with no active bugs |

## 9. Checklists

### After `workshop-spaces` merges

- [ ] the merge commit's `main` run of `image.yml` passed `publish`; the `build`
      digest is recorded in section 8
- [ ] the candidate is deployed by digest and verified as in 5.1 (`dev`,
      matching digest, matching revision label)
- [ ] early load test run and recorded; `pool_size`/`max_overflow` tuned and
      committed if needed (a new commit means a new candidate, deployed and
      checked again, and a repeated run)
- [ ] redeploy, rollback and single-space reset rehearsed and recorded
      (section 8), including: the reset returns a space to `v1` with an empty
      cart; after a redeploy a runtime order from before is 404; removing
      `WORKSHOP_ADMIN_TOKEN` fails the deployment with a log naming it, and the
      token is restored afterwards

### T-1 week (gating)

- [ ] `drift-coverage` and `acceptance-conformance` are merged and `main` is
      green
- [ ] the release-candidate commit's candidate is deployed by digest and
      verified as in 5.1
- [ ] `curl -s $HOST/api/workshop/presets | jq -r '.presets | keys[]'` lists
      `drift_and_bug`, which shows `drift-coverage` is in this build
- [ ] gating load test run: exit 0, and the `[slow-bug]` rows in the CSV have a
      minimum response time of at least 1000 ms
- [ ] the run is recorded in section 8 as kind `gating`; scale-out decided
      (section 7) if it failed
- [ ] any later application change, including pool tuning, triggers a new gating
      run before tagging

### T-1 day

- [ ] the `workshop-<id>` tag is deployed and `/health` reports `workshop-<id>`
- [ ] the `<coolify-host>` placeholders in this runbook are filled in
- [ ] the build matches the gating run: the image's
      `org.opencontainers.image.revision` equals the commit recorded in section
      8, or `git diff --stat <tested commit> workshop-<id> -- backend tools
      Dockerfile pyproject.toml uv.lock` is empty (digests differ per tag, so
      they are not compared). Otherwise re-run the gating load test against this
      deployment, record it, and apply section 7 if it fails
- [ ] smoke test with two spaces: preset isolation, the indicator, `Space:
      default` with the hint without a space, and a 401 without a space
- [ ] redeploy to wipe all smoke state
- [ ] the URL and the `X-Workshop-Space` convention are handed to the workshop
      repository's `coolify` profile maintainers, including the note that agent
      configurations open `?space=<handle>` or send the header

### Day of

- [ ] fresh redeploy before participants start
- [ ] `/health` reports `workshop-<id>`
- [ ] `curl -s $HOST/api/workshop/status | jq -c '{space, locator_stage, active_bugs}'`
      without a space reports `default`, `v1` and no active bugs
- [ ] logs watched for 5xx during the day
- [ ] the token stays with the facilitators

## 10. A note on logs

Watch the logs in Coolify for 5xx responses, and nothing else. Do not export,
forward or share access logs: participants' handles appear in URLs
(`?space=<handle>`), headers and cookies, which makes an access log a list of
who did what. Keep log review inside the Coolify UI and let the instance's
logs disappear with the redeploy that ends the workshop.
