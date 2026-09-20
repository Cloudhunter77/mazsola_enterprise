"""Shared FastAPI dependencies."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, Query, status
from pydantic import BeforeValidator
from sqlalchemy.ext.asyncio import AsyncSession

from leltar.config import Settings, get_settings
from leltar.db import get_session
from leltar.security import SESSION_COOKIE, read_session, verify_api_key

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _blank_as_none(value: object) -> object:
    """Treat an empty query parameter as one that was not given.

    `?place_id=` is what a client sends when its variable is empty - an iOS Shortcut with
    no room selected, or a form that submitted its placeholder option. Without this it is
    a 422 about UUID lengths, which is a confusing way to say "you did not pick a room".
    """
    return None if value == "" else value


# The `Query()` marker belongs inside the Annotated rather than in the argument default:
# passing Query(...) as the default instead makes FastAPI re-validate the raw string
# against the bare annotation, and the validator above is then quietly ignored.
OptionalUUID = Annotated[
    uuid.UUID | None, BeforeValidator(_blank_as_none), Query()
]



async def require_auth(
    settings: SettingsDep,
    home_inventory_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    x_api_key: Annotated[str | None, Header()] = None,
) -> str:
    """Accept either the browser session cookie or the shortcut's API key."""
    if settings.auth_disabled:
        return "dev"

    if verify_api_key(x_api_key, settings.api_key):
        return "api-key"

    subject = read_session(settings, home_inventory_session)
    if subject:
        return subject

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated.",
        headers={"WWW-Authenticate": "Cookie"},
    )


AuthDep = Annotated[str, Depends(require_auth)]
