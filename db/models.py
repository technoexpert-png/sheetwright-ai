"""Relational model for Sheetwright AI.

Three decisions drive the shape of this file.

*Every tenant-owned row carries `org_id` directly.* Not via a join through some
parent — directly. That makes the isolation rule trivially checkable ("does this
query filter org_id?") and means a missing filter is a visible bug rather than a
subtle one three joins deep. See db.repo.scoped().

*Anonymous trials get a real Org.* The alternative — nullable `org_id` for
trial uploads — would fork every query and every permission check into
"tenant" and "no tenant" paths. A throwaway Org with `is_trial=True` keeps
exactly one code path and lets the reaper delete a trial by deleting its org.

*Structured where we query it, JSONB where we don't.* Schema fields are their
own table because we validate and order them individually. Mapping results,
diagnostics payloads and row values are JSONB because they are always read and
written whole, and inventing columns for them would buy nothing.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ── Tenancy ──────────────────────────────────────────────────────────────────

class Role(str, enum.Enum):
    OWNER = "owner"     # billing + delete the org
    ADMIN = "admin"     # manage members and schemas
    MEMBER = "member"   # upload and convert


class Org(TimestampMixin, Base):
    """A tenant. Trial orgs are real orgs that expire."""

    __tablename__ = "orgs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str | None] = mapped_column(String(80), unique=True)

    # Trial orgs are created for anonymous visitors so tenancy has one code
    # path. `expires_at` lets a reaper delete them wholesale.
    is_trial: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    users: Mapped[list[User]] = relationship(back_populates="org", cascade="all, delete-orphan")
    schemas: Mapped[list[TargetSchema]] = relationship(
        back_populates="org", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # A trial without an expiry would never be collected.
        CheckConstraint(
            "(is_trial = false) OR (expires_at IS NOT NULL)",
            name="ck_trial_org_has_expiry",
        ),
        Index("ix_orgs_trial_expiry", "is_trial", "expires_at"),
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(Enum(Role, name="role"), default=Role.MEMBER, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    org: Mapped[Org] = relationship(back_populates="users")

    # Email is unique per org, not globally: the same person may belong to two
    # tenants, which is normal in B2B SaaS.
    __table_args__ = (UniqueConstraint("org_id", "email", name="uq_users_org_email"),)


class Session(TimestampMixin, Base):
    """Server-side session, so a login can actually be revoked.

    The cookie carries only this row's signed id. Keeping the record server-side
    means logout and "sign out everywhere" are real operations rather than a
    hope that the client discarded its token.
    """

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def is_anonymous(self) -> bool:
        return self.user_id is None

    @staticmethod
    def default_expiry(days: int) -> datetime:
        return _now() + timedelta(days=days)


# ── Target schemas ───────────────────────────────────────────────────────────

class FieldType(str, enum.Enum):
    STRING = "string"
    EMAIL = "email"
    PHONE = "phone"
    NUMBER = "number"
    INTEGER = "integer"
    DATE = "date"
    BOOLEAN = "boolean"


class TargetSchema(TimestampMixin, Base):
    """The shape a customer wants their spreadsheet converted into."""

    __tablename__ = "target_schemas"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # Templates are seeded per-org on creation rather than shared globally, so a
    # customer can edit one without side effects for anyone else.
    from_template: Mapped[str | None] = mapped_column(String(60))

    org: Mapped[Org] = relationship(back_populates="schemas")
    fields: Mapped[list[SchemaField]] = relationship(
        back_populates="schema", cascade="all, delete-orphan",
        order_by="SchemaField.position",
    )

    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_schema_org_name"),)


class SchemaField(Base):
    """One target field.

    `description` is not decoration — it is the primary signal the LLM maps
    against. "Employee's work email, not personal" resolves ambiguity that a
    field *named* `email` never could, so the UI treats it as a first-class
    input rather than an optional note.
    """

    __tablename__ = "schema_fields"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    schema_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("target_schemas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    field_type: Mapped[FieldType] = mapped_column(
        Enum(FieldType, name="field_type"), default=FieldType.STRING, nullable=False
    )
    required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    schema: Mapped[TargetSchema] = relationship(back_populates="fields")

    __table_args__ = (UniqueConstraint("schema_id", "name", name="uq_field_schema_name"),)


# ── Uploads and processing ───────────────────────────────────────────────────

class UploadStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    NEEDS_REVIEW = "needs_review"   # finished, but a mapping was ambiguous
    COMPLETE = "complete"
    ERROR = "error"


class Upload(TimestampMixin, Base):
    """One spreadsheet a customer submitted, and where its processing got to."""

    __tablename__ = "uploads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Null for an anonymous trial upload: the org owns it, no user exists yet.
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # The schema is captured at upload time, but a customer may edit the schema
    # afterwards — so results also record the field list they were produced
    # against. SET NULL keeps a historical result readable after a schema is
    # deleted rather than cascading the evidence away.
    schema_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("target_schemas.id", ondelete="SET NULL"), index=True
    )

    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(180))
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)

    status: Mapped[UploadStatus] = mapped_column(
        Enum(UploadStatus, name="upload_status"), default=UploadStatus.PENDING, nullable=False
    )
    stage: Mapped[str | None] = mapped_column(String(60))
    error: Mapped[str | None] = mapped_column(Text)
    required_action: Mapped[str | None] = mapped_column(Text)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # A human's corrected mapping, `{field_name: source_column | null}`.
    # Stored on the upload rather than inferred from the previous Result,
    # because "this is what the machine decided" and "this is what the human
    # told us to use" are different facts and conflating them makes the
    # worker's behavior depend on how you read a flag. When present, the
    # worker uses it verbatim and skips the mapper entirely.
    override_mapping: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (Index("ix_uploads_org_created", "org_id", "created_at"),)


class JobState(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Job(TimestampMixin, Base):
    """Work queue, implemented in Postgres.

    `SELECT ... FOR UPDATE SKIP LOCKED` gives safe multi-worker dequeue without
    Redis, Celery, or SQS. At this scale that is not a shortcut: it removes a
    service to deploy, monitor, and explain, and the transactional guarantee is
    stronger than a broker with at-least-once delivery and a separate database.
    Revisit when sustained throughput outgrows one Postgres — not before.

    `run_after` carries retry backoff; `locked_by` names the worker holding it
    so a crashed worker's rows can be identified and reclaimed.
    """

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    upload_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("uploads.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    state: Mapped[JobState] = mapped_column(
        Enum(JobState, name="job_state"), default=JobState.QUEUED, nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(120))
    last_error: Mapped[str | None] = mapped_column(Text)

    # The dequeue query filters on (state, run_after) and orders by run_after.
    __table_args__ = (Index("ix_jobs_claimable", "state", "run_after"),)


class Result(TimestampMixin, Base):
    """The mapping decision for one upload, separate from its rows.

    Kept apart from Upload because it is rewritten when a customer overrides a
    mapping and re-runs, while the Upload (the file, who sent it, when) is
    immutable history.
    """

    __tablename__ = "results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    upload_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("uploads.id", ondelete="CASCADE"), nullable=False, index=True
    )

    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    llm_provider: Mapped[str] = mapped_column(String(40), nullable=False)
    # Whether a human corrected the machine's mapping. The single most useful
    # field for judging how well automatic mapping actually performs.
    human_overridden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Read and written whole; no query ever filters inside them.
    schema_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    column_mapping: Mapped[dict] = mapped_column(JSONB, nullable=False)
    unmapped_source_columns: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    summary: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    __table_args__ = (
        UniqueConstraint("upload_id", "revision", name="uq_result_upload_revision"),
    )


class NormalizedRow(Base):
    """One output record. A table, not JSONB, because there are many per upload
    and they are paged, counted, and filtered by completeness in the UI."""

    __tablename__ = "normalized_rows"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    result_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("results.id", ondelete="CASCADE"), nullable=False, index=True
    )

    source_row: Mapped[int] = mapped_column(Integer, nullable=False)
    complete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    fields: Mapped[dict] = mapped_column(JSONB, nullable=False)
    warnings: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    __table_args__ = (
        Index("ix_rows_result_source", "result_id", "source_row"),
        Index("ix_rows_result_incomplete", "result_id", "complete"),
    )


class Diagnostic(Base):
    """A structured finding. `code` is stable and safe for a client to branch on."""

    __tablename__ = "diagnostics"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    result_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("results.id", ondelete="CASCADE"), nullable=False, index=True
    )

    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    column: Mapped[str | None] = mapped_column(String(255))
    target_field: Mapped[str | None] = mapped_column(String(80))
    rows: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    __table_args__ = (Index("ix_diag_result_severity", "result_id", "severity"),)


class AuditEvent(TimestampMixin, Base):
    """Append-only record of who did what.

    Exists from the first migration rather than being retrofitted: an audit log
    added after the fact has a hole exactly where the interesting history was.
    """

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    action: Mapped[str] = mapped_column(String(60), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    details: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    __table_args__ = (Index("ix_audit_org_created", "org_id", "created_at"),)
