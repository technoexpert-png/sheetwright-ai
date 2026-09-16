# Architecture

## Shape

```
                 browser
                    │  cookie session (httpOnly, signed, server-side row)
                    ▼
        ┌───────────────────────┐
        │  FastAPI  (api/)      │   thin: validate, resolve tenant, serialise
        │  ├─ routes_auth       │
        │  ├─ routes_schemas    │
        │  └─ routes_uploads    │
        └───────┬───────┬───────┘
                │       │ enqueue
        object  │       ▼
        storage │   ┌───────────────┐   FOR UPDATE SKIP LOCKED
      (core/    │   │  jobs table   │◄──────────────┐
      storage)  │   └───────────────┘               │
                │                                  │ claim
                ▼                          ┌────────┴────────┐
        ┌───────────────┐                  │ worker/run.py   │  N processes
        │  Postgres     │◄─────────────────┤ worker/pipeline │
        └───────────────┘                  └────────┬────────┘
                                                    │
                                    ┌───────────────▼───────────────┐
                                    │  core/  (no ORM, no HTTP)     │
                                    │  parsing → llm → normalize    │
                                    └───────────────────────────────┘
```

`core/` is a pure library. It is imported by the worker and, for exports, by the
API — but it imports neither. That is what makes the conversion pipeline
testable with plain dataclasses.

## Lifecycle of one upload

```
POST /api/uploads
  ├─ validate file (extension, non-empty, size)     ← before creating anything
  ├─ mint a trial org if there is no session
  ├─ store bytes            → {org_id}/{upload_id}/{filename}
  ├─ INSERT upload (pending) + INSERT job (queued)
  └─ 202 { id, status: pending }

worker (≤1s later)
  ├─ claim job              FOR UPDATE SKIP LOCKED, commit the claim first
  ├─ stage=parsing          core.parsing      structure
  ├─ stage=mapping          core.llm          semantics  (or the human override)
  ├─ stage=normalizing      core.normalize    values + diagnostics
  ├─ stage=saving           Result + NormalizedRow* + Diagnostic*
  └─ status = needs_review | complete

PUT /api/uploads/{id}/mapping
  └─ store override on the upload, requeue the SAME job
       → the re-run takes the identical path, so a corrected result
         cannot diverge from a fresh one
```

The claim is committed **before** the work starts. A crash then leaves the row
visibly `RUNNING` for stale reclaim, rather than rolling back and letting two
workers race the same upload.

## Data model

Eleven tables. The ones that carry the design:

| Table | Note |
|---|---|
| `orgs` | The tenant. Trials are real orgs with `expires_at` and a `CHECK` that a trial always has one |
| `sessions` | Server-side, so logout is a real revocation rather than a hope the client discarded its cookie |
| `target_schemas` / `schema_fields` | Relational, because fields are validated and ordered individually. `description` is a first-class input — it is the main signal the mapper reasons over |
| `uploads` | Immutable history of *what arrived*, plus `override_mapping` for a human's corrections |
| `jobs` | The queue. `upload_id` is UNIQUE, so duplicate work is impossible by construction |
| `results` | The mapping decision, separate from the rows, because it is rewritten on re-run while the upload is not. Carries a **schema snapshot** so a historical result survives the schema being edited |
| `normalized_rows` | A table, not JSONB: many per upload, and they are paged, counted, and filtered by completeness |
| `diagnostics` | Structured findings with stable `code`s |
| `audit_events` | Append-only, present from the first migration — an audit log added later has a hole exactly where the interesting history was |

**Structured where we query it, JSONB where we don't.** Field definitions are
relational; mapping payloads and row values are JSONB because they are always
read and written whole.

## Scaling, and when each choice breaks

| Choice | Fine until | Then |
|---|---|---|
| Postgres as the queue | sustained job rate saturates one primary | SQS/Redis behind the same `worker/queue.py` interface |
| Whole file in memory | ~10 MB (enforced) | streaming parse; `parsing` already yields rows |
| One mapper call per upload | never really — it scales with *columns* | cache by header-set hash to skip repeats |
| Rows in Postgres | tens of millions | partition by `org_id`, or move cold results to object storage |
| Single worker process | one CPU of conversion | run more; `SKIP LOCKED` makes it safe with no code change |

