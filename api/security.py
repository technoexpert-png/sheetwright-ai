"""Password hashing and session-cookie signing.

Argon2id for passwords: it is the current recommendation, and `argon2-cffi`
picks sane parameters so we are not inventing a work factor. Sessions are
server-side rows (see db.models.Session); the cookie carries only a *signed*
reference to one, so logout is a real revocation rather than a hope that the
client threw its token away.
"""

from __future__ import annotations

import uuid

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from config import settings

_hasher = PasswordHasher()

# Namespaced salt so a signed session value can never be replayed as some other
# kind of signed token we might add later.
_SESSION_SALT = "sheetwright.session.v1"


def hash_password(raw: str) -> str:
    return _hasher.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    """Constant-time-ish verification. Never raises for a wrong password."""
    try:
        return _hasher.verify(hashed, raw)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(hashed: str) -> bool:
    """True when the stored hash predates the current parameters.

    Called on successful login so hashes migrate forward as argon2 defaults
    harden, instead of everyone staying on whatever was current at signup.
    """
    try:
        return _hasher.check_needs_rehash(hashed)
    except InvalidHashError:
        return True


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings().secret_key, salt=_SESSION_SALT)


def sign_session_id(session_id: uuid.UUID) -> str:
    return _serializer().dumps(str(session_id))


def unsign_session_id(token: str) -> uuid.UUID | None:
    """Return the session id, or None if the cookie is forged or stale.

    The signature carries its own max age as defense in depth; the Session row
    also has `expires_at`, and both are checked. A signature that merely looks
    valid is not enough to be logged in.
    """
    try:
        raw = _serializer().loads(token, max_age=settings().session_days * 86400)
        return uuid.UUID(raw)
    except (BadSignature, SignatureExpired, ValueError):
        return None
