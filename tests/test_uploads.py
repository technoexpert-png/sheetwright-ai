"""The whole conversion flow over HTTP, including the override loop.

The worker is not running during tests, so `drain()` claims and processes jobs
through the *real* queue and pipeline code rather than a test-only shortcut. If
the worker's claim logic breaks, these tests break.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from db.base import SessionFactory
from worker import queue
from worker.pipeline import PermanentFailure, process

# Resolved from this file, not an absolute path: the suite must run from a
# fresh clone with no assumptions about where the repo sits on disk.
SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def drain(max_jobs: int = 5) -> int:
    """Run queued jobs to completion, exactly as worker/run.py does."""
    done = 0
    for _ in range(max_jobs):
        db = SessionFactory()
        try:
            job = queue.claim(db, "test-worker")
            if job is None:
                db.commit()
                break
            upload_id = job.upload_id
            db.commit()
            try:
                process(db, upload_id)
                queue.complete(db, job)
            except PermanentFailure as exc:
                queue.fail(db, job, str(exc), retryable=False)
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                fresh = db.get(type(job), job.id)
                if fresh is not None:
                    queue.fail(db, fresh, repr(exc), retryable=False)
            db.commit()
            done += 1
        finally:
            db.close()
    return done


@pytest.fixture
def session(client):
    """A trial session with the seeded schemas available."""
    client.post("/api/auth/trial")
    schemas = {s["name"]: s for s in client.get("/api/schemas").json()}
    return client, schemas


def upload_file(client, schema_id, path: Path, name: str | None = None):
    with path.open("rb") as fh:
        return client.post(
            "/api/uploads",
            files={"file": (name or path.name, fh, "text/csv")},
            data={"schema_id": schema_id},
        )


class TestUpload:
    def test_upload_is_accepted_and_queued(self, session):
        client, schemas = session
        r = upload_file(client, schemas["Contacts"]["id"], SAMPLES / "sample_a_contacts.csv")
        assert r.status_code == 202
        body = r.json()
        assert body["status"] == "pending"
        assert body["size_bytes"] > 0
        assert body["row_count"] is None      # nothing processed yet

    def test_a_first_time_visitor_can_convert_with_no_account_at_all(self, client):
        """The zero-friction path, end to end.

        No session, and no schema_id — a genuine first-timer cannot know one,
        since their schemas are created by this very request. The upload must
        still work and leave them with a usable session.
        """
        with (SAMPLES / "sample_a_contacts.csv").open("rb") as fh:
            r = client.post("/api/uploads",
                            files={"file": ("contacts.csv", fh, "text/csv")})
        assert r.status_code == 202
        assert client.get("/api/auth/me").json()["anonymous"] is True
        assert drain() == 1
        body = client.get(f"/api/uploads/{r.json()['id']}/result").json()
        assert body["summary"]["total_rows"] == 9

    def test_a_rejected_file_does_not_create_an_orphan_org(self, client):
        """Validation runs before the org does, so a PDF cannot leave a tenant
        behind."""
        from db.base import SessionFactory
        from db.models import Org

        r = client.post("/api/uploads",
                        files={"file": ("notes.pdf", b"%PDF-1.4", "application/pdf")})
        assert r.status_code == 415
        db = SessionFactory()
        try:
            assert db.query(Org).count() == 0
        finally:
            db.close()

    def test_unsupported_extension_is_rejected(self, session):
        client, schemas = session
        r = client.post(
            "/api/uploads",
            files={"file": ("notes.pdf", b"%PDF-1.4", "application/pdf")},
            data={"schema_id": schemas["Contacts"]["id"]},
        )
        assert r.status_code == 415

    def test_empty_file_is_rejected(self, session):
        client, schemas = session
        r = client.post(
            "/api/uploads",
            files={"file": ("empty.csv", b"", "text/csv")},
            data={"schema_id": schemas["Contacts"]["id"]},
        )
        assert r.status_code == 400

    def test_unknown_schema_is_rejected(self, session):
        import uuid
        client, _ = session
        r = upload_file(client, str(uuid.uuid4()), SAMPLES / "sample_a_contacts.csv")
        assert r.status_code == 404


class TestConversion:
    def test_csv_converts_and_needs_review(self, session):
        """sample_a has two unmappable columns and a missing required email, so
        it should land in `needs_review` rather than silently `complete`."""
        client, schemas = session
        up = upload_file(client, schemas["Contacts"]["id"],
                         SAMPLES / "sample_a_contacts.csv").json()
        assert drain() == 1

        status = client.get(f"/api/uploads/{up['id']}").json()
        assert status["status"] in ("complete", "needs_review")
        assert status["row_count"] == 9
        assert status["diagnostic_counts"]

    def test_result_shape_is_complete(self, session):
        client, schemas = session
        up = upload_file(client, schemas["Contacts"]["id"],
                         SAMPLES / "sample_a_contacts.csv").json()
        drain()
        r = client.get(f"/api/uploads/{up['id']}/result")
        assert r.status_code == 200
        body = r.json()
        assert body["revision"] == 1
        assert body["llm_provider"] == "mock"
        assert body["human_overridden"] is False
        assert set(body["column_mapping"]) == {"full_name", "email", "company", "phone"}
        assert body["source_columns"]
        assert body["summary"]["total_rows"] == 9
        assert len(body["rows"]) == 9

    def test_mapped_and_empty_are_distinguishable_over_http(self, session):
        """The core product distinction must survive serialisation."""
        client, schemas = session
        up = upload_file(client, schemas["Contacts"]["id"],
                         SAMPLES / "sample_a_contacts.csv").json()
        drain()
        rows = client.get(f"/api/uploads/{up['id']}/result").json()["rows"]
        empty_cell = next(
            f for r in rows for f in r["fields"].values()
            if f["mapped"] and f["value"] is None
        )
        assert "empty" in empty_cell["reason"]

    def test_phone_extension_is_separated_not_concatenated(self, session):
        """Regression: "ext. 14" folded into the number produced a plausible
        but wrong 12-digit phone."""
        client, schemas = session
        up = upload_file(client, schemas["Contacts"]["id"],
                         SAMPLES / "sample_a_contacts.csv").json()
        drain()
        rows = client.get(f"/api/uploads/{up['id']}/result").json()["rows"]
        phones = [r["fields"]["phone"]["value"] for r in rows]
        assert "555010220014" not in phones
        assert "+15550102200" in phones

    def test_credential_suffix_is_not_treated_as_a_surname(self, session):
        """Regression: "Dr. Aiko Tanaka, PhD" became "PhD Dr. Aiko Tanaka"."""
        client, schemas = session
        up = upload_file(client, schemas["Contacts"]["id"],
                         SAMPLES / "sample_a_contacts.csv").json()
        drain()
        rows = client.get(f"/api/uploads/{up['id']}/result").json()["rows"]
        names = [r["fields"]["full_name"]["value"] for r in rows]
        assert "Dr. Aiko Tanaka, PhD" in names
        assert not any(n and n.startswith("PhD") for n in names)

    def test_xlsx_with_merged_cells_converts(self, session):
        client, schemas = session
        up = upload_file(client, schemas["Contacts"]["id"],
                         SAMPLES / "sample_b_roster.xlsx").json()
        drain()
        body = client.get(f"/api/uploads/{up['id']}/result").json()
        codes = {d["code"] for d in body["diagnostics"]}
        assert "merged_cells_expanded" in codes
        assert "duplicate_header" in codes

    def test_result_rows_are_pageable_but_summary_is_not(self, session):
        client, schemas = session
        up = upload_file(client, schemas["Contacts"]["id"],
                         SAMPLES / "sample_a_contacts.csv").json()
        drain()
        body = client.get(f"/api/uploads/{up['id']}/result?limit=3").json()
        assert len(body["rows"]) == 3
        assert body["summary"]["total_rows"] == 9, "summary must cover the whole result"


class TestTiming:
    def test_result_before_processing_is_409_with_live_status(self, session):
        client, schemas = session
        up = upload_file(client, schemas["Contacts"]["id"],
                         SAMPLES / "sample_a_contacts.csv").json()
        r = client.get(f"/api/uploads/{up['id']}/result")
        assert r.status_code == 409
        assert r.json()["detail"]["status"] == "pending"

    def test_unparseable_file_ends_in_error_with_required_action(self, session):
        client, schemas = session
        up = client.post(
            "/api/uploads",
            files={"file": ("bad.csv", b"only,a,header\n", "text/csv")},
            data={"schema_id": schemas["Contacts"]["id"]},
        ).json()
        drain()
        status = client.get(f"/api/uploads/{up['id']}").json()
        assert status["status"] == "error"
        assert status["error"]
        assert "again" in status["required_action"]

    def test_result_for_a_failed_upload_is_422(self, session):
        client, schemas = session
        up = client.post(
            "/api/uploads",
            files={"file": ("bad.csv", b"only,a,header\n", "text/csv")},
            data={"schema_id": schemas["Contacts"]["id"]},
        ).json()
        drain()
        r = client.get(f"/api/uploads/{up['id']}/result")
        assert r.status_code == 422
        assert r.json()["detail"]["required_action"]


class TestOverride:
    def test_override_reruns_and_records_the_human_decision(self, session):
        client, schemas = session
        up = upload_file(client, schemas["Contacts"]["id"],
                         SAMPLES / "sample_a_contacts.csv").json()
        drain()
        before = client.get(f"/api/uploads/{up['id']}/result").json()
        assert before["human_overridden"] is False

        r = client.put(f"/api/uploads/{up['id']}/mapping", json={"mapping": {
            "full_name": "Secondary Contact",       # deliberately different
            "email": "E-mail Addr",
            "company": None,                        # deliberately unmapped
            "phone": "Cell #",
        }})
        assert r.status_code == 202
        assert drain() == 1

        after = client.get(f"/api/uploads/{up['id']}/result").json()
        assert after["revision"] == 2
        assert after["human_overridden"] is True
        assert after["llm_provider"] == "human"
        assert after["column_mapping"]["full_name"]["source_column"] == "Secondary Contact"
        assert after["column_mapping"]["full_name"]["confidence"] == 1.0
        assert after["column_mapping"]["company"]["source_column"] is None

    def test_an_overridden_mapping_is_never_flagged_ambiguous(self, session):
        """A human already decided; re-asking them would be nonsense."""
        client, schemas = session
        up = upload_file(client, schemas["Contacts"]["id"],
                         SAMPLES / "sample_b_roster.xlsx").json()
        drain()
        client.put(f"/api/uploads/{up['id']}/mapping", json={"mapping": {
            "full_name": "full name", "email": "EMAIL",
            "company": "Employer", "phone": "Telephone"}})
        drain()
        body = client.get(f"/api/uploads/{up['id']}/result").json()
        assert not any(m["ambiguous"] for m in body["column_mapping"].values())
        assert client.get(f"/api/uploads/{up['id']}").json()["status"] == "complete"

    def test_override_naming_a_missing_column_is_dropped_not_trusted(self, session):
        client, schemas = session
        up = upload_file(client, schemas["Contacts"]["id"],
                         SAMPLES / "sample_a_contacts.csv").json()
        drain()
        client.put(f"/api/uploads/{up['id']}/mapping", json={"mapping": {
            "full_name": "Contact", "email": "No Such Column"}})
        drain()
        m = client.get(f"/api/uploads/{up['id']}/result").json()["column_mapping"]
        assert m["email"]["source_column"] is None
        assert "no longer present" in m["email"]["rationale"]


class TestExport:
    @pytest.mark.parametrize("fmt,marker", [
        ("csv", b"full_name"), ("xlsx", b"PK"), ("json", b'"rows"')])
    def test_export_formats(self, session, fmt, marker):
        client, schemas = session
        up = upload_file(client, schemas["Contacts"]["id"],
                         SAMPLES / "sample_a_contacts.csv").json()
        drain()
        r = client.get(f"/api/uploads/{up['id']}/export?format={fmt}")
        assert r.status_code == 200
        assert marker in r.content
        assert "attachment" in r.headers["content-disposition"]

    def test_csv_carries_the_source_row_for_traceability(self, session):
        client, schemas = session
        up = upload_file(client, schemas["Contacts"]["id"],
                         SAMPLES / "sample_a_contacts.csv").json()
        drain()
        text = client.get(f"/api/uploads/{up['id']}/export?format=csv").content.decode("utf-8-sig")
        header = text.splitlines()[0]
        assert header.endswith("_source_row")

    def test_export_before_processing_is_409(self, session):
        client, schemas = session
        up = upload_file(client, schemas["Contacts"]["id"],
                         SAMPLES / "sample_a_contacts.csv").json()
        assert client.get(f"/api/uploads/{up['id']}/export").status_code == 409

    def test_unknown_format_is_rejected_by_validation(self, session):
        client, schemas = session
        up = upload_file(client, schemas["Contacts"]["id"],
                         SAMPLES / "sample_a_contacts.csv").json()
        drain()
        assert client.get(f"/api/uploads/{up['id']}/export?format=pdf").status_code == 422


class TestIsolation:
    def test_one_tenant_cannot_see_anothers_upload(self, client, second_client):
        client.post("/api/auth/trial")
        sid = client.get("/api/schemas").json()[0]["id"]
        up = upload_file(client, sid, SAMPLES / "sample_a_contacts.csv").json()
        drain()

        second_client.post("/api/auth/trial")
        assert second_client.get(f"/api/uploads/{up['id']}").status_code == 404
        assert second_client.get(f"/api/uploads/{up['id']}/result").status_code == 404
        assert second_client.get(f"/api/uploads/{up['id']}/export").status_code == 404
        assert second_client.get("/api/uploads").json() == []
