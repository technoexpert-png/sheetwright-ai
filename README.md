# Sheetwright AI

**Convert an arbitrary, badly-formatted spreadsheet into a schema you define.**
Sheetwright reads any CSV or XLSX, uses an LLM to work out which of its columns
maps to which of your fields, and then shows you every decision it made —
confidence scores, the alternatives it considered, and each value it had to
reformat — before you export a clean file.

The hard part isn't parsing. It's **being honest about uncertainty.** Real
exports have merged cells, title rows above the headers, columns called
`Cell #`, and rows missing required data. Sheetwright never silently guesses:
low-confidence mappings are flagged for review, every value carries its
provenance, and anything questionable becomes a structured diagnostic.

> Built with Claude Code. How, and what that cost, is documented in
> **[HOW_THIS_WAS_BUILT.md](HOW_THIS_WAS_BUILT.md)** — including the bugs the
> process caught.

---

## Run it in 60 seconds

```bash
docker compose up
```

That's the whole thing: Postgres, the API, the worker, and migrations.
Then open **<http://localhost:8000/docs>** for the API, or run the front end:

```bash
cd web && npm install && npm run dev     # http://localhost:5173
```

**No API key needed.** The LLM layer defaults to a deterministic mock mapper
(see [below](#the-llm-layer)), which is also what makes the test suite run
offline.

Two sample spreadsheets to try, one semantically messy and one structurally
messy, are described in [docs/samples.md](docs/samples.md).

> Use `localhost`, not `127.0.0.1` — Vite binds IPv6-only by default.

### Tests

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
docker compose up -d db
.venv/bin/python -m pytest        # 74 passed
```

Tests run against **real Postgres**, not SQLite. The schema uses JSONB, UUIDs,
enums, and `FOR UPDATE SKIP LOCKED`; a SQLite stand-in would pass while telling
you nothing about whether production works.

---

## The decisions worth reviewing

### `core/` never imports the ORM

```
core/parsing.py     structure   merged cells, header detection, ragged rows
core/llm.py         semantics   which column means what
core/normalize.py   values      validation, cleaning, diagnostics
```

Parsing, mapping, and normalization operate on plain dataclasses
(`core/schema.py`), so the entire conversion pipeline is testable with no
database and no HTTP. The single conversion between stored schemas and that
view lives in `api/services.py`.

### The LLM answers one question per upload, not one per row

It is asked *which source column maps to which target field* — once. Three
reasons:

1. **Cost and latency scale with columns, not rows.** A 100,000-row file is one
   call.
2. **Auditability.** The mapping is a small object a human can eyeball and
   override. Per-row extraction would be unreviewable.
3. **Determinism where it counts.** Email validation and phone formatting are
   rules, not judgment. Handing them to a model would make identical inputs
   produce different outputs.

### The LLM layer

Two implementations, one protocol, selected by `LLM_PROVIDER`:

| | `MockColumnMapper` (default) | `AnthropicColumnMapper` |
|---|---|---|
| Network | none | Anthropic Messages API |
| Method tag | `mock_llm` | `llm` |

**The mock is not a stub.** It scores every (column, field) pair on two
independent signals:

- **Name similarity** — weighted term overlap between the header and the target
  field's name *and its description*. Descriptions carry real weight:
  *"Work email, not personal"* resolves ambiguity a field merely named `email`
  cannot. Abbreviations match by subsequence, not prefix, because real headers
  drop interior letters (`Dept`→department, `CCY`→currency).
- **Content sniffing driven by field type** — a column whose sampled values are
  all emails is strong evidence for an `email` field regardless of its header.
  This is how `Cell #` still resolves to `phone`. Evidence is capped for
  `string` fields so free text can never win on content alone.

The real path is code-complete: structured output via tool-use (no free-text
parsing), confidences clamped, and a **hallucination guard** that discards any
`source_column` not verbatim in the real header list — a model naming a
plausible column that doesn't exist is the failure most likely to corrupt
output silently. On any error it falls back to the mock and reports
`llm_provider: "mock"`, so a response never misstates its own provenance.

```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-… LLM_PROVIDER=anthropic
```

### Tenancy is structural, not remembered

A cross-tenant leak is the worst bug this kind of product can ship, so the rule
isn't left to discipline:

- Every tenant-owned table carries **`org_id` directly** — not via a join
  through a parent. "Does this query filter `org_id`?" is then trivially
  checkable, and a missing filter is a visible bug rather than one buried three
  joins deep.
- **`TenantScope`** is the only sanctioned way to reach them. `select()` applies
  the filter; `create()` stamps `org_id`; passing someone else's raises.
- **A test cross-checks `TENANT_MODELS` against the mapper metadata**, so adding
  a table with `org_id` and forgetting to register it fails the suite.
- Another tenant's row reads as **absent, not forbidden** — `404`, never `403`,
  because a `403` confirms the id exists.

### Anonymous trials are real, expiring organisations

Not a nullable `org_id`. A trial *is* an `Org` with `is_trial=True` and an
`expires_at` (with a `CHECK` constraint, since a trial without an expiry would
never be collected). That keeps exactly **one** tenancy code path, and a trial
is reaped by deleting its org, which cascades.

Signing up **promotes** the trial rather than abandoning it — losing someone's
work at the moment they decide to become a customer is the worst possible time.

### Postgres is the work queue

`SELECT … FOR UPDATE SKIP LOCKED`. No Redis, Celery, or SQS:

- One fewer service to deploy, monitor, back up, and explain.
- The guarantee is **stronger** — the claim and the state change commit or roll
  back together, rather than at-least-once delivery across two systems that can
  disagree.
- Retries, backoff, and dead-lettering are three columns, not a framework.

The concurrency property is **tested with real simultaneous transactions**, not
asserted in a comment. Revisit when throughput outgrows one Postgres.

### "No column" and "empty cell" are different facts

Both serialise a `null`. They mean completely different things and imply
different fixes, so they're never collapsed:

```jsonc
{"value": null, "mapped": false, "reason": "no source column matched this field"}
// → the spreadsheet has NO column for this. Fix: add one.

{"value": null, "mapped": true, "source_column": "EMAIL",
 "reason": "source cell was empty"}
// → the column exists, this ROW is blank. Fix: fill it in.
```

### Rows are never dropped

A row failing validation is still emitted, with its problem attached and
aggregated into diagnostics. The caller decides what's acceptable. Diagnostics
aggregate **per field** carrying affected row numbers, so a 5,000-row file with
one bad column yields *one* finding, not 5,000.

---

## API

All routes are under `/api`. Full contract:
**[docs/api-contract.md](docs/api-contract.md)**.

| | |
|---|---|
| `POST /api/uploads` | multipart file + optional `schema_id` → `202` |
| `GET /api/uploads/{id}` | status: `pending` → `running` → `needs_review` / `complete` / `error` |
| `GET /api/uploads/{id}/result` | mapping, rows, diagnostics (`409` while running, `422` if failed) |
| `PUT /api/uploads/{id}/mapping` | a human's corrections → re-runs |
| `GET /api/uploads/{id}/export?format=` | `csv` · `xlsx` · `json` |

`needs_review` is its own status: the conversion finished, but a mapping was
ambiguous or a required field went unmapped, so the UI lands the user on the
review step instead of implying success.

---

## Layout

```
api/      routes, auth, tenancy, DTOs
core/     parsing · schema · llm · normalize · export · storage   (no ORM)
worker/   Postgres-backed queue + the conversion pipeline
db/       models + Alembic migrations
web/      React 19 + Vite + Tailwind front end
docs/     api contract, architecture, samples
tests/    74 tests against real Postgres
```

Further reading:
[**ARCHITECTURE.md**](docs/architecture.md) (including the AWS deployment
design) · [**HOW_THIS_WAS_BUILT.md**](HOW_THIS_WAS_BUILT.md)

---

## What I'd do next

- **Schema CRUD.** Templates are seeded per org, but there's no endpoint to
  create a schema yet, so "user-defined" is only half true.
- **Trial reaper** as a scheduled job — the model and constraint support it;
  nothing runs it.
- **Fetch-the-page-containing-row-N**, so a diagnostic referencing row 4,000 can
  jump there.
- **Cache the mapping by header-set hash**, so repeat uploads of the same export
  skip the model entirely.
- **Streaming parse** for files too large to hold in memory.

## Licence

MIT — see [LICENSE](LICENSE).