## Deployment

### Current target: Fly.io

Two processes from one image — the API and the worker differ only by entrypoint.
Two images would be two things to keep in sync for no benefit at this size.

```
fly.toml         app = sheetwright-ai
  [processes]
    api    = uvicorn api.main:app --host 0.0.0.0 --port 8000
    worker = python -m worker.run
```

Postgres via **Fly Managed Postgres** (`fly mpg`) — unmanaged `fly pg` is
deprecated. Object storage via **Tigris**, which is S3-compatible, so
`core/storage.py` needs only `S3_ENDPOINT_URL` set. Migrations run on the API
process at boot; the worker deliberately does not, so two processes never race
the Alembic version lock on a cold start.

### The same design on AWS

```
              Route 53
                 │
            CloudFront ──────► S3 (web/dist, the SPA)
                 │ /api/*
                 ▼
        ALB ──► ECS Fargate service: api        (2+ tasks, autoscale on RPS)
                 │                              task role, no static keys
                 ├──► RDS Postgres (Multi-AZ)   Secrets Manager for the DSN
                 ├──► S3 bucket (uploads)       SSE-KMS, lifecycle expiry
                 └──► CloudWatch Logs / metrics

        ECS Fargate service: worker             separate service, scales on
                 │                              queue depth (custom metric)
                 └──► same RDS + S3
```

Decisions that matter, rather than a box diagram:

- **API and worker are separate ECS services**, not one task with two
  containers. They scale on different signals — the API on request rate, the
  worker on queue depth — and a worker deploy must not restart the API.
- **Queue depth is a published CloudWatch metric** (`worker/queue.py::depth`),
  which is what makes worker autoscaling possible without SQS.
- **No long-lived credentials.** Task roles for S3 and Secrets Manager; the
  database password is never in an environment file.
- **Uploads get an S3 lifecycle rule** matching trial retention, so expired
  tenant data leaves object storage without a bespoke job.
- **Migrations run as a one-off ECS task** in the deploy pipeline, not at
  container boot — at boot, N scaling tasks would contend for the version lock.
- **RDS Multi-AZ** rather than a read replica: the workload is write-heavy
  (rows, diagnostics, audit) and the queue depends on a single writer.

The application code is identical in both. The only environment-specific pieces
are `DATABASE_URL`, `STORAGE_BACKEND=s3`, `S3_BUCKET`, and
`S3_ENDPOINT_URL` — which is the whole reason storage sits behind a
four-method interface.

## Security posture

- **Argon2id** password hashing, with `check_needs_rehash` on login so stored
  hashes migrate forward as the defaults harden.
- **Server-side sessions**; the cookie carries only a signed reference. Both the
  signature's max age and the row's `expires_at` are checked — a valid signature
  alone is not enough to be logged in.
- **`httpOnly`, `SameSite=Lax`, `Secure` outside development.**
- **Tenant isolation enforced in the data-access layer**, not in each route, and
  cross-checked by a test against the mapper metadata.
- **Account enumeration closed**: a wrong password and an unknown email return
  byte-identical responses.
- **Upload keys are sanitised** and the resolved path is verified to be inside
  the storage root — `../../etc/passwd` reduces to `passwd`.
- **The LLM hallucination guard** discards any source column not verbatim in the
  real header list, so a model cannot invent a column that silently corrupts
  output.

## Known gaps

Listed because a reviewer will find them anyway:

- **No schema CRUD endpoint.** Templates are seeded per org; you cannot yet
  create or edit one via the API, so "user-defined schemas" is half-delivered.
- **The trial reaper is not scheduled.** The model, the constraint, and
  `delete_prefix` all support it; nothing runs it.
- **Rate limiting is absent.** Trials are capped by upload count, which is not
  the same thing.
- **Diagnostics can reference rows outside the loaded page**, and there is no
  "fetch the page containing row N".
