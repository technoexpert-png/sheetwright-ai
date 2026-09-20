"""Target-schema listing. Full CRUD lands in step 4 with the conversion flow."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from api import deps, dto
from core.templates import SCHEMA_TEMPLATES
from db import models
from db.base import get_session
from db.repo import TenantScope

router = APIRouter(prefix="/schemas", tags=["schemas"])


def _out(s: models.TargetSchema) -> dto.SchemaOut:
    return dto.SchemaOut(
        id=s.id, name=s.name, description=s.description, from_template=s.from_template,
        fields=[
            dto.FieldOut(
                name=f.name, field_type=f.field_type.value, required=f.required,
                description=f.description, position=f.position,
            )
            for f in s.fields
        ],
    )


@router.get("", response_model=list[dto.SchemaOut])
def list_schemas(scope: TenantScope = Depends(deps.current_scope)) -> list[dto.SchemaOut]:
    """This tenant's schemas. Trials get the seeded templates, same as anyone."""
    return [_out(s) for s in scope.list(models.TargetSchema, limit=200)]


@router.get("/templates")
def list_templates() -> dict:
    """The catalog, readable without a session — it is marketing copy, not data."""
    return {
        key: {"name": spec["name"], "description": spec["description"],
              "fields": spec["fields"]}
        for key, spec in SCHEMA_TEMPLATES.items()
    }


@router.get("/{schema_id}", response_model=dto.SchemaOut)
def get_schema(
    schema_id: str, scope: TenantScope = Depends(deps.current_scope)
) -> dto.SchemaOut:
    s = scope.get(models.TargetSchema, _parse_uuid(schema_id))
    # Another tenant's schema reads as absent, not forbidden — a 403 here would
    # confirm the id exists.
    if s is None:
        raise HTTPException(status_code=404, detail="Unknown schema.")
    return _out(s)


# ── authoring ────────────────────────────────────────────────────────────────

def _parse_uuid(raw: str) -> uuid.UUID:
    """A malformed id is a 404, not a 422.

    From the caller's point of view "that schema does not exist" is true either
    way, and a different status for a malformed id leaks that the route parses
    ids at all.
    """
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise HTTPException(status_code=404, detail="Unknown schema.") from None


def _field_type(raw: str) -> models.FieldType:
    try:
        return models.FieldType(raw)
    except ValueError:
        valid = ", ".join(t.value for t in models.FieldType)
        raise HTTPException(
            status_code=422,
            detail=f"Unknown field type {raw!r}. Expected one of: {valid}.",
        ) from None


def _is_duplicate_name(exc: IntegrityError) -> bool:
    """True only for the org-unique-name constraint.

    Reporting every IntegrityError as a duplicate name produced a 409 saying
    a schema "already exists" while it was renaming itself — a confidently
    wrong message that sends the reader looking in the wrong place. Anything
    else is a bug here, and should surface as one.
    """
    constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
    return constraint == "uq_schema_org_name"


def _apply_fields(
    db: DbSession, schema: models.TargetSchema, body: dto.SchemaWrite
) -> None:
    """Replace the field list wholesale.

    Position comes from the submitted order, not from any position the client
    sends: the editor always holds the whole list, and deriving order from the
    array removes a second source of truth that could disagree with it.

    The clear-and-flush is load-bearing. `schema_fields` has a UNIQUE
    (schema_id, name), and if the replacement list reuses a name — which it
    almost always does, since most edits keep most fields — SQLAlchemy would
    otherwise INSERT the new row before DELETEing the old one and trip the
    constraint. Flushing the removals first makes the order explicit.
    """
    schema.fields.clear()
    db.flush()
    schema.fields = [
        models.SchemaField(
            name=f.name,
            field_type=_field_type(f.field_type),
            required=f.required,
            description=f.description,
            position=i,
        )
        for i, f in enumerate(body.fields)
    ]


def _name_taken(db: DbSession, scope: TenantScope, name: str,
                exclude_id: uuid.UUID | None = None) -> bool:
    q = scope.select(models.TargetSchema).where(models.TargetSchema.name == name)
    if exclude_id is not None:
        q = q.where(models.TargetSchema.id != exclude_id)
    return db.scalars(q).first() is not None


