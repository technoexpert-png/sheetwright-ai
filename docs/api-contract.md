# API contract (Phase 1)

Frozen so the front end and back end can be built in parallel. All routes are prefixed **`/api`** (so they cannot collide with the SPA's
own client-side routes). Cookie auth (`sw_session`, httpOnly); every request
sends credentials. `/health` and `/ready` stay at the root for platform probes.

## Session
```
POST /auth/trial        201 -> SessionOut          # anonymous, no body
POST /auth/signup       201 -> SessionOut          # {org_name, email, password}
POST /auth/login        200 -> SessionOut          # {email, password, org_id?}
POST /auth/logout       204
GET  /auth/me           200 -> SessionOut          # authenticated:false when logged out
```
```jsonc
SessionOut = { authenticated: bool, anonymous: bool,
               org: {id, name, is_trial, expires_at} | null,
               user: {id, email, role} | null }
```

## Schemas
```
GET    /schemas                     200 -> SchemaOut[]
GET    /schemas/templates           200 -> { key: {...} }        # public, no session
GET    /schemas/{id}                200 -> SchemaOut | 404
POST   /schemas                     201 -> SchemaOut             # SchemaWrite body
POST   /schemas/from-template/{key} 201 -> SchemaOut             # copy a template
PUT    /schemas/{id}                200 -> SchemaOut             # SchemaWrite; fields replaced wholesale
DELETE /schemas/{id}                204
```
```jsonc
SchemaWrite = {
  name: string,                    // unique within the org
  description?: string,
  fields: [{ name, field_type, required?, description?, position? }]   // >= 1
}
```
Errors: `409` duplicate name, `422` invalid (no fields, duplicate or empty
field name, unknown `field_type`), `404` unknown id or template.

`PUT` replaces the field list wholesale rather than patching it - a partial
field update has no obvious merge semantics when fields are reordered or
renamed, and the editor always holds the whole list anyway.

Deleting a schema does **not** delete uploads converted against it: the upload
keeps `schema_id = null` and each stored result carries its own schema
snapshot, so historical output stays readable and exportable.
```jsonc
SchemaOut = { id, name, description, from_template,
              fields: [{name, field_type, required, description, position}] }
// field_type: string|email|phone|number|integer|date|boolean
```

## Uploads
```
POST /uploads                      202 -> UploadOut   # multipart: file, schema_id?
                                                      # creates a trial session if none;
                                                      # schema_id optional -> org's first schema
GET  /uploads                      200 -> UploadOut[]
GET  /uploads/{id}                 200 -> UploadOut | 404
GET  /uploads/{id}/result          200 -> ResultOut | 404 | 409 (still processing)
PUT  /uploads/{id}/mapping         202 -> UploadOut   # {mapping: {field: source_column|null}}
GET  /uploads/{id}/export?format=  200 -> file        # csv | xlsx | json
```
```jsonc
UploadOut = { id, filename, size_bytes, schema_id, status, stage,
              error, required_action,
              created_at, started_at, finished_at,
              diagnostic_counts: {info?, warning?, error?},
              row_count: int | null }
// status: pending | running | needs_review | complete | error

ResultOut = {
  upload_id, revision, llm_provider, human_overridden,
  schema: { name, fields:[{name, field_type, required, description, position}] },
  column_mapping: {
    "<field>": { target_field, source_column|null, confidence, method,
                 ambiguous, rationale,
                 alternatives: [{source_column, confidence, rationale}] }
  },
  source_columns: string[],              // every header found in the file
  unmapped_source_columns: string[],
  summary: { total_rows, complete_rows, rows_with_warnings,
             mapped_fields[], unmapped_fields[] },
  diagnostics: [{ severity, code, message, column, target_field, rows[] }],
  rows: [{ source_row, complete,
           fields: { "<field>": { value, mapped, source_column, reason } },
           warnings: string[] }]
}
```

`GET /uploads/{id}/result` accepts `?limit=` & `?offset=` for `rows`
(default 100). `summary` always reflects the whole result, not the page.

## Status semantics
- `needs_review` — finished, but at least one mapping was ambiguous or a
  required field went unmapped. The UI should land the user on the review step.
- `409` from `/result` — valid request, wrong time; body carries the live status.
- `422` from `/result` — the upload failed; body carries `error` and
  `required_action`.
