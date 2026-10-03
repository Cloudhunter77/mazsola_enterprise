"""The household's logins.

Everyone can see who is in the household - the "who paid" buttons need the names - and
change their own name and password. Adding people, resetting someone else's password and
switching an account off are for admins. One rule holds throughout: the last active admin
cannot stop being one, or nobody could add a login again without a shell on the NAS.
"""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import AdminDep, AuthDep, SessionDep
from app.models import User
from app.schemas.api import UserCreate, UserOut, UserUpdate
from app.security import hash_password, verify_password
from app.services.users import normalise_username

router = APIRouter(prefix="/api/users", tags=["users"])

USERNAME = re.compile(r"^[a-z0-9._-]{2,60}$")
MIN_PASSWORD = 8


def _out(user: User, me: uuid.UUID | None) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        is_admin=user.is_admin,
        active=user.active,
        is_me=user.id == me,
    )


def _check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise HTTPException(
            status_code=422, detail=f"A jelszó legalább {MIN_PASSWORD} karakter legyen."
        )


async def _username_free(session, username: str, except_id: uuid.UUID | None = None) -> str:
    username = normalise_username(username)
    if not USERNAME.match(username):
        raise HTTPException(
            status_code=422,
            detail="A felhasználónév 2–60 karakter: kisbetű, szám, pont, kötőjel, aláhúzás.",
        )
    taken = await session.scalar(select(User.id).where(User.username == username))
    if taken is not None and taken != except_id:
        raise HTTPException(status_code=409, detail="Ez a felhasználónév már foglalt.")
    return username


@router.get("", response_model=list[UserOut])
async def list_users(principal: AuthDep, session: SessionDep) -> list[UserOut]:
    users = (await session.scalars(select(User).order_by(User.created_at, User.id))).all()
    return [_out(user, principal.user_id) for user in users]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(principal: AdminDep, session: SessionDep, body: UserCreate) -> UserOut:
    username = await _username_free(session, body.username)
    _check_password(body.password)
    user = User(
        username=username,
        display_name=body.display_name.strip(),
        password_hash=hash_password(body.password),
        is_admin=body.is_admin,
    )
    session.add(user)
    await session.commit()
    return _out(user, principal.user_id)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    principal: AuthDep, session: SessionDep, user_id: uuid.UUID, body: UserUpdate
) -> UserOut:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="No such user.")

    is_self = user.id == principal.user_id
    if not is_self and not principal.is_admin:
        raise HTTPException(status_code=403, detail="Csak a saját adataidat módosíthatod.")

    if body.display_name is not None:
        user.display_name = body.display_name.strip()
    if body.username is not None:
        user.username = await _username_free(session, body.username, except_id=user.id)

    if body.password is not None:
        _check_password(body.password)
        # Your own password needs the current one: a phone left unlocked should not be
        # enough to take the account over. An admin resetting someone who forgot theirs
        # cannot know it, and does not need to.
        if is_self and not verify_password(body.current_password or "", user.password_hash):
            raise HTTPException(status_code=403, detail="A jelenlegi jelszó nem stimmel.")
        user.password_hash = hash_password(body.password)

    if body.is_admin is not None or body.active is not None:
        if not principal.is_admin:
            raise HTTPException(status_code=403, detail="Admins only.")
        if is_self and body.active is False:
            raise HTTPException(status_code=422, detail="Saját magadat nem kapcsolhatod ki.")
        losing_admin = user.is_admin and user.active and (
            body.is_admin is False or body.active is False
        )
        if losing_admin and await _active_admins(session) <= 1:
            raise HTTPException(
                status_code=422, detail="Legalább egy aktív adminnak maradnia kell."
            )
        if body.is_admin is not None:
            user.is_admin = body.is_admin
        if body.active is not None:
            user.active = body.active

    await session.commit()
    return _out(user, principal.user_id)


async def _active_admins(session) -> int:
    return await session.scalar(
        select(func.count(User.id)).where(User.is_admin.is_(True)).where(User.active.is_(True))
    ) or 0