@router.post("", response_model=dto.SchemaOut, status_code=201)
def create_schema(
    body: dto.SchemaWrite,
    db: DbSession = Depends(get_session),
    scope: TenantScope = Depends(deps.current_scope),
    sess: models.Session = Depends(deps.require_session),
) -> dto.SchemaOut:
    """Define a new target schema.

    Available to anonymous trials as well as accounts: a trial that cannot
    define a schema cannot evaluate the product, and the org scoping is
    identical either way.
    """
    if _name_taken(db, scope, body.name):
        raise HTTPException(
            status_code=409, detail=f"A schema named {body.name!r} already exists."
        )

    schema = scope.create(
        models.TargetSchema, name=body.name, description=body.description
    )
    _apply_fields(db, schema, body)
    scope.audit("schema.created", user_id=sess.user_id, target_type="schema",
                name=body.name, field_count=len(body.fields))
    try:
        db.commit()
    except IntegrityError as exc:
        # Belt and braces: the pre-check above races a concurrent create, and
        # the unique constraint is what actually guarantees it. Any *other*
        # integrity error is a bug and must not be disguised as a name clash.
        db.rollback()
        if not _is_duplicate_name(exc):
            raise
        raise HTTPException(
            status_code=409, detail=f"A schema named {body.name!r} already exists."
        ) from None
    db.refresh(schema)
    return _out(schema)


@router.post("/from-template/{key}", response_model=dto.SchemaOut, status_code=201)
def create_from_template(
    key: str,
    db: DbSession = Depends(get_session),
    scope: TenantScope = Depends(deps.current_scope),
    sess: models.Session = Depends(deps.require_session),
) -> dto.SchemaOut:
    """Copy a starter template into this org.

    A copy, not a reference: editing "Contacts" must not change it for every
    other tenant. If the name is taken, a numeric suffix is appended rather
    than failing - the caller asked for a template, not for a specific name.
    """
    spec = SCHEMA_TEMPLATES.get(key)
    if spec is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown template {key!r}. Available: "
                   f"{', '.join(sorted(SCHEMA_TEMPLATES))}.",
        )

    name = spec["name"]
    suffix = 2
    while _name_taken(db, scope, name):
        name = f"{spec['name']} {suffix}"
        suffix += 1

    schema = scope.create(
        models.TargetSchema, name=name, description=spec["description"],
        from_template=key,
    )
    schema.fields = [
        models.SchemaField(
            name=f["name"], field_type=models.FieldType(f["field_type"]),
            required=f["required"], description=f["description"], position=i,
        )
        for i, f in enumerate(spec["fields"])
    ]
    scope.audit("schema.created_from_template", user_id=sess.user_id,
                target_type="schema", template=key, name=name)
    db.commit()
    db.refresh(schema)
    return _out(schema)


@router.put("/{schema_id}", response_model=dto.SchemaOut)
def update_schema(
    schema_id: str,
    body: dto.SchemaWrite,
    db: DbSession = Depends(get_session),
    scope: TenantScope = Depends(deps.current_scope),
    sess: models.Session = Depends(deps.require_session),
) -> dto.SchemaOut:
    """Replace a schema's name, description, and field list.

    Editing a schema does not retroactively change results already produced
    against it: each stored result carries its own schema snapshot. Re-running
    an upload picks up the new definition; existing output stays as reviewed.
    """
    sid = _parse_uuid(schema_id)
    schema = scope.get(models.TargetSchema, sid)
    if schema is None:
        raise HTTPException(status_code=404, detail="Unknown schema.")

    if _name_taken(db, scope, body.name, exclude_id=sid):
        raise HTTPException(
            status_code=409, detail=f"A schema named {body.name!r} already exists."
        )

    schema.name = body.name
    schema.description = body.description
    # Once edited by hand it is no longer the template it came from, and
    # claiming otherwise would mislead anyone reading `from_template`.
    schema.from_template = None
    _apply_fields(db, schema, body)
    scope.audit("schema.updated", user_id=sess.user_id, target_type="schema",
                target_id=sid, field_count=len(body.fields))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if not _is_duplicate_name(exc):
            raise
        raise HTTPException(
            status_code=409, detail=f"A schema named {body.name!r} already exists."
        ) from None
    db.refresh(schema)
    return _out(schema)


@router.delete("/{schema_id}", status_code=204)
def delete_schema(
    schema_id: str,
    db: DbSession = Depends(get_session),
    scope: TenantScope = Depends(deps.current_scope),
    sess: models.Session = Depends(deps.require_session),
) -> Response:
    """Delete a schema.

    Uploads converted against it are deliberately NOT deleted: `uploads.
    schema_id` is ON DELETE SET NULL and every result carries a schema
    snapshot, so historical output stays readable and exportable. Cascading
    here would destroy the customer's work to tidy up a definition.
    """
    sid = _parse_uuid(schema_id)
    schema = scope.get(models.TargetSchema, sid)
    if schema is None:
        raise HTTPException(status_code=404, detail="Unknown schema.")

    scope.audit("schema.deleted", user_id=sess.user_id, target_type="schema",
                target_id=sid, name=schema.name)
    db.delete(schema)
    db.commit()
    return Response(status_code=204)
