"""Who is logged in, and the household's logins.

The first login is the one that already existed: the password in APP_PASSWORD_HASH. It is
turned into a real account - an admin - the first time anything needs one, so upgrading
changes nothing about how you get in. After that, accounts live in the database and the
environment variable is only ever read again to bootstrap a fresh install.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import User
from app.security import hash_password, verify_password

log = logging.getLogger(__name__)

# Verified against when the username does not exist, so a wrong username costs the same
# argon2 time as a wrong password and the response time does not say which logins exist.
_DUMMY_HASH: str | None = None


def _dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("this password does not belong to anyone")
    return _DUMMY_HASH


@dataclass(frozen=True, slots=True)
class Principal:
    """The person a request acts for."""

    user_id: uuid.UUID | None
    display_name: str
    is_admin: bool
    # "session", "api-key" or "dev" - how they got in, for the record.
    via: str


def normalise_username(username: str) -> str:
    return username.strip().lower()


def principal_for(user: User, via: str) -> Principal:
    return Principal(user.id, user.display_name, user.is_admin, via)


async def ensure_owner(session: AsyncSession, settings: Settings) -> User | None:
    """The original single login, as an account. Created once, the first time it is needed."""
    owner = await owner_of(session)
    if owner is not None:
        return owner
    if await session.scalar(select(func.count(User.id))):
        # Accounts exist but none is an active admin; do not invent one behind anyone's back.
        return None
    if not settings.app_password_hash:
        return None

    username = normalise_username(settings.app_username or "admin") or "admin"
    owner = User(
        username=username,
        display_name=(settings.app_display_name or username).strip()[:80] or username,
        password_hash=settings.app_password_hash,
        is_admin=True,
    )
    session.add(owner)
    await session.commit()
    log.info("created the first login, %r, from APP_PASSWORD_HASH", username)
    return owner


async def owner_of(session: AsyncSession) -> User | None:
    """The longest-standing active admin: who the phone shortcut's API key acts as."""
    return await session.scalar(
        select(User)
        .where(User.is_admin.is_(True))
        .where(User.active.is_(True))
        .order_by(User.created_at, User.id)
        .limit(1)
    )


async def authenticate(
    session: AsyncSession, settings: Settings, username: str | None, password: str
) -> User | None:
    """The account these credentials open, or None. Never says which half was wrong.

    No username means the original owner: the login form before there were several people
    sent only a password, and an app saved to a phone's home screen keeps sending it until
    it updates.
    """
    owner = await ensure_owner(session, settings)
    if username is None or not username.strip():
        user = owner
    else:
        user = await session.scalar(
            select(User).where(User.username == normalise_username(username))
        )

    if user is None or not user.active:
        verify_password(password, _dummy_hash())
        return None
    return user if verify_password(password, user.password_hash) else None


async def user_for_session(session: AsyncSession, subject: str | None) -> User | None:
    """The account a session cookie names, if it still exists and may still log in."""
    if not subject:
        return None
    if subject == "owner":
        # A cookie issued before there were accounts. It proved the owner's password then,
        # so it stands for the owner now, rather than logging everyone out on upgrade.
        return await owner_of(session)
    try:
        user_id = uuid.UUID(subject)
    except ValueError:
        return None
    user = await session.get(User, user_id)
    return user if user is not None and user.active else None
