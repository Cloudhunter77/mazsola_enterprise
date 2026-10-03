"""Set a login's password from inside the container, for when nobody can get in.

    python scripts/set_password.py <username>

Once accounts exist, APP_PASSWORD_HASH is no longer read for logging in - it only creates
the first account on a fresh install - so changing it does not reset anything. This does.
It reads the new password without echoing it, so it never reaches your shell history, and
it re-activates the account in case that is why it was locked out.
"""

from __future__ import annotations

import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services.users import normalise_username  # noqa: E402


async def main(username: str) -> None:
    async with SessionLocal() as session:
        user = await session.scalar(
            select(User).where(User.username == normalise_username(username))
        )
        if user is None:
            names = (await session.scalars(select(User.username).order_by(User.username))).all()
            raise SystemExit(f"No login called {username!r}. Logins: {', '.join(names) or '-'}")

        password = getpass.getpass(f"New password for {user.username}: ")
        if not password:
            raise SystemExit("No password given.")
        if password != getpass.getpass("Again: "):
            raise SystemExit("The two entries did not match.")

        user.password_hash = hash_password(password)
        user.active = True
        await session.commit()
        print(f"Password set for {user.username}.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    asyncio.run(main(sys.argv[1]))
