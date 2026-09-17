# Engineering notes

Defects found while building Sheetwright, and what each one changed. They are
recorded because the interesting ones share a property: the code looked
correct, the tests passed, and the output was plausible and wrong. Each entry
is the failure, the cause, and the fix that is now pinned by a test.

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

## Three that only existed in production

These lived in the gap between the app and the platform, which is why the
suite structurally could not reach them.

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

## Two inherited regressions, now pinned

```
"555-010-2200 ext. 14"   →  555010220014      a valid-looking number that dials elsewhere
"Dr. Aiko Tanaka, PhD"   →  PhD Dr. Aiko Tanaka   a credential read as a surname
```

Both were found by *running* the earlier project and being bothered by the
output — not by a specification. Both have named regression tests here, and both
survive the generalization.

---
