"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.security import SESSION_COOKIE, read_session, verify_api_key

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def require_auth(
    settings: SettingsDep,
    mazsola_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    x_api_key: Annotated[str | None, Header()] = None,
) -> str:
    """Accept either the browser session cookie or the shortcut's API key."""
    if settings.auth_disabled:
        return "dev"

    if verify_api_key(x_api_key, settings.api_key):
        return "api-key"

    subject = read_session(settings, mazsola_session)
    if subject:
        return subject

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated.",
        headers={"WWW-Authenticate": "Cookie"},
    )


AuthDep = Annotated[str, Depends(require_auth)]
