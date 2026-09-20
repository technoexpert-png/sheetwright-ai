"""The site should answer at one address, not two.

sheetwrightai.com is served by the same Fly app as www.sheetwrightai.com and
sheetwright-ai.fly.dev. Without a canonical redirect all three serve identical
pages, which splits links and looks unfinished. The redirect is deliberately
narrow, and these tests pin the narrowness as much as the behavior.
"""

from __future__ import annotations

import pytest

from config import settings

CANONICAL = "sheetwrightai.com"


@pytest.fixture
def canonical(monkeypatch):
    """Turn the redirect on for one test, then put the cache back."""
    monkeypatch.setenv("CANONICAL_HOST", CANONICAL)
    settings.cache_clear()
    yield
    monkeypatch.delenv("CANONICAL_HOST", raising=False)
    settings.cache_clear()


class TestCanonicalHost:
    def test_www_redirects_permanently_to_the_bare_domain(self, client, canonical):
        r = client.get("/", headers={"host": f"www.{CANONICAL}"}, follow_redirects=False)
        assert r.status_code == 301
        assert r.headers["location"] == f"https://{CANONICAL}/"

    def test_redirect_keeps_the_path_and_query(self, client, canonical):
        r = client.get("/uploads?page=2", headers={"host": f"www.{CANONICAL}"},
                       follow_redirects=False)
        assert r.headers["location"] == f"https://{CANONICAL}/uploads?page=2"

    def test_redirect_forces_https(self, client, canonical):
        """TestClient speaks http; the redirect must still land on https."""
        r = client.get("/", headers={"host": f"www.{CANONICAL}"}, follow_redirects=False)
        assert r.headers["location"].startswith("https://")

    def test_apex_is_served_not_redirected(self, client, canonical):
        r = client.get("/health", headers={"host": CANONICAL})
        assert r.status_code == 200

    def test_fly_hostname_still_works(self, client, canonical):
        """The fly.dev name stays usable for debugging a bad DNS change."""
        r = client.get("/health", headers={"host": "sheetwright-ai.fly.dev"},
                       follow_redirects=False)
        assert r.status_code == 200

    def test_health_check_with_an_internal_host_is_untouched(self, client, canonical):
        """Fly's checks arrive addressed to the machine, not the domain. A
        redirect here would read as a failing app and cause a restart loop."""
        r = client.get("/health", headers={"host": "172.19.21.41:8000"},
                       follow_redirects=False)
        assert r.status_code == 200

    def test_a_lookalike_domain_is_not_redirected(self, client, canonical):
        """Only www.<canonical> is rewritten, not anything containing it."""
        r = client.get("/health", headers={"host": f"www.{CANONICAL}.evil.test"},
                       follow_redirects=False)
        assert r.status_code == 200

    def test_host_matching_ignores_case_and_port(self, client, canonical):
        r = client.get("/", headers={"host": f"WWW.{CANONICAL.upper()}:443"},
                       follow_redirects=False)
        assert r.status_code == 301
        assert r.headers["location"] == f"https://{CANONICAL}/"

    def test_disabled_by_default(self, client):
        """No CANONICAL_HOST set: dev and tests must see no redirect at all."""
        r = client.get("/health", headers={"host": f"www.{CANONICAL}"},
                       follow_redirects=False)
        assert r.status_code == 200

    def test_api_routes_redirect_too(self, client, canonical):
        """A form posting to www must not silently write under the wrong host."""
        r = client.get("/api/schemas/templates", headers={"host": f"www.{CANONICAL}"},
                       follow_redirects=False)
        assert r.status_code == 301
