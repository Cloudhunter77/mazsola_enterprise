"""Single-user authentication.

The app sits behind your VPN, so this is a lock on an inside door rather than the front
gate: one password, one long-lived signed cookie, plus a static key for the phone shortcut.
"""

from __future__ import annotations

import hmac
import logging
import time

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import Settings

log = logging.getLogger(__name__)

SESSION_COOKIE = "receipt_tracker_session"
DEFAULT_SECRET = "change-me-in-production"

# Every placeholder this repository ships. Checking only the pydantic default would miss
# the one people actually leave in place - the value printed in deploy/docker-compose.yaml.
PLACEHOLDER_SECRETS = frozenset({
    DEFAULT_SECRET,
    "change_me_secret",
    "dev-secret-not-for-real-use",
    "secret",
    "changeme",
})

# `openssl rand -hex 32`, as the deployment guide instructs, gives 64 characters. Anything
# much shorter is a typed-in password being used as a signing key.
MIN_SECRET_LENGTH = 32

# Failed-login throttle, keyed by caller address. argon2 already makes each attempt slow;
# this stops an unattended script from grinding away for hours. Keyed per caller rather
# than globally on purpose - a single shared counter would let any stranger who can reach
# the login page keep the owner permanently locked out.
MAX_FAILED_LOGINS = 10
LOCKOUT_SECONDS = 300
MAX_TRACKED_CLIENTS = 1024

_hasher = PasswordHasher()
_failures: dict[str, tuple[int, float]] = {}


class InsecureConfiguration(RuntimeError):
    """The app is configured in a way that would not actually protect anything."""


def check_configuration(settings: Settings) -> None:
    """Refuse to start in a configuration that only looks secure.

    The default signing key is published in this repository, so anyone who can reach the
    app could mint a valid session cookie with it. That is a silent failure - everything
    appears to work - which is exactly the kind worth turning into a loud one.
    """
    if settings.auth_disabled:
        return

    secret = (settings.secret_key or "").strip()
    normalised = secret.lower()
    looks_like_placeholder = (
        normalised in PLACEHOLDER_SECRETS
        or "change_me" in normalised
        or "change-me" in normalised
        or normalised.startswith("dev-secret")
    )

    if not secret or looks_like_placeholder or len(secret) < MIN_SECRET_LENGTH:
        reason = (
            "is still a placeholder from the repository"
            if looks_like_placeholder or not secret
            else f"is only {len(secret)} characters"
        )
        raise InsecureConfiguration(
            f"SECRET_KEY {reason}, so session cookies could be forged by anyone who has "
            "read this repository. Generate one with `openssl rand -hex 32`, or set "
            "AUTH_DISABLED=true for local development."
        )

    if not settings.app_password_hash and not settings.api_key:
        log.warning(
            "Neither APP_PASSWORD_HASH nor API_KEY is set: nobody can log in. "
            "See scripts/hash_password.py."
        )


def register_failure(client: str) -> None:
    count, _ = _failures.get(client, (0, 0.0))
    _failures[client] = (count + 1, time.monotonic())
    # The map is keyed by caller, so bound it rather than let it grow without limit.
    if len(_failures) > MAX_TRACKED_CLIENTS:
        oldest = min(_failures, key=lambda key: _failures[key][1])
        _failures.pop(oldest, None)


def clear_failures(client: str) -> None:
    _failures.pop(client, None)


def seconds_locked_out(client: str) -> int:
    """How long this caller must wait, or 0 if they may try now."""
    count, last = _failures.get(client, (0, 0.0))
    if count < MAX_FAILED_LOGINS:
        return 0
    remaining = LOCKOUT_SECONDS - (time.monotonic() - last)
    if remaining <= 0:
        clear_failures(client)
        return 0
    return int(remaining) + 1


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
    return URLSafeTimedSerializer(settings.secret_key, salt="receipt-tracker-session")


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
