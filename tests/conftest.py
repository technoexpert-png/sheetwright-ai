"""Test fixtures.

Tests run against a real Postgres, not SQLite. The schema uses JSONB, UUID
columns, enums, partial-safe indexes and `FOR UPDATE SKIP LOCKED`; a SQLite
stand-in would pass while telling us nothing about whether production works.

DATABASE_URL is set before any application module is imported, because both
`config.settings()` and the SQLAlchemy engine are created at import time.
"""

from __future__ import annotations

import os

TEST_DB = "postgresql+psycopg://sheetwright:sheetwright@localhost:5432/sheetwright_test"
os.environ["DATABASE_URL"] = TEST_DB
os.environ["SECRET_KEY"] = "test-only-secret"
os.environ["ENVIRONMENT"] = "development"   # keeps cookies non-Secure over http

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def migrate() -> None:
    """Build the schema once per session, via Alembic rather than
    `create_all` — so the migrations themselves are under test."""
    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "db/migrations")
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
def clean_tables() -> None:
    """Truncate between tests. Faster than recreating the schema, and
    RESTART IDENTITY keeps sequences from drifting across the suite."""
    from db.base import engine
    from db.base import Base
    import db.models  # noqa: F401

    names = ", ".join(f'"{t}"' for t in Base.metadata.tables)
    with engine.begin() as c:
        c.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def client() -> TestClient:
    """A client with its own cookie jar, so one test's session cannot leak
    into another."""
    from api.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def second_client() -> TestClient:
    """A separate browser, for cross-tenant isolation tests."""
    from api.main import app
    with TestClient(app) as c:
        yield c
