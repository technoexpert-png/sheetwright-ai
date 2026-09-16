"""Request and response bodies.

Kept apart from the SQLAlchemy models on purpose: the wire format and the
storage format change for different reasons, and coupling them means every
column rename becomes an API break.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


class SignupRequest(BaseModel):
    org_name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=12, max_length=200)

    @field_validator("password")
    @classmethod
    def not_trivial(cls, v: str) -> str:
        # A length floor with no composition rules: current guidance favours
        # length over character-class theatre, which mostly produces "P@ssw0rd".
        if v.strip() != v:
            raise ValueError("password must not start or end with whitespace")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    # Only needed when one email exists in more than one organisation.
    org_id: uuid.UUID | None = None


class OrgOut(BaseModel):
    id: uuid.UUID
    name: str
    is_trial: bool
    expires_at: datetime | None = None


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    role: str


class SessionOut(BaseModel):
    """What the client needs to render its header and gate its UI."""

    authenticated: bool
    anonymous: bool
    org: OrgOut | None = None
    user: UserOut | None = None


class OrgChoice(BaseModel):
    id: uuid.UUID
    name: str


class FieldOut(BaseModel):
    name: str
    field_type: str
    required: bool
    description: str | None = None
    position: int


class SchemaOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    from_template: str | None = None
    fields: list[FieldOut]


# ── uploads ──────────────────────────────────────────────────────────────────

class UploadOut(BaseModel):
    id: uuid.UUID
    filename: str
    size_bytes: int
    schema_id: uuid.UUID | None = None
    status: str
    stage: str | None = None
    error: str | None = None
    required_action: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    # Counts rather than the payload: status is polled, and the detail is one
    # request away once processing finishes.
    diagnostic_counts: dict[str, int] = Field(default_factory=dict)
    row_count: int | None = None


class MappingAlternativeOut(BaseModel):
    source_column: str
    confidence: float
    rationale: str | None = None


class ColumnMappingOut(BaseModel):
    target_field: str
    source_column: str | None = None
    confidence: float = 0.0
    method: str = "unmapped"
    ambiguous: bool = False
    rationale: str | None = None
    alternatives: list[MappingAlternativeOut] = Field(default_factory=list)


class DiagnosticOut(BaseModel):
    severity: str
    code: str
    message: str
    column: str | None = None
    target_field: str | None = None
    rows: list[int] = Field(default_factory=list)


class FieldValueOut(BaseModel):
    """`mapped` is the important bit: it separates "the spreadsheet had no
    column for this" from "the column exists but this row was blank"."""

    value: str | None = None
    mapped: bool
    source_column: str | None = None
    reason: str | None = None


class RowOut(BaseModel):
    source_row: int
    complete: bool
    fields: dict[str, FieldValueOut]
    warnings: list[str] = Field(default_factory=list)


class SummaryOut(BaseModel):
    total_rows: int
    complete_rows: int
    rows_with_warnings: int
    mapped_fields: list[str] = Field(default_factory=list)
    unmapped_fields: list[str] = Field(default_factory=list)


class ResultOut(BaseModel):
    upload_id: uuid.UUID
    revision: int
    llm_provider: str
    human_overridden: bool
    schema_: dict = Field(alias="schema")
    column_mapping: dict[str, ColumnMappingOut]
    source_columns: list[str] = Field(default_factory=list)
    unmapped_source_columns: list[str] = Field(default_factory=list)
    summary: SummaryOut
    diagnostics: list[DiagnosticOut] = Field(default_factory=list)
    rows: list[RowOut] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class MappingOverrideRequest(BaseModel):
    """`{field_name: source_column | null}` — null means deliberately unmapped."""

    mapping: dict[str, str | None]
