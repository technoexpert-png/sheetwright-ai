"""Bridge between stored schemas and the pure-Python conversion core.

`core/` deliberately knows nothing about SQLAlchemy — parsing, mapping, and
normalization are testable with plain dataclasses and no database. The cost of
that decoupling is exactly one conversion, and it lives here rather than being
smeared through the pipeline.

The conversion is also a *snapshot*. A customer can edit a schema after an
upload has been converted against it, so a stored result records the field list
it was actually produced from. Without that, a historical result would silently
re-interpret itself whenever the schema changed, and its diagnostics would stop
matching its own rows.
"""

from __future__ import annotations

from core.schema import TargetField, TargetSchemaSpec
from db import models


def spec_from_db(schema: models.TargetSchema) -> TargetSchemaSpec:
    """Convert a stored schema into the core's immutable view of it."""
    return TargetSchemaSpec(
        name=schema.name,
        description=schema.description,
        fields=tuple(
            TargetField(
                name=f.name,
                field_type=f.field_type.value,
                required=f.required,
                description=f.description,
                position=f.position,
            )
            for f in sorted(schema.fields, key=lambda f: f.position)
        ),
    )


def spec_to_snapshot(spec: TargetSchemaSpec) -> dict:
    """Serialize a spec for storage on a Result.

    Plain JSON rather than a foreign key: the point is to freeze what the
    conversion actually used, so it must survive the schema being edited or
    deleted afterwards.
    """
    return {
        "name": spec.name,
        "description": spec.description,
        "fields": [
            {
                "name": f.name,
                "field_type": f.field_type,
                "required": f.required,
                "description": f.description,
                "position": f.position,
            }
            for f in spec.fields
        ],
    }


def spec_from_snapshot(snapshot: dict) -> TargetSchemaSpec:
    """Rebuild a spec from a stored snapshot, for re-export or re-review."""
    return TargetSchemaSpec(
        name=snapshot.get("name", "Schema"),
        description=snapshot.get("description"),
        fields=tuple(
            TargetField(
                name=f["name"],
                field_type=f.get("field_type", "string"),
                required=bool(f.get("required", False)),
                description=f.get("description"),
                position=int(f.get("position", i)),
            )
            for i, f in enumerate(snapshot.get("fields", []))
        ),
    )
