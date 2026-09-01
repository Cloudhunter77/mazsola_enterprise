"""Single-user authentication.

The app sits behind your VPN, so this is a lock on an inside door rather than the front
gate: one password, one long-lived signed cookie, plus a static key for the phone shortcut.
"""

from __future__ import annotations

import hmac
import logging

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import Settings

log = logging.getLogger(__name__)

SESSION_COOKIE = "mazsola_session"
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False
    try:
        return _hasher.verify(stored_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def verify_api_key(provided: str | None, expected: str | None) -> bool:
    """Constant-time comparison, so a wrong key leaks nothing through timing."""
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided, expected)


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt="mazsola-session")


def issue_session(settings: Settings, subject: str = "owner") -> str:
    return _serializer(settings).dumps({"sub": subject})


def read_session(settings: Settings, token: str | None) -> str | None:
    """Return the session subject, or None if the cookie is missing, forged or expired."""
    if not token:
        return None
    try:
        data = _serializer(settings).loads(
            token, max_age=settings.session_max_age_days * 24 * 3600
        )
    except SignatureExpired:
        return None
    except BadSignature:
        log.warning("rejected a session cookie with a bad signature")
        return None
    return data.get("sub")
