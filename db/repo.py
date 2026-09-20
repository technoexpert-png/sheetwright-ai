"""Tenant-scoped data access.

The isolation rule for this application is one sentence: *every query against a
tenant-owned table filters on `org_id`.* The risk is not that someone disagrees
with the rule — it is that someone forgets it once, in a hurry, and nothing
complains. A cross-tenant leak is the worst bug a SaaS product can ship.

So the rule is made structural rather than remembered:

- `TENANT_MODELS` names every model carrying `org_id`. A test asserts the set
  matches reality, so adding a tenant table without registering it fails CI.
- `TenantScope` is the only sanctioned way to read or write them. Its `select`
  applies the filter for you, and `create` stamps `org_id` on insert, so the
  safe path is also the shortest path.
- `get` returns None for a row belonging to another tenant rather than raising
  a distinguishable error — a 404 must not reveal that some other tenant's
  record exists.
"""

from __future__ import annotations

import uuid
from typing import Any, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session as DbSession

from db import models

# Every model with an org_id column. Kept explicit, and cross-checked by
# tests/test_tenancy.py against the mapper metadata.
TENANT_MODELS: frozenset[type] = frozenset({
    models.User,
    models.Session,
    models.TargetSchema,
    models.Upload,
    models.Job,
    models.Result,
    models.NormalizedRow,
    models.Diagnostic,
    models.AuditEvent,
})

T = TypeVar("T")


class TenantScope:
    """All reads and writes for one organization."""

    def __init__(self, db: DbSession, org_id: uuid.UUID) -> None:
        self.db = db
        self.org_id = org_id

    # ── reads ───────────────────────────────────────────────────────────────

    def select(self, model: type[T]) -> Select[tuple[T]]:
        """A SELECT already filtered to this tenant."""
        self._require_tenant_model(model)
        return select(model).where(model.org_id == self.org_id)  # type: ignore[attr-defined]

    def get(self, model: type[T], row_id: uuid.UUID) -> T | None:
        """Fetch by id *within this tenant*. Another tenant's row reads as absent."""
        self._require_tenant_model(model)
        return self.db.scalars(
            self.select(model).where(model.id == row_id)  # type: ignore[attr-defined]
        ).first()

    def list(self, model: type[T], *, limit: int = 100, offset: int = 0) -> list[T]:
        return list(self.db.scalars(self.select(model).limit(limit).offset(offset)))

    def count(self, model: type[T]) -> int:
        self._require_tenant_model(model)
        return self.db.scalar(
            select(func.count()).select_from(model).where(model.org_id == self.org_id)  # type: ignore[attr-defined]
        ) or 0

    # ── writes ──────────────────────────────────────────────────────────────

    def create(self, model: type[T], **values: Any) -> T:
        """Insert with `org_id` stamped on, so a caller cannot forget it.

        An explicit org_id is rejected rather than trusted: passing one would
        be the exact shape of a cross-tenant write.
        """
        self._require_tenant_model(model)
        if "org_id" in values and values["org_id"] != self.org_id:
            raise PermissionError(
                f"refusing to create {model.__name__} for org "
                f"{values['org_id']} from a scope bound to {self.org_id}"
            )
        obj = model(**{**values, "org_id": self.org_id})  # type: ignore[call-arg]
        self.db.add(obj)
        return obj

    def audit(
        self,
        action: str,
        *,
        user_id: uuid.UUID | None = None,
        target_type: str | None = None,
        target_id: uuid.UUID | None = None,
        **details: Any,
    ) -> models.AuditEvent:
        """Record an action. Append-only; never updated or deleted."""
        return self.create(
            models.AuditEvent,
            user_id=user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details,
        )

    # ── internals ───────────────────────────────────────────────────────────

    @staticmethod
    def _require_tenant_model(model: type) -> None:
        if model not in TENANT_MODELS:
            raise TypeError(
                f"{model.__name__} is not a tenant-owned model. Either add it to "
                "TENANT_MODELS (if it has org_id) or query it directly — do not "
                "route non-tenant models through TenantScope."
            )
