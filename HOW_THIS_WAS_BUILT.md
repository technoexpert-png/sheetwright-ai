# How this was built

This project was built by one architect directing Claude Code. That is stated
up front because it is the point, not a disclaimer: the interesting question
about AI-assisted engineering is not *whether* a model can write the code — it
obviously can — but whether the result is architected, verified, and honest
about its own failure modes.

What follows is the operating model, and the bugs it caught.

---

## Where the work came from

The conversion core — structural parsing, LLM column mapping, value
normalization — was **not** written from scratch here. It was lifted from an
earlier ~90-minute project that solved the same problem for **four hardcoded
fields** (`full_name`, `email`, `company`, `phone`). Sheetwright's contribution
is the generalization to **user-defined schemas of arbitrary fields**, plus
everything a product needs around it: tenancy, auth, persistence, a queue, a
review loop, export, and a front end.

That reuse is deliberate. The generalization was the hard part, and it is
visible in the diff: per-field-*name* cleaners became per-field-*type* cleaners,
and a fixed synonym table became name/description similarity scored against
type-driven content sniffing.

## How the work was divided

**The human decided; the AI executed and verified.** Concretely, these were
human calls, argued with the model but not delegated to it:

- `core/` must not import the ORM, so the pipeline is testable without a database
- Postgres as the work queue rather than Redis/Celery, and the conditions under which that stops being right
- No pandas — explicit parsing reads better for a reviewer and merged cells need `openpyxl` regardless
- Every tenant-owned table carries `org_id` *directly*; `TenantScope` is the only way in
- Anonymous trials are real expiring orgs, not a nullable `org_id`
- "No column" and "empty cell" are distinct facts and must never collapse
- The LLM answers one question per upload, not one per row
- What to defer: schema CRUD, the trial reaper, streaming parse

**Parallelism with frozen interfaces.** Independent modules were built
concurrently by separate agents, each against a contract written *before* any of
them started — dataclass signatures for `core/`, and
[`docs/api-contract.md`](docs/api-contract.md) for the front end. The contract
is why four parallel workstreams integrated on first assembly rather than
needing a reconciliation pass.

**Verification proportional to consequence.** A copy change and a migration that
rewrites authoritative state do not get the same scrutiny:

| Claim | How it is actually checked |
|---|---|
| Tenant isolation holds | Cross-tenant reads tested through the repo *and* over HTTP; registry cross-checked against mapper metadata |
| `SKIP LOCKED` works | Two **real simultaneous transactions**, asserting they get different jobs and that one job goes to exactly one worker |
| The pipeline works | End-to-end through the running stack with the **real worker process**, not an inline call |
| The UI renders | Headless browser over every route, with and without a backend |
| Migrations work | The suite builds its schema via Alembic, not `create_all` |

**No API key required, by design.** The mock mapper is the default and is
genuinely useful, which is what lets all 115 tests run offline. A test suite that
needs a paid API is a test suite that stops being run.

---

## Bugs this process caught

These are the most useful part of this document. Each one is output that looked
plausible and was wrong.

### A two-clock race in the queue

```
run_after (set by the DB clock at INSERT) = 19:16:22.197342
_now()    (app clock, used in the filter) = 19:16:22.153601   ← earlier
run_after <= _now()  →  false
```

`jobs.run_after` defaulted to the *database's* `now()`, but the claim query
compared it against the *application's* clock. A just-enqueued job read as
not-yet-due. On one machine that is a microsecond race; with a separate database
host, clock skew turns it into **jobs stalling for however far the app server
drifts behind** — and it would have presented as a mysterious intermittent hang,
not as a bug. Fixed by making the database the only clock the queue trusts.

Found by a test that enqueued a job and immediately claimed it.

### A documented path that was impossible

The API contract said an upload with no session would bootstrap a trial. It
could never work: a first-time visitor cannot supply a `schema_id`, because
their schemas do not exist until that very request creates their org. The
endpoint was documented, tested against, and unreachable. `schema_id` is now
optional.

### An orphan tenant on every rejected upload

File validation ran *after* org creation, so uploading a PDF left a tenant
behind. Reordered, with a test asserting `Org.count() == 0` after a `415`.

### An API route shadowing a UI route

`/uploads` was both an API prefix and the SPA's own history route, so a document
navigation could be answered with JSON. Surfaced by the front-end work, which
had papered over it in a dev proxy. Everything moved under `/api`, and the
workaround was deleted.

### Abbreviations don't match by prefix

`Dept`→`department` and `CCY`→`currency` both fail a prefix test, because real
headers abbreviate by dropping *interior* letters. Subsequence matching fixed
both, and earned `Qty`→quantity and `Amt`→amount for free.

### Three that only existed in production

Deploying found bugs the test suite structurally could not, because each one
lived in the gap between the app and the platform.

**`boto3` was missing from `requirements.txt`.** Object storage would have
failed at runtime and only in production, because development uses the
filesystem backend and never imports it. Nothing in the suite covered the S3
path with real credentials, so the import error had no way to surface locally.

**The image had no front end.** The Dockerfile built the Python app and never
ran the Vite build, so the first deploy came up as a healthy API serving no UI.
Health checks passed the whole time — they check the API, and the API was fine.
The fix was a multi-stage build plus a catch-all route that serves the SPA
without shadowing `/api`.

**The worker outran its own migrations.** On the first deploy it booted about
six seconds before the API finished `alembic upgrade head` and spent those polls
logging `relation "jobs" does not exist`. It recovered on its own — the tick
loop catches and continues rather than dying — so this was cosmetic, but a
fresh deploy dumping a traceback reads as a broken service. It now waits for its
tables. It still does not migrate: racing the version lock is the worse failure.

### Two inherited regressions, now pinned

```
"555-010-2200 ext. 14"   →  555010220014      a valid-looking number that dials elsewhere
"Dr. Aiko Tanaka, PhD"   →  PhD Dr. Aiko Tanaka   a credential read as a surname
```

Both were found by *running* the earlier project and being bothered by the
output — not by a specification. Both have named regression tests here, and both
survive the generalization.

---

## What it cost

**The verification tax is real.** Roughly half the code in this repository is
tests, contracts, and comments explaining *why*. That is not overhead
accidentally incurred; it is the thing that makes the rest safe to move quickly.

**The dominant failure mode is plausible-but-wrong.** Every bug above was
fluent, idiomatic code that looked right. Obvious errors are cheap because they
fail immediately. What costs time is output that is subtly incorrect and reads
well — which is exactly why "it compiles and the happy path works" is not a
finish line.

**Parallelism has coordination costs.** Two concurrent agents collided on
identically-named scratch files, and one clobbered the other's work mid-run.
Namespacing scratch paths per worker fixed it, but the lesson generalises: the
more you fan out, the more the shared surface needs explicit ownership.

**Some diagnoses were wrong, including mine.** I concluded routes weren't
registering because they were absent from `app.routes` — FastAPI 0.141 simply
doesn't expose them that way, and behaviour testing would have settled it in
seconds. Reading internals before testing behaviour cost time twice.

**The most important bug was found by a human, not a test.** On a genuine first
visit the upload page showed *"Could not load schemas: Not authenticated"* — the
schemas request raced the silent trial creation, and because nothing in its
dependencies changed when the session appeared, the error never cleared. No test
caught it, because in development you almost always already have a cookie by the
time you look.

That is the honest limit of this way of working. The model is very good at the
code and at exhaustive checking of things you thought to check. Deciding *what
is worth checking* — and actually looking at the product as a stranger would —
stayed human, and had to.
