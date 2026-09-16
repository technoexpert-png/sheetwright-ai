"""Signup, login, logout, anonymous trials, and whoami."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from api import deps, dto
from api.security import hash_password, needs_rehash, verify_password
from config import settings
from core.templates import seed_org_templates
from db import models
from db.base import get_session
from db.repo import TenantScope

router = APIRouter(prefix="/auth", tags=["auth"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _session_out(
    db: DbSession, sess: models.Session | None
) -> dto.SessionOut:
    if sess is None:
        return dto.SessionOut(authenticated=False, anonymous=False)
    org = db.get(models.Org, sess.org_id)
    user = db.get(models.User, sess.user_id) if sess.user_id else None
    return dto.SessionOut(
        authenticated=True,
        anonymous=user is None,
        org=dto.OrgOut(
            id=org.id, name=org.name, is_trial=org.is_trial, expires_at=org.expires_at
        ) if org else None,
        user=dto.UserOut(id=user.id, email=user.email, role=user.role.value) if user else None,
    )


@router.post("/signup", response_model=dto.SessionOut, status_code=201)
def signup(
    body: dto.SignupRequest,
    response: Response,
    db: DbSession = Depends(get_session),
    existing: models.Session | None = Depends(deps.current_session),
) -> dto.SessionOut:
    """Create an organisation with its first user as owner.

    If the visitor already has an anonymous trial session, their trial org is
    *promoted* rather than abandoned — otherwise the work they just did would
    silently vanish at the moment they decided to sign up, which is the worst
    possible time to lose it.
    """
    promoting = existing is not None and existing.user_id is None
    if promoting:
        org = db.get(models.Org, existing.org_id)
        org.name = body.org_name
        org.is_trial = False
        org.expires_at = None
    else:
        org = models.Org(name=body.org_name)
        db.add(org)
        db.flush()

    taken = db.scalars(
        select(models.User).where(
            models.User.org_id == org.id, models.User.email == body.email
        )
    ).first()
    if taken:
        raise HTTPException(status_code=409, detail="That email already exists in this organisation.")

    user = models.User(
        org_id=org.id,
        email=body.email,
        password_hash=hash_password(body.password),
        role=models.Role.OWNER,
    )
    db.add(user)
    db.flush()

    scope = TenantScope(db, org.id)
    if not promoting:
        seed_org_templates(scope)
    scope.audit("org.created", user_id=user.id, target_type="org", target_id=org.id,
                promoted_from_trial=promoting)

    # Replace the anonymous session with an authenticated one.
    if existing is not None:
        deps.end_session(db, response, existing)
    sess = deps.start_session(db, response, org_id=org.id, user_id=user.id)
    db.commit()
    return _session_out(db, sess)


@router.post("/login", response_model=dto.SessionOut)
def login(
    body: dto.LoginRequest,
    response: Response,
    db: DbSession = Depends(get_session),
) -> dto.SessionOut:
    """Password login.

    Email is unique *per organisation*, not globally, because the same person
    legitimately belongs to more than one tenant. So a login may match several
    accounts; we verify the password against each candidate and, if more than
    one matches, ask which organisation rather than guessing.
    """
    candidates = list(db.scalars(
        select(models.User).where(models.User.email == body.email)
    ))
    if body.org_id is not None:
        candidates = [u for u in candidates if u.org_id == body.org_id]

    matched = [u for u in candidates if verify_password(body.password, u.password_hash)]

    if not matched:
        # Same message whether the email is unknown or the password is wrong:
        # distinguishing them turns the login form into an account-enumeration
        # oracle.
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    if len(matched) > 1:
        orgs = [db.get(models.Org, u.org_id) for u in matched]
        raise HTTPException(
            status_code=409,
            detail={
                "message": "This email belongs to more than one organisation.",
                "choose_org_id": [
                    dto.OrgChoice(id=o.id, name=o.name).model_dump(mode="json")
                    for o in orgs if o
                ],
            },
        )

    user = matched[0]
    # Migrate the hash forward if argon2's defaults have hardened since signup.
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    user.last_login_at = _now()

    sess = deps.start_session(db, response, org_id=user.org_id, user_id=user.id)
    TenantScope(db, user.org_id).audit("user.login", user_id=user.id)
    db.commit()
    return _session_out(db, sess)


@router.post("/trial", response_model=dto.SessionOut, status_code=201)
def start_trial(
    response: Response,
    db: DbSession = Depends(get_session),
    existing: models.Session | None = Depends(deps.current_session),
) -> dto.SessionOut:
    """Begin an anonymous trial.

    The visitor gets a real, expiring organisation. That keeps tenancy to one
    code path — no nullable org_id, no "is this a trial?" branch in every query
    — and a trial is reaped by deleting its org, which cascades.
    """
    if existing is not None:
        return _session_out(db, existing)

    org = models.Org(
        name="Trial",
        is_trial=True,
        expires_at=_now() + timedelta(hours=settings().trial_retention_hours),
    )
    db.add(org)
    db.flush()
    seed_org_templates(TenantScope(db, org.id))
    sess = deps.start_session(db, response, org_id=org.id)
    db.commit()
    return _session_out(db, sess)


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    db: DbSession = Depends(get_session),
    sess: models.Session | None = Depends(deps.current_session),
) -> None:
    if sess is not None:
        deps.end_session(db, response, sess)
        db.commit()


@router.get("/me", response_model=dto.SessionOut)
def me(
    db: DbSession = Depends(get_session),
    sess: models.Session | None = Depends(deps.current_session),
) -> dto.SessionOut:
    """Unauthenticated callers get `authenticated: false` rather than a 401,
    so the front end can render a logged-out view without treating it as an
    error."""
    return _session_out(db, sess)
