"""Login, logout, and 'am I logged in'."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status

from leltar.api.deps import SettingsDep
from leltar.schemas.api import LoginRequest, SessionInfo
from leltar.security import (
    SESSION_COOKIE,
    clear_failures,
    issue_session,
    read_session,
    register_failure,
    seconds_locked_out,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=SessionInfo)
async def login(
    body: LoginRequest, request: Request, response: Response, settings: SettingsDep
) -> SessionInfo:
    if settings.auth_disabled:
        return SessionInfo(authenticated=True, subject="dev")

    client = request.client.host if request.client else "unknown"

    locked_for = seconds_locked_out(client)
    if locked_for:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed attempts. Try again in {locked_for} seconds.",
            headers={"Retry-After": str(locked_for)},
        )

    if not settings.app_password_hash:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "No password is configured. Set APP_PASSWORD_HASH "
                "(see scripts/hash_password.py)."
            ),
        )

    if not verify_password(body.password, settings.app_password_hash):
        register_failure(client)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong password.")

    clear_failures(client)
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
    home_inventory_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> SessionInfo:
    if settings.auth_disabled:
        return SessionInfo(authenticated=True, subject="dev")
    subject = read_session(settings, home_inventory_session)
    return SessionInfo(authenticated=bool(subject), subject=subject)
