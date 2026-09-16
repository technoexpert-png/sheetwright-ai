"""The conversion job: stored file in, canonical rows and diagnostics out.

Deliberately not a FastAPI background task. Parsing a large sheet and calling a
model is far too slow to hold a request open, and a background task dies with
the process that spawned it — an upload would silently never finish after a
deploy. A claimed row in Postgres survives that (see worker/queue.py).

`process` never raises. Every failure becomes a terminal state with a message
the customer can act on, because an upload stuck in `running` forever is worse
than one that says why it stopped.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session as DbSession

from api.services import spec_from_db, spec_to_snapshot
from core.export import SOURCE_ROW_COLUMN  # noqa: F401  (documented column name)
from core.llm import ColumnMapping, MappingResult, get_mapper
from core.normalize import LOW_CONFIDENCE_THRESHOLD, normalize
from core.parsing import ParseError, parse_spreadsheet
from core.storage import get_storage
from db import models
from db.repo import TenantScope

logger = logging.getLogger(__name__)

# How many data rows the mapper sees as evidence. Enough for content sniffing
# to be meaningful; small enough to keep a real LLM prompt cheap.
SAMPLE_ROWS_FOR_MAPPING = 5


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PermanentFailure(Exception):
    """A failure retrying cannot fix — a corrupt file, a deleted schema.

    Separated from transient errors so the queue can skip the backoff and tell
    the customer immediately instead of making them wait out three attempts.
    """


def _mapping_from_override(
    override: dict, source_columns: list[str], field_names: list[str]
) -> MappingResult:
    """Build a MappingResult from a human's corrections.

    Confidence is 1.0 and method is "human" — a person looked at it, so there
    is nothing to be uncertain about and nothing to flag for review. Any column
    the human names that is not actually in the file is dropped rather than
    trusted: the file may have been re-uploaded with different headers since
    they reviewed it.
    """
    mappings: dict[str, ColumnMapping] = {}
    used: set[str] = set()
    for name in field_names:
        chosen = override.get(name)
        if chosen and chosen in source_columns and chosen not in used:
            used.add(chosen)
            mappings[name] = ColumnMapping(
                target_field=name, source_column=chosen, confidence=1.0,
                method="human", ambiguous=False,
                rationale="Set manually during review.",
            )
        else:
            reason = (
                "Left unmapped during review." if not chosen
                else f"Column {chosen!r} is no longer present in the file."
            )
            mappings[name] = ColumnMapping(
                target_field=name, source_column=None, confidence=0.0,
                method="unmapped", rationale=reason,
            )
    return MappingResult(
        mappings=mappings,
        unmapped_source_columns=[c for c in source_columns if c not in used],
        provider="human",
    )


def _needs_review(mapping: MappingResult, schema_required: list[str]) -> bool:
    """Should we stop and ask a human before calling this done?

    Two triggers: the mapper was unsure about something, or a required field
    has no column at all. Both mean the output is probably wrong in a way the
    customer can fix in seconds and we cannot fix at all.
    """
    if any(cm.ambiguous for cm in mapping.mappings.values()):
        return True
    return any(
        not mapping.mappings[f].is_mapped
        for f in schema_required
        if f in mapping.mappings
    )


def process(db: DbSession, upload_id) -> None:
    """Run one upload through the pipeline and persist the result."""
    upload = db.get(models.Upload, upload_id)
    if upload is None:
        logger.warning("upload %s disappeared before processing", upload_id)
        return

    scope = TenantScope(db, upload.org_id)
    storage = get_storage()

    try:
        # ── parse ───────────────────────────────────────────────────────────
        upload.status = models.UploadStatus.RUNNING
        upload.stage = "parsing"
        upload.started_at = upload.started_at or _now()
        upload.error = None
        upload.required_action = None
        db.flush()

        try:
            raw = storage.get(upload.storage_key)
        except FileNotFoundError as exc:
            raise PermanentFailure("The stored file is missing.") from exc

        try:
            table = parse_spreadsheet(upload.filename, raw)
        except ParseError as exc:
            raise PermanentFailure(str(exc)) from exc

        # ── resolve the target schema ───────────────────────────────────────
        if upload.schema_id is None:
            raise PermanentFailure("The target schema for this upload was deleted.")
        schema_row = scope.get(models.TargetSchema, upload.schema_id)
        if schema_row is None:
            raise PermanentFailure("The target schema for this upload was deleted.")
        spec = spec_from_db(schema_row)

        # ── map columns: a human's choice wins over the model's ─────────────
        upload.stage = "mapping"
        db.flush()
        if upload.override_mapping:
            mapping = _mapping_from_override(
                upload.override_mapping, table.headers, list(spec.field_names)
            )
        else:
            sample = [r.cells for r in table.rows[:SAMPLE_ROWS_FOR_MAPPING]]
            mapping = get_mapper().map_columns(spec, table.headers, sample)

        # ── normalize ───────────────────────────────────────────────────────
        upload.stage = "normalizing"
        db.flush()
        rows, diagnostics, summary = normalize(spec, table, mapping)

        # ── persist ─────────────────────────────────────────────────────────
        upload.stage = "saving"
        db.flush()
        _replace_result(db, scope, upload, spec, table, mapping, rows, diagnostics, summary)

        review = _needs_review(mapping, list(spec.required_field_names))
        upload.status = (
            models.UploadStatus.NEEDS_REVIEW if review else models.UploadStatus.COMPLETE
        )
        upload.stage = "done"
        upload.finished_at = _now()
        scope.audit(
            "upload.converted",
            user_id=upload.created_by_user_id,
            target_type="upload",
            target_id=upload.id,
            provider=mapping.provider,
            rows=summary.total_rows,
            needs_review=review,
        )
        db.flush()
        logger.info(
            "upload %s -> %s (%d rows, %d diagnostics, provider=%s)",
            upload.id, upload.status.value, summary.total_rows,
            len(diagnostics), mapping.provider,
        )

    except PermanentFailure as exc:
        _terminal_error(
            db, upload, str(exc),
            "Check the file is a valid .csv or .xlsx with a header row and at "
            "least one data row, then upload it again.",
        )
        raise

    except Exception as exc:  # noqa: BLE001 — the worker must not lose the job
        logger.exception("upload %s failed unexpectedly", upload.id)
        _terminal_error(
            db, upload, f"Unexpected error while processing: {exc}",
            "Try again; if it keeps happening, quote this upload id to support.",
        )
        raise


def _terminal_error(db: DbSession, upload, error: str, action: str) -> None:
    upload.status = models.UploadStatus.ERROR
    upload.stage = "failed"
    upload.error = error
    upload.required_action = action
    upload.finished_at = _now()
    db.flush()


def _replace_result(db, scope, upload, spec, table, mapping, rows, diagnostics, summary) -> None:
    """Write a new result revision, discarding the previous one.

    Revisions increment so an audit trail shows how many times a mapping was
    corrected, but only the newest is kept: storing every superseded row set
    would multiply storage for data nobody reads. The Result row itself records
    `human_overridden`, which is the fact worth keeping.
    """
    from sqlalchemy import delete, select

    prev_rev = db.scalar(
        select(models.Result.revision)
        .where(models.Result.upload_id == upload.id)
        .order_by(models.Result.revision.desc())
        .limit(1)
    ) or 0
    db.execute(delete(models.Result).where(models.Result.upload_id == upload.id))

    result = scope.create(
        models.Result,
        upload_id=upload.id,
        revision=prev_rev + 1,
        llm_provider=mapping.provider,
        human_overridden=bool(upload.override_mapping),
        schema_snapshot=spec_to_snapshot(spec),
        column_mapping={
            name: {
                "target_field": cm.target_field,
                "source_column": cm.source_column,
                "confidence": cm.confidence,
                "method": cm.method,
                "ambiguous": cm.ambiguous,
                "rationale": cm.rationale,
                "alternatives": [
                    {"source_column": a.source_column, "confidence": a.confidence,
                     "rationale": a.rationale}
                    for a in cm.alternatives
                ],
            }
            for name, cm in mapping.mappings.items()
        },
        unmapped_source_columns=list(mapping.unmapped_source_columns),
        summary={
            "total_rows": summary.total_rows,
            "complete_rows": summary.complete_rows,
            "rows_with_warnings": summary.rows_with_warnings,
            "mapped_fields": list(summary.mapped_fields),
            "unmapped_fields": list(summary.unmapped_fields),
            "source_columns": list(table.headers),
            "header_row_number": table.header_row_number,
            "sheet_name": table.sheet_name,
            "low_confidence_threshold": LOW_CONFIDENCE_THRESHOLD,
        },
    )
    db.flush()

    for r in rows:
        scope.create(
            models.NormalizedRow,
            result_id=result.id,
            source_row=r.source_row,
            complete=r.complete,
            fields={
                name: {"value": fv.value, "mapped": fv.mapped,
                       "source_column": fv.source_column, "reason": fv.reason}
                for name, fv in r.fields.items()
            },
            warnings=list(r.warnings),
        )
    for d in diagnostics:
        scope.create(
            models.Diagnostic,
            result_id=result.id, severity=d.severity, code=d.code,
            message=d.message, column=d.column, target_field=d.target_field,
            rows=list(d.rows),
        )
    db.flush()
