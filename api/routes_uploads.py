"""Upload, poll, review, override, export."""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile,
)
from fastapi.responses import Response as RawResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from api import deps, dto
from api.services import spec_from_snapshot
from config import settings
from core.export import CONTENT_TYPES, export
from core.normalize import FieldValue, NormalizedRowData
from core.storage import build_key, get_storage
from db import models
from db.base import get_session
from db.repo import TenantScope
from worker import queue

router = APIRouter(prefix="/uploads", tags=["uploads"])

ALLOWED_EXTENSIONS = {".csv", ".tsv", ".txt", ".xlsx", ".xlsm"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _upload_out(db: DbSession, u: models.Upload) -> dto.UploadOut:
    """Serialize an upload, with diagnostic counts and row count if finished."""
    result_id = db.scalar(
        select(models.Result.id).where(models.Result.upload_id == u.id)
        .order_by(models.Result.revision.desc()).limit(1)
    )
    counts: dict[str, int] = {}
    row_count = None
    if result_id is not None:
        counts = dict(
            Counter(
                dict(
                    db.execute(
                        select(models.Diagnostic.severity, func.count())
                        .where(models.Diagnostic.result_id == result_id)
                        .group_by(models.Diagnostic.severity)
                    ).all()
                )
            )
        )
        row_count = db.scalar(
            select(func.count()).select_from(models.NormalizedRow)
            .where(models.NormalizedRow.result_id == result_id)
        )
    return dto.UploadOut(
        id=u.id, filename=u.filename, size_bytes=u.size_bytes, schema_id=u.schema_id,
        status=u.status.value, stage=u.stage, error=u.error,
        required_action=u.required_action, created_at=u.created_at,
        started_at=u.started_at, finished_at=u.finished_at,
        diagnostic_counts=counts, row_count=row_count,
    )


@router.post("", response_model=dto.UploadOut, status_code=202)
async def create_upload(
    response: Response,
    file: UploadFile = File(..., description="A .csv or .xlsx spreadsheet"),
    schema_id: uuid.UUID | None = Form(
        None, description="Target schema; defaults to the org's first schema"
    ),
    db: DbSession = Depends(get_session),
    sess: models.Session | None = Depends(deps.current_session),
) -> dto.UploadOut:
    """Store the file and queue it.

    No account required: a visitor with no session gets an anonymous trial org
    created transparently. Demanding signup before a conversion tool will
    convert anything is a bad first run, and tenancy costs nothing extra
    because a trial *is* a real org (see db.models.Org.is_trial).

    `schema_id` is optional for exactly that reason. A genuinely first-time
    visitor cannot know one — their schemas do not exist until their trial org
    is created by this very request — so omitting it falls back to the seeded
    Contacts template. A client that already has a session should always send
    it explicitly.
    """
    # Validate the file BEFORE creating anything. Rejecting a PDF after having
    # created an organization for it leaves an orphan tenant behind.
    filename = file.filename or "upload"
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type {ext or filename!r}. "
                   f"Expected one of: {', '.join(sorted(ALLOWED_EXTENSIONS))}.",
        )

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="That file is empty.")
    if len(raw) > settings().max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the "
                   f"{settings().max_upload_bytes // (1024 * 1024)} MB limit.",
        )

    if sess is None:
        org = models.Org(
            name="Trial", is_trial=True,
            expires_at=_now() + timedelta(hours=settings().trial_retention_hours),
        )
        db.add(org)
        db.flush()
        from core.templates import seed_org_templates
        seed_org_templates(TenantScope(db, org.id))
        sess = deps.start_session(db, response, org_id=org.id)
        db.commit()

    scope = TenantScope(db, sess.org_id)
    org = db.get(models.Org, sess.org_id)

    if schema_id is None:
        # Deterministic default so two visitors get the same starting point.
        schema_row = db.scalars(
            scope.select(models.TargetSchema).order_by(models.TargetSchema.name)
        ).first()
        if schema_row is None:
            raise HTTPException(
                status_code=409,
                detail="This organization has no target schemas yet.",
            )
    else:
        schema_row = scope.get(models.TargetSchema, schema_id)
        if schema_row is None:
            raise HTTPException(status_code=404, detail="Unknown target schema.")
    schema_id = schema_row.id

    # Trials are capped so an anonymous visitor cannot be used to run up
    # unbounded processing on someone else's behalf.
    if org is not None and org.is_trial:
        used = scope.count(models.Upload)
        if used >= settings().trial_upload_limit:
            raise HTTPException(
                status_code=402,
                detail=f"Trials are limited to {settings().trial_upload_limit} "
                       "conversions. Sign up to continue — your existing work is kept.",
            )

    upload = scope.create(
        models.Upload,
        created_by_user_id=sess.user_id,
        schema_id=schema_id,
        filename=filename,
        content_type=file.content_type,
        size_bytes=len(raw),
        storage_key="pending",
    )
    db.flush()
    upload.storage_key = build_key(sess.org_id, upload.id, filename)
    get_storage().put(upload.storage_key, raw)

    queue.enqueue(db, org_id=sess.org_id, upload_id=upload.id)
    scope.audit("upload.created", user_id=sess.user_id, target_type="upload",
                target_id=upload.id, filename=filename, size_bytes=len(raw))
    db.commit()
    return _upload_out(db, upload)


