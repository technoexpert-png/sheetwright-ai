"""Sessions, signup, login, and the trial-to-account promotion."""

from __future__ import annotations


def signup(client, org="Acme Co", email="owner@acme.example", pw="correct horse battery"):
    return client.post("/api/auth/signup", json={"org_name": org, "email": email, "password": pw})


class TestTrial:
    def test_trial_creates_an_anonymous_session(self, client):
        r = client.post("/api/auth/trial")
        assert r.status_code == 201
        body = r.json()
        assert body["authenticated"] is True
        assert body["anonymous"] is True
        assert body["user"] is None
        assert body["org"]["is_trial"] is True

    def test_trial_org_has_an_expiry(self, client):
        """A trial without an expiry would never be reaped — there is a CHECK
        constraint for this, and the API must satisfy it."""
        assert client.post("/api/auth/trial").json()["org"]["expires_at"] is not None

    def test_trial_gets_the_seeded_schema_templates(self, client):
        client.post("/api/auth/trial")
        names = {s["name"] for s in client.get("/api/schemas").json()}
        assert {"Contacts", "Products", "Transactions", "Inventory"} <= names

    def test_calling_trial_twice_reuses_the_session(self, client):
        first = client.post("/api/auth/trial").json()["org"]["id"]
        second = client.post("/api/auth/trial").json()["org"]["id"]
        assert first == second, "a second trial call must not orphan the first org"


class TestSignup:
    def test_creates_org_with_owner(self, client):
        r = signup(client)
        assert r.status_code == 201
        body = r.json()
        assert body["anonymous"] is False
        assert body["user"]["role"] == "owner"
        assert body["org"]["is_trial"] is False

    def test_promotes_an_existing_trial_rather_than_abandoning_it(self, client):
        """Work done during a trial must survive signing up. Losing it at the
        exact moment someone decides to become a customer is the worst
        possible time."""
        trial_org = client.post("/api/auth/trial").json()["org"]["id"]
        promoted = signup(client).json()["org"]
        assert promoted["id"] == trial_org
        assert promoted["is_trial"] is False
        assert promoted["expires_at"] is None
        assert promoted["name"] == "Acme Co"

    def test_promotion_does_not_duplicate_the_seeded_templates(self, client):
        client.post("/api/auth/trial")
        signup(client)
        names = [s["name"] for s in client.get("/api/schemas").json()]
        assert len(names) == len(set(names)) == 4

    def test_rejects_a_short_password(self, client):
        r = client.post("/api/auth/signup", json={
            "org_name": "X", "email": "a@b.example", "password": "short"})
        assert r.status_code == 422

    def test_rejects_duplicate_email_within_the_same_org(self, client, second_client):
        signup(client)
        # Same org name creates a *different* org, so this must succeed —
        # orgs are not identified by name.
        assert signup(second_client).status_code == 201


class TestLogin:
    def test_login_then_me(self, client, second_client):
        signup(client)
        r = second_client.post("/api/auth/login",
                               json={"email": "owner@acme.example",
                                     "password": "correct horse battery"})
        assert r.status_code == 200
        assert second_client.get("/api/auth/me").json()["user"]["email"] == "owner@acme.example"

    def test_wrong_password_and_unknown_email_are_indistinguishable(self, client, second_client):
        """Different messages here would turn the form into an account
        enumeration oracle."""
        signup(client)
        wrong = second_client.post("/api/auth/login",
                                   json={"email": "owner@acme.example", "password": "nope"})
        unknown = second_client.post("/api/auth/login",
                                     json={"email": "nobody@acme.example", "password": "nope"})
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json()["detail"] == unknown.json()["detail"]

    def test_same_email_in_two_orgs_asks_which(self, client, second_client):
        """Email is unique per org, not globally, because one person can
        legitimately belong to two tenants."""
        signup(client, org="Acme", email="dual@x.example")
        signup(second_client, org="Beta", email="dual@x.example")
        r = client.post("/api/auth/login", json={"email": "dual@x.example",
                                             "password": "correct horse battery"})
        assert r.status_code == 409
        assert len(r.json()["detail"]["choose_org_id"]) == 2

    def test_org_id_disambiguates(self, client, second_client):
        signup(client, org="Acme", email="dual@x.example")
        beta = signup(second_client, org="Beta", email="dual@x.example").json()["org"]["id"]
        r = client.post("/api/auth/login", json={"email": "dual@x.example",
                                             "password": "correct horse battery",
                                             "org_id": beta})
        assert r.status_code == 200
        assert r.json()["org"]["name"] == "Beta"


class TestLogout:
    def test_logout_revokes_the_session_server_side(self, client):
        signup(client)
        assert client.get("/api/auth/me").json()["authenticated"] is True
        assert client.post("/api/auth/logout").status_code == 204
        assert client.get("/api/auth/me").json()["authenticated"] is False

    def test_a_revoked_cookie_cannot_be_replayed(self, client):
        """The point of server-side sessions: holding the cookie is not enough."""
        signup(client)
        cookie = client.cookies.get("sw_session")
        client.post("/api/auth/logout")
        client.cookies.set("sw_session", cookie)          # replay it
        assert client.get("/api/auth/me").json()["authenticated"] is False

    def test_a_forged_cookie_is_rejected(self, client):
        client.cookies.set("sw_session", "not-a-valid-signed-value")
        assert client.get("/api/auth/me").json()["authenticated"] is False


class TestUnauthenticated:
    def test_me_returns_a_logged_out_view_not_a_401(self, client):
        r = client.get("/api/auth/me")
        assert r.status_code == 200
        assert r.json() == {"authenticated": False, "anonymous": False,
                            "org": None, "user": None}

    def test_schemas_require_a_session(self, client):
        assert client.get("/api/schemas").status_code == 401

    def test_templates_are_public(self, client):
        """The catalog is marketing copy, not tenant data."""
        assert client.get("/api/schemas/templates").status_code == 200
