"""Tenant isolation.

A cross-tenant leak is the worst bug this kind of product can ship, so the
rule is not left to discipline: `TENANT_MODELS` is cross-checked against the
mapper metadata here, which means adding a table with `org_id` and forgetting
to register it fails the suite rather than quietly bypassing TenantScope.
"""

from __future__ import annotations

import uuid

import pytest

from db import models
from db.repo import TENANT_MODELS, TenantScope


class TestRegistry:
    def test_every_model_with_org_id_is_registered(self):
        """The check that makes the whole scheme self-enforcing."""
        from db.base import Base

        has_org_id = {
            m.class_
            for m in Base.registry.mappers
            if "org_id" in m.class_.__table__.columns
        }
        missing = has_org_id - set(TENANT_MODELS)
        assert not missing, (
            "these models have org_id but are not in TENANT_MODELS, so they can "
            f"be queried without a tenant filter: {[m.__name__ for m in missing]}"
        )

    def test_no_registered_model_lacks_org_id(self):
        """The reverse: a model in the registry without org_id would make
        TenantScope.select() raise at runtime instead of compile time."""
        wrong = [m.__name__ for m in TENANT_MODELS if "org_id" not in m.__table__.columns]
        assert not wrong, f"registered without org_id: {wrong}"

    def test_org_itself_is_not_a_tenant_model(self):
        """Org is the tenant; scoping it to itself would be circular."""
        assert models.Org not in TENANT_MODELS


class TestScopeIsolation:
    @pytest.fixture
    def two_orgs(self):
        from db.base import SessionFactory

        db = SessionFactory()
        a = models.Org(name="Org A")
        b = models.Org(name="Org B")
        db.add_all([a, b])
        db.flush()
        sa, sb = TenantScope(db, a.id), TenantScope(db, b.id)
        sa.create(models.TargetSchema, name="A schema")
        sb.create(models.TargetSchema, name="B schema")
        db.commit()
        yield db, sa, sb
        db.close()

    def test_select_only_returns_own_rows(self, two_orgs):
        _db, sa, sb = two_orgs
        assert [s.name for s in sa.list(models.TargetSchema)] == ["A schema"]
        assert [s.name for s in sb.list(models.TargetSchema)] == ["B schema"]

    def test_get_of_another_tenants_row_reads_as_absent(self, two_orgs):
        """None, not an exception — a distinguishable error would confirm the
        row exists, which is itself a leak."""
        db, sa, sb = two_orgs
        b_row = sb.list(models.TargetSchema)[0]
        assert sa.get(models.TargetSchema, b_row.id) is None
        assert sb.get(models.TargetSchema, b_row.id) is not None

    def test_count_is_scoped(self, two_orgs):
        _db, sa, sb = two_orgs
        assert sa.count(models.TargetSchema) == sb.count(models.TargetSchema) == 1

    def test_create_stamps_the_scopes_org(self, two_orgs):
        _db, sa, _sb = two_orgs
        row = sa.create(models.TargetSchema, name="stamped")
        assert row.org_id == sa.org_id

    def test_create_refuses_an_explicit_foreign_org_id(self, two_orgs):
        """Passing someone else's org_id is exactly the shape of a
        cross-tenant write, so it raises rather than being trusted."""
        _db, sa, sb = two_orgs
        with pytest.raises(PermissionError):
            sa.create(models.TargetSchema, name="smuggled", org_id=sb.org_id)

    def test_create_accepts_a_matching_org_id(self, two_orgs):
        _db, sa, _sb = two_orgs
        row = sa.create(models.TargetSchema, name="explicit", org_id=sa.org_id)
        assert row.org_id == sa.org_id

    def test_non_tenant_model_is_rejected(self, two_orgs):
        _db, sa, _sb = two_orgs
        with pytest.raises(TypeError, match="not a tenant-owned model"):
            sa.select(models.Org)

    def test_audit_events_are_scoped_too(self, two_orgs):
        db, sa, sb = two_orgs
        sa.audit("thing.happened", detail="a")
        db.commit()
        assert sa.count(models.AuditEvent) == 1
        assert sb.count(models.AuditEvent) == 0


class TestApiIsolation:
    """The same guarantee, observed through HTTP rather than the repo."""

    def _signup(self, client, org, email):
        return client.post("/api/auth/signup", json={
            "org_name": org, "email": email, "password": "correct horse battery"})

    def test_one_tenant_cannot_read_anothers_schema_by_id(self, client, second_client):
        self._signup(client, "Acme", "a@acme.example")
        self._signup(second_client, "Beta", "b@beta.example")

        beta_schema_id = second_client.get("/api/schemas").json()[0]["id"]
        # Beta can read it; Acme gets a 404, not a 403.
        assert second_client.get(f"/api/schemas/{beta_schema_id}").status_code == 200
        assert client.get(f"/api/schemas/{beta_schema_id}").status_code == 404

    def test_schema_lists_do_not_overlap(self, client, second_client):
        self._signup(client, "Acme", "a@acme.example")
        self._signup(second_client, "Beta", "b@beta.example")
        a_ids = {s["id"] for s in client.get("/api/schemas").json()}
        b_ids = {s["id"] for s in second_client.get("/api/schemas").json()}
        assert a_ids and b_ids
        assert not (a_ids & b_ids), "seeded templates must be per-org copies, not shared rows"

    def test_a_malformed_id_is_a_404_not_a_500(self, client):
        self._signup(client, "Acme", "a@acme.example")
        assert client.get("/api/schemas/not-a-uuid").status_code == 404

    def test_a_random_uuid_is_a_404(self, client):
        self._signup(client, "Acme", "a@acme.example")
        assert client.get(f"/api/schemas/{uuid.uuid4()}").status_code == 404
