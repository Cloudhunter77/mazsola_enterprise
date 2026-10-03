"""Login, logout, and 'who am I'."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.deps import SessionDep, SettingsDep, require_auth
from app.schemas.api import LoginRequest, SessionInfo
from app.security import (
    SESSION_COOKIE,
    clear_failures,
    issue_session,
    register_failure,
    seconds_locked_out,
)
from app.services.users import authenticate, ensure_owner

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=SessionInfo)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    settings: SettingsDep,
    session: SessionDep,
) -> SessionInfo:
    if settings.auth_disabled:
        owner = await ensure_owner(session, settings)
        return SessionInfo.for_user(owner) if owner else SessionInfo(authenticated=True)

    client = request.client.host if request.client else "unknown"

    locked_for = seconds_locked_out(client)
    if locked_for:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed attempts. Try again in {locked_for} seconds.",
            headers={"Retry-After": str(locked_for)},
        )

    user = await authenticate(session, settings, body.username, body.password)
    if user is None:
        if await ensure_owner(session, settings) is None and not settings.app_password_hash:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "No login is configured. Set APP_PASSWORD_HASH "
                    "(see scripts/hash_password.py)."
                ),
            )
        register_failure(client)
        # One message for both halves, so the reply does not say which logins exist.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong username or password."
        )

    clear_failures(client)
    response.set_cookie(
        SESSION_COOKIE,
        issue_session(settings, str(user.id)),
        max_age=settings.session_max_age_days * 24 * 3600,
        httponly=True,
        samesite="lax",
        # Not `secure`: a home NAS is usually reached over plain HTTP inside the VPN, and a
        # secure cookie would simply never be sent back.
    )
    return SessionInfo.for_user(user)


@router.post("/logout", response_model=SessionInfo)
async def logout(response: Response) -> SessionInfo:
    response.delete_cookie(SESSION_COOKIE)
    return SessionInfo(authenticated=False)


@router.get("/me", response_model=SessionInfo)
async def me(request: Request, settings: SettingsDep, session: SessionDep) -> SessionInfo:
    """Who is logged in - or a plain "nobody", never a 401, so the app can show its login."""
    try:
        principal = await require_auth(
            settings,
            session,
            request.cookies.get(SESSION_COOKIE),
            request.headers.get("x-api-key"),
        )
    except HTTPException:
        return SessionInfo(authenticated=False)
    return SessionInfo(
        authenticated=True,
        subject=str(principal.user_id) if principal.user_id else principal.via,
        user_id=principal.user_id,
        display_name=principal.display_name,
        is_admin=principal.is_admin,
    )
