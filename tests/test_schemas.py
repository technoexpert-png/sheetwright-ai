"""Target-schema authoring: create, edit, reorder, delete.

The behavior worth protecting here is what happens to *existing work* when a
definition changes. A schema is not just configuration — uploads were
converted against it, and those results must stay readable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_uploads import drain

SAMPLES = Path(__file__).resolve().parent.parent / "samples"

CONTACTS = {
    "name": "People",
    "description": "Anyone we can email",
    "fields": [
        {"name": "full_name", "field_type": "string", "required": True,
         "description": "Natural order, first then last"},
        {"name": "email", "field_type": "email", "required": True,
         "description": "Work address, not personal"},
    ],
}


@pytest.fixture
def client_with_session(client):
    client.post("/api/auth/trial")
    return client


class TestCreate:
    def test_creates_a_schema_with_ordered_fields(self, client_with_session):
        c = client_with_session
        r = c.post("/api/schemas", json=CONTACTS)
        assert r.status_code == 201
        body = r.json()
        assert body["name"] == "People"
        assert [f["name"] for f in body["fields"]] == ["full_name", "email"]
        assert [f["position"] for f in body["fields"]] == [0, 1]

    def test_position_is_derived_from_order_not_from_the_client(self, client_with_session):
        """The editor holds the whole list; honouring a client-sent position
        would create a second source of truth that can disagree with it."""
        c = client_with_session
        payload = {
            "name": "Ordered",
            "fields": [
                {"name": "b", "position": 99},
                {"name": "a", "position": 0},
            ],
        }
        fields = c.post("/api/schemas", json=payload).json()["fields"]
        assert [f["name"] for f in fields] == ["b", "a"]
        assert [f["position"] for f in fields] == [0, 1]

    def test_descriptions_survive(self, client_with_session):
        """Descriptions are the mapper's main signal, so losing them silently
        would degrade mapping quality with no visible cause."""
        c = client_with_session
        fields = c.post("/api/schemas", json=CONTACTS).json()["fields"]
        assert fields[1]["description"] == "Work address, not personal"

    def test_duplicate_name_is_409(self, client_with_session):
        c = client_with_session
        c.post("/api/schemas", json=CONTACTS)
        r = c.post("/api/schemas", json=CONTACTS)
        assert r.status_code == 409
        assert "already exists" in r.json()["detail"]

    def test_the_new_schema_is_usable_immediately(self, client_with_session):
        """A schema you cannot convert against is not a schema."""
        c = client_with_session
        sid = c.post("/api/schemas", json=CONTACTS).json()["id"]
        with (SAMPLES / "sample_a_contacts.csv").open("rb") as fh:
            up = c.post("/api/uploads",
                        files={"file": ("a.csv", fh, "text/csv")},
                        data={"schema_id": sid}).json()
        drain()
        result = c.get(f"/api/uploads/{up['id']}/result").json()
        assert set(result["column_mapping"]) == {"full_name", "email"}
        assert result["summary"]["total_rows"] == 9


class TestValidation:
    @pytest.mark.parametrize("payload,why", [
        ({"name": "X", "fields": []}, "no fields"),
        ({"name": "  ", "fields": [{"name": "a"}]}, "blank schema name"),
        ({"name": "X", "fields": [{"name": "a"}, {"name": "A"}]}, "duplicate field name"),
        ({"name": "X", "fields": [{"name": ""}]}, "blank field name"),
    ])
    def test_rejected_with_422(self, client_with_session, payload, why):
        assert client_with_session.post("/api/schemas", json=payload).status_code == 422, why

    def test_unknown_field_type_names_the_valid_ones(self, client_with_session):
        """An error that only says "invalid" makes the caller go and read the
        source."""
        r = client_with_session.post("/api/schemas", json={
            "name": "X", "fields": [{"name": "a", "field_type": "wibble"}]})
        assert r.status_code == 422
        assert "email" in r.json()["detail"] and "boolean" in r.json()["detail"]

    def test_whitespace_in_names_is_normalised(self, client_with_session):
        r = client_with_session.post("/api/schemas", json={
            "name": "  Spaced   Out ", "fields": [{"name": " full   name "}]})
        assert r.json()["name"] == "Spaced Out"
        assert r.json()["fields"][0]["name"] == "full name"


class TestTemplates:
    def test_creates_from_a_template(self, client_with_session):
        r = client_with_session.post("/api/schemas/from-template/products")
        assert r.status_code == 201
        body = r.json()
        assert body["from_template"] == "products"
        assert "sku" in [f["name"] for f in body["fields"]]

    def test_a_second_copy_gets_a_suffix_rather_than_failing(self, client_with_session):
        """The caller asked for a template, not for a particular name."""
        c = client_with_session
        first = c.post("/api/schemas/from-template/products").json()["name"]
        second = c.post("/api/schemas/from-template/products")
        assert second.status_code == 201
        assert second.json()["name"] != first

    def test_unknown_template_lists_the_real_ones(self, client_with_session):
        r = client_with_session.post("/api/schemas/from-template/nope")
        assert r.status_code == 404
        assert "contacts" in r.json()["detail"]

    def test_a_template_copy_is_independent(self, client_with_session, second_client):
        """Editing one org's copy must not touch anyone else's."""
        c, other = client_with_session, second_client
        other.post("/api/auth/trial")
        mine = c.post("/api/schemas/from-template/inventory").json()
        theirs = next(s for s in other.get("/api/schemas").json()
                      if s["from_template"] == "inventory")
        c.put(f"/api/schemas/{mine['id']}", json={
            "name": "Mine only", "fields": [{"name": "changed"}]})
        after = other.get(f"/api/schemas/{theirs['id']}").json()
        assert after["name"] == "Inventory"
        assert [f["name"] for f in after["fields"]] != ["changed"]


class TestUpdate:
    def test_replaces_fields_wholesale(self, client_with_session):
        c = client_with_session
        sid = c.post("/api/schemas", json=CONTACTS).json()["id"]
        r = c.put(f"/api/schemas/{sid}", json={
            "name": "People", "fields": [{"name": "email", "field_type": "email"}]})
        assert r.status_code == 200
        assert [f["name"] for f in r.json()["fields"]] == ["email"]

    def test_reordering_is_just_a_different_array_order(self, client_with_session):
        c = client_with_session
        sid = c.post("/api/schemas", json=CONTACTS).json()["id"]
        flipped = {"name": "People", "fields": list(reversed(CONTACTS["fields"]))}
        fields = c.put(f"/api/schemas/{sid}", json=flipped).json()["fields"]
        assert [f["name"] for f in fields] == ["email", "full_name"]

    def test_editing_clears_from_template(self, client_with_session):
        """It is no longer the template it came from, and saying otherwise
        would mislead anyone reading that field."""
        c = client_with_session
        s = c.post("/api/schemas/from-template/contacts").json()
        assert s["from_template"] == "contacts"
        after = c.put(f"/api/schemas/{s['id']}", json={
            "name": s["name"], "fields": [{"name": "only_field"}]}).json()
        assert after["from_template"] is None

    def test_keeping_your_own_name_is_not_a_conflict(self, client_with_session):
        c = client_with_session
        sid = c.post("/api/schemas", json=CONTACTS).json()["id"]
        r = c.put(f"/api/schemas/{sid}", json={
            "name": "People", "fields": [{"name": "x"}]})
        assert r.status_code == 200

    def test_taking_another_schemas_name_is_409(self, client_with_session):
        c = client_with_session
        c.post("/api/schemas", json=CONTACTS)
        other = c.post("/api/schemas", json={"name": "Other",
                                             "fields": [{"name": "x"}]}).json()
        r = c.put(f"/api/schemas/{other['id']}", json={
            "name": "People", "fields": [{"name": "x"}]})
        assert r.status_code == 409

    def test_editing_does_not_rewrite_an_existing_result(self, client_with_session):
        """The snapshot guarantee: output already reviewed must not silently
        re-interpret itself when the definition changes."""
        c = client_with_session
        sid = c.post("/api/schemas", json=CONTACTS).json()["id"]
        with (SAMPLES / "sample_a_contacts.csv").open("rb") as fh:
            up = c.post("/api/uploads", files={"file": ("a.csv", fh, "text/csv")},
                        data={"schema_id": sid}).json()
        drain()
        before = c.get(f"/api/uploads/{up['id']}/result").json()

        c.put(f"/api/schemas/{sid}", json={
            "name": "People", "fields": [{"name": "totally_different"}]})

        after = c.get(f"/api/uploads/{up['id']}/result").json()
        assert set(after["column_mapping"]) == set(before["column_mapping"])
        assert [f["name"] for f in after["schema"]["fields"]] == ["full_name", "email"]


class TestDelete:
    def test_deletes(self, client_with_session):
        c = client_with_session
        sid = c.post("/api/schemas", json=CONTACTS).json()["id"]
        assert c.delete(f"/api/schemas/{sid}").status_code == 204
        assert c.get(f"/api/schemas/{sid}").status_code == 404

    def test_deleting_a_schema_does_not_destroy_converted_uploads(self, client_with_session):
        """Cascading here would delete the customer's work to tidy up a
        definition. The upload keeps schema_id=null and stays exportable from
        its own snapshot."""
        c = client_with_session
        sid = c.post("/api/schemas", json=CONTACTS).json()["id"]
        with (SAMPLES / "sample_a_contacts.csv").open("rb") as fh:
            up = c.post("/api/uploads", files={"file": ("a.csv", fh, "text/csv")},
                        data={"schema_id": sid}).json()
        drain()
        c.delete(f"/api/schemas/{sid}")

        still = c.get(f"/api/uploads/{up['id']}")
        assert still.status_code == 200
        assert still.json()["schema_id"] is None
        assert c.get(f"/api/uploads/{up['id']}/result").status_code == 200
        assert c.get(f"/api/uploads/{up['id']}/export?format=csv").status_code == 200

    def test_unknown_and_malformed_ids_are_both_404(self, client_with_session):
        import uuid
        c = client_with_session
        assert c.delete(f"/api/schemas/{uuid.uuid4()}").status_code == 404
        assert c.delete("/api/schemas/not-a-uuid").status_code == 404


class TestIsolation:
    def test_another_tenant_cannot_read_edit_or_delete(self, client_with_session, second_client):
        c, other = client_with_session, second_client
        other.post("/api/auth/trial")
        sid = c.post("/api/schemas", json=CONTACTS).json()["id"]
        assert other.get(f"/api/schemas/{sid}").status_code == 404
        assert other.put(f"/api/schemas/{sid}",
                         json={"name": "Hijacked", "fields": [{"name": "x"}]}).status_code == 404
        assert other.delete(f"/api/schemas/{sid}").status_code == 404

    def test_authoring_requires_a_session(self, client):
        assert client.post("/api/schemas", json=CONTACTS).status_code == 401
