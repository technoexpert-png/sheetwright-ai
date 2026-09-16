"""Target-schema listing. Full CRUD lands in step 4 with the conversion flow."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api import deps, dto
from core.templates import SCHEMA_TEMPLATES
from db import models
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
    """The catalogue, readable without a session — it is marketing copy, not data."""
    return {
        key: {"name": spec["name"], "description": spec["description"],
              "fields": spec["fields"]}
        for key, spec in SCHEMA_TEMPLATES.items()
    }


@router.get("/{schema_id}", response_model=dto.SchemaOut)
def get_schema(
    schema_id: str, scope: TenantScope = Depends(deps.current_scope)
) -> dto.SchemaOut:
    import uuid
    try:
        sid = uuid.UUID(schema_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Unknown schema.")
    s = scope.get(models.TargetSchema, sid)
    # Another tenant's schema reads as absent, not forbidden — a 403 here would
    # confirm the id exists.
    if s is None:
        raise HTTPException(status_code=404, detail="Unknown schema.")
    return _out(s)
