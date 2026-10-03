"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.security import SESSION_COOKIE, read_session, verify_api_key
from app.services.users import (
    Principal,
    ensure_owner,
    principal_for,
    user_for_session,
)

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def require_auth(
    settings: SettingsDep,
    session: SessionDep,
    receipt_tracker_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    x_api_key: Annotated[str | None, Header()] = None,
) -> Principal:
    """Accept either a person's session cookie or the shortcut's API key.

    The API key acts as the owner - the first login - since the shortcut was set up for the
    one person the app had when it was made. Everyone else signs in with their own account.
    """
    if settings.auth_disabled:
        owner = await ensure_owner(session, settings)
        return principal_for(owner, "dev") if owner else Principal(None, "dev", True, "dev")

    if verify_api_key(x_api_key, settings.api_key):
        owner = await ensure_owner(session, settings)
        if owner is None:
            return Principal(None, "API", False, "api-key")
        return principal_for(owner, "api-key")

    user = await user_for_session(session, read_session(settings, receipt_tracker_session))
    if user is not None:
        return principal_for(user, "session")

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated.",
        headers={"WWW-Authenticate": "Cookie"},
    )


AuthDep = Annotated[Principal, Depends(require_auth)]


async def require_admin(principal: AuthDep) -> Principal:
    if not principal.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admins only.")
    return principal


AdminDep = Annotated[Principal, Depends(require_admin)]
