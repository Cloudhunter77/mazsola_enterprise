"""Login, logout, and 'am I logged in'."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Response, status

from app.api.deps import SettingsDep
from app.schemas.api import LoginRequest, SessionInfo
from app.security import SESSION_COOKIE, issue_session, read_session, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=SessionInfo)
async def login(body: LoginRequest, response: Response, settings: SettingsDep) -> SessionInfo:
    if settings.auth_disabled:
        return SessionInfo(authenticated=True, subject="dev")

    if not settings.app_password_hash:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No password is configured. Set APP_PASSWORD_HASH (see scripts/hash_password.py).",
        )

    if not verify_password(body.password, settings.app_password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong password.")

    response.set_cookie(
        SESSION_COOKIE,
        issue_session(settings),
        max_age=settings.session_max_age_days * 24 * 3600,
        httponly=True,
        samesite="lax",
        # Not `secure`: a home NAS is usually reached over plain HTTP inside the VPN, and a
        # secure cookie would simply never be sent back.
    )
    return SessionInfo(authenticated=True, subject="owner")


@router.post("/logout", response_model=SessionInfo)
async def logout(response: Response) -> SessionInfo:
    response.delete_cookie(SESSION_COOKIE)
    return SessionInfo(authenticated=False)


@router.get("/me", response_model=SessionInfo)
async def me(
    settings: SettingsDep,
    mazsola_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> SessionInfo:
    if settings.auth_disabled:
        return SessionInfo(authenticated=True, subject="dev")
    subject = read_session(settings, mazsola_session)
    return SessionInfo(authenticated=bool(subject), subject=subject)
