"""FastAPI dependencies: session, tenant scope, and role checks.

The chain is deliberately explicit — `session -> scope -> user -> role` — so a
route's signature states exactly how much authority it requires. A route asking
only for `scope` can be read at a glance as "any member of this tenant,
including an anonymous trial", and one asking for `require_admin` cannot
accidentally be reached by a trial visitor.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session as DbSession

from config import settings
from db import models
from db.base import get_session
from db.repo import TenantScope
from api.security import sign_session_id, unsign_session_id


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── session ──────────────────────────────────────────────────────────────────

def current_session(
    request: Request, db: DbSession = Depends(get_session)
) -> models.Session | None:
    """Resolve the signed cookie to a live Session row, or None.

    Three things must all hold: the signature verifies, the row exists, and the
    row is neither expired nor revoked. A valid signature alone is not enough —
    that is the whole reason sessions are stored server-side.
    """
    token = request.cookies.get(settings().session_cookie)
    if not token:
        return None
    session_id = unsign_session_id(token)
    if session_id is None:
        return None
    row = db.get(models.Session, session_id)
    if row is None or row.revoked_at is not None or row.expires_at <= _now():
        return None
    return row


def require_session(
    sess: models.Session | None = Depends(current_session),
) -> models.Session:
    if sess is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return sess


def start_session(
    db: DbSession,
    response: Response,
    *,
    org_id,
    user_id=None,
) -> models.Session:
    """Create a session row and set the signed cookie.

    Used for both signup/login and anonymous trials — a trial is just a session
    with no user, which is why tenancy needs no special case for it.
    """
    row = models.Session(
        org_id=org_id,
        user_id=user_id,
        expires_at=_now() + timedelta(days=settings().session_days),
        last_seen_at=_now(),
    )
    db.add(row)
    db.flush()
    response.set_cookie(
        settings().session_cookie,
        sign_session_id(row.id),
        max_age=settings().session_days * 86400,
        httponly=True,                                     # not readable by JS
        samesite="lax",                                    # survives top-level nav
        secure=settings().environment != "development",    # HTTPS-only in prod
    )
    return row


def end_session(db: DbSession, response: Response, sess: models.Session) -> None:
    """Revoke server-side, then clear the cookie. Order matters: revoking first
    means a stolen cookie is already useless even if the clear is lost."""
    sess.revoked_at = _now()
    db.flush()
    response.delete_cookie(settings().session_cookie)


# ── tenant scope ─────────────────────────────────────────────────────────────

def current_scope(
    sess: models.Session = Depends(require_session),
    db: DbSession = Depends(get_session),
) -> TenantScope:
    """The only sanctioned handle on tenant data for this request."""
    return TenantScope(db, sess.org_id)


def current_org(
    sess: models.Session = Depends(require_session),
    db: DbSession = Depends(get_session),
) -> models.Org:
    org = db.get(models.Org, sess.org_id)
    if org is None:
        # The session outlived its org — a reaped trial, most likely.
        raise HTTPException(status_code=401, detail="Session is no longer valid.")
    return org


# ── user and roles ───────────────────────────────────────────────────────────

def current_user(
    sess: models.Session | None = Depends(current_session),
    db: DbSession = Depends(get_session),
) -> models.User | None:
    """None for an anonymous trial. Routes that tolerate trials use this."""
    if sess is None or sess.user_id is None:
        return None
    return db.get(models.User, sess.user_id)


def require_user(user: models.User | None = Depends(current_user)) -> models.User:
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="This action requires an account. Sign up to keep your work.",
        )
    return user


def require_role(*allowed: models.Role) -> Callable[..., models.User]:
    """Dependency factory: `Depends(require_role(Role.OWNER, Role.ADMIN))`."""

    def _check(user: models.User = Depends(require_user)) -> models.User:
        if user.role not in allowed:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Requires role {' or '.join(r.value for r in allowed)}; "
                    f"you are {user.role.value}."
                ),
            )
        return user

    return _check


require_admin = require_role(models.Role.OWNER, models.Role.ADMIN)
require_owner = require_role(models.Role.OWNER)
