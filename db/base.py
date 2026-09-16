"""Engine, session factory, and the declarative base.

Sessions are handed out per request by a FastAPI dependency and closed when the
request ends. The worker opens its own short-lived session per job rather than
holding one open across polls, so a long-idle worker never pins a connection.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings().database_url,
    pool_pre_ping=True,   # a recycled Fly machine can leave dead connections
    future=True,
)

SessionFactory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    s = SessionFactory()
    try:
        yield s
    finally:
        s.close()