@router.get("", response_model=list[dto.UploadOut])
def list_uploads(
    db: DbSession = Depends(get_session),
    scope: TenantScope = Depends(deps.current_scope),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[dto.UploadOut]:
    rows = db.scalars(
        scope.select(models.Upload)
        .order_by(models.Upload.created_at.desc())
        .limit(limit).offset(offset)
    ).all()
    return [_upload_out(db, u) for u in rows]


@router.get("/{upload_id}", response_model=dto.UploadOut)
def get_upload(
    upload_id: uuid.UUID,
    db: DbSession = Depends(get_session),
    scope: TenantScope = Depends(deps.current_scope),
) -> dto.UploadOut:
    u = scope.get(models.Upload, upload_id)
    if u is None:
        raise HTTPException(status_code=404, detail="Unknown upload.")
    return _upload_out(db, u)


def _latest_result(db: DbSession, scope: TenantScope, upload_id: uuid.UUID):
    return db.scalars(
        scope.select(models.Result).where(models.Result.upload_id == upload_id)
        .order_by(models.Result.revision.desc()).limit(1)
    ).first()


@router.get("/{upload_id}/result", response_model=dto.ResultOut)
def get_result(
    upload_id: uuid.UUID,
    db: DbSession = Depends(get_session),
    scope: TenantScope = Depends(deps.current_scope),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dto.ResultOut:
    """The conversion output. `rows` is paged; `summary` always covers the whole
    result, so a client showing the first page still reports honest totals."""
    u = scope.get(models.Upload, upload_id)
    if u is None:
        raise HTTPException(status_code=404, detail="Unknown upload.")

    if u.status is models.UploadStatus.ERROR:
        # 422, not 500: the request was fine, the file was not.
        raise HTTPException(status_code=422, detail={
            "message": "Processing failed for this upload.",
            "error": u.error, "required_action": u.required_action})

    result = _latest_result(db, scope, upload_id)
    if result is None:
        # 409 tells a poller "valid request, wrong time" and hands back the
        # live status so it needs no second call.
        raise HTTPException(status_code=409, detail={
            "message": "Conversion is not finished yet.",
            "status": u.status.value, "stage": u.stage})

    rows = db.scalars(
        scope.select(models.NormalizedRow)
        .where(models.NormalizedRow.result_id == result.id)
        .order_by(models.NormalizedRow.source_row)
        .limit(limit).offset(offset)
    ).all()
    diags = db.scalars(
        scope.select(models.Diagnostic)
        .where(models.Diagnostic.result_id == result.id)
    ).all()

    return dto.ResultOut(
        upload_id=u.id, revision=result.revision, llm_provider=result.llm_provider,
        human_overridden=result.human_overridden,
        schema=result.schema_snapshot,
        column_mapping={
            k: dto.ColumnMappingOut(**v) for k, v in result.column_mapping.items()
        },
        source_columns=result.summary.get("source_columns", []),
        unmapped_source_columns=result.unmapped_source_columns,
        summary=dto.SummaryOut(**{
            k: result.summary[k] for k in
            ("total_rows", "complete_rows", "rows_with_warnings",
             "mapped_fields", "unmapped_fields")
        }),
        diagnostics=[
            dto.DiagnosticOut(
                severity=d.severity, code=d.code, message=d.message,
                column=d.column, target_field=d.target_field, rows=d.rows,
            ) for d in diags
        ],
        rows=[
            dto.RowOut(
                source_row=r.source_row, complete=r.complete,
                fields={k: dto.FieldValueOut(**v) for k, v in r.fields.items()},
                warnings=r.warnings,
            ) for r in rows
        ],
    )


@router.put("/{upload_id}/mapping", response_model=dto.UploadOut, status_code=202)
def override_mapping(
    upload_id: uuid.UUID,
    body: dto.MappingOverrideRequest,
    db: DbSession = Depends(get_session),
    scope: TenantScope = Depends(deps.current_scope),
) -> dto.UploadOut:
    """Accept a human's corrected mapping and re-run.

    The correction is stored on the upload and the existing job is requeued,
    rather than converting inline: re-running goes through exactly the same
    pipeline as the first attempt, so a corrected result cannot diverge from a
    fresh one.
    """
    u = scope.get(models.Upload, upload_id)
    if u is None:
        raise HTTPException(status_code=404, detail="Unknown upload.")
    if u.status is models.UploadStatus.RUNNING:
        raise HTTPException(
            status_code=409,
            detail="This upload is being processed; wait for it to finish first.",
        )

    u.override_mapping = {k: v for k, v in body.mapping.items()}
    u.status = models.UploadStatus.PENDING
    u.stage = None
    u.error = None
    u.required_action = None
    u.finished_at = None

    job = db.scalars(
        scope.select(models.Job).where(models.Job.upload_id == upload_id)
    ).first()
    if job is None:
        queue.enqueue(db, org_id=scope.org_id, upload_id=upload_id)
    else:
        queue.requeue(db, job)

    scope.audit("upload.mapping_overridden", target_type="upload", target_id=u.id,
                mapping=u.override_mapping)
    db.commit()
    return _upload_out(db, u)


@router.get("/{upload_id}/export")
def export_result(
    upload_id: uuid.UUID,
    format: str = Query("csv", pattern="^(csv|xlsx|json)$"),
    db: DbSession = Depends(get_session),
    scope: TenantScope = Depends(deps.current_scope),
) -> RawResponse:
    """Download the converted data.

    Rebuilt from the stored rows and the schema *snapshot*, not the live schema:
    an export must reproduce what the customer reviewed, even if they have since
    edited the schema.
    """
    u = scope.get(models.Upload, upload_id)
    if u is None:
        raise HTTPException(status_code=404, detail="Unknown upload.")
    result = _latest_result(db, scope, upload_id)
    if result is None:
        raise HTTPException(status_code=409, detail="Conversion is not finished yet.")

    spec = spec_from_snapshot(result.schema_snapshot)
    db_rows = db.scalars(
        scope.select(models.NormalizedRow)
        .where(models.NormalizedRow.result_id == result.id)
        .order_by(models.NormalizedRow.source_row)
    ).all()
    rows = [
        NormalizedRowData(
            source_row=r.source_row,
            fields={k: FieldValue(**v) for k, v in r.fields.items()},
            warnings=list(r.warnings),
            complete=r.complete,
        )
        for r in db_rows
    ]

    payload, content_type = export(format, spec, rows)
    stem = u.filename.rsplit(".", 1)[0][:80] or "sheetwright"
    return RawResponse(
        content=payload,
        media_type=content_type,
        headers={
            "Content-Disposition":
                f'attachment; filename="{stem}-{spec.name.lower()}.{format}"'
        },
    )
