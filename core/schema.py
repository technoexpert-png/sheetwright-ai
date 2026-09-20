"""Plain-dataclass view of a user-defined target schema.

Nothing in `core/` — parsing, column mapping, normalization — may import
SQLAlchemy. A customer's schema lives in the database, but the pipeline only
ever *reads* it: field names, types, which are required. Passing ORM instances
inward would drag a session, a connection and a live transaction into every
unit test, and make behavior depend on lazy-loading order. So the API layer
converts DB rows into the immutable value objects below at the edge, and
everything inward takes a `TargetSchemaSpec`.

Validation lives here, not only in DB constraints, because a spec can also come
from a template, an API payload or a test fixture. The pipeline is entitled to
assume every spec it receives is coherent: non-empty, uniquely named fields
with known types.
"""

from __future__ import annotations

from dataclasses import dataclass

# Mirrors the `FieldType` enum in db/models.py. Duplicated deliberately: the
# alternative is core importing the ORM, which is the thing this module exists
# to avoid. The set is small and changes rarely; a mismatch surfaces the moment
# a DB-backed spec is converted, because an unknown type raises here.
VALID_FIELD_TYPES: frozenset[str] = frozenset(
    {"string", "email", "phone", "number", "integer", "date", "boolean"}
)


@dataclass(frozen=True)
class TargetField:
    """One column the customer wants to end up with."""

    name: str
    field_type: str = "string"
    required: bool = False
    # Free text written for the mapper to read ("work email, not personal").
    # It is the strongest signal available when a header is ambiguous.
    description: str | None = None
    # Presentation order, owned by the schema rather than list position, so a
    # caller can reorder fields without rebuilding the tuple.
    position: int = 0


@dataclass(frozen=True)
class TargetSchemaSpec:
    """An ordered, validated set of target fields."""

    name: str
    fields: tuple[TargetField, ...]
    description: str | None = None

    def __post_init__(self) -> None:
        # Accept any sequence but store a tuple: a list would make the spec
        # unhashable and quietly mutable despite frozen=True.
        object.__setattr__(self, "fields", tuple(self.fields))

        if not self.fields:
            raise ValueError(
                f"Target schema {self.name!r} has no fields; "
                "a schema must define at least one field."
            )

        seen: dict[str, str] = {}
        for field_ in self.fields:
            if not field_.name or not field_.name.strip():
                raise ValueError(
                    f"Target schema {self.name!r} has a field with an empty name "
                    f"(at position {field_.position})."
                )
            if field_.field_type not in VALID_FIELD_TYPES:
                raise ValueError(
                    f"Field {field_.name!r} has unknown field_type "
                    f"{field_.field_type!r}; expected one of: "
                    f"{', '.join(sorted(VALID_FIELD_TYPES))}."
                )
            # Case-insensitive, because these names become output column
            # headers and dict keys; `Email` and `email` would be one column to
            # every consumer and an unresolvable ambiguity to the mapper.
            key = field_.name.strip().lower()
            if key in seen:
                raise ValueError(
                    f"Duplicate field name {field_.name!r} in target schema "
                    f"{self.name!r} (already defined as {seen[key]!r})."
                )
            seen[key] = field_.name

    def field(self, name: str) -> TargetField | None:
        """Look a field up by name, matching the way duplicates are rejected."""
        wanted = name.strip().lower()
        for field_ in self.fields:
            if field_.name.strip().lower() == wanted:
                return field_
        return None

    def _ordered(self) -> list[TargetField]:
        return sorted(self.fields, key=lambda f: f.position)

    @property
    def field_names(self) -> list[str]:
        return [f.name for f in self._ordered()]

    @property
    def required_field_names(self) -> list[str]:
        return [f.name for f in self._ordered() if f.required]


def spec_from_dicts(
    name: str,
    fields: list[dict],
    description: str | None = None,
) -> TargetSchemaSpec:
    """Build a spec from plain dicts — the shape `core/templates.py` uses.

    Optional keys may be absent. A dict without `position` falls back to its
    index, so declaration order is preserved for sources that never bothered to
    number their fields; the sort is stable, so explicit and implicit positions
    can coexist.
    """
    built = [
        TargetField(
            name=str(raw.get("name", "")),
            field_type=str(raw.get("field_type", "string")),
            required=bool(raw.get("required", False)),
            description=raw.get("description"),
            position=int(raw["position"]) if raw.get("position") is not None else index,
        )
        for index, raw in enumerate(fields)
    ]
    ordered = tuple(sorted(built, key=lambda f: f.position))
    return TargetSchemaSpec(name=name, fields=ordered, description=description)
