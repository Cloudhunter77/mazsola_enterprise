"""Several logins in one household.

What matters most here is what must not change on upgrade: the password that already
worked keeps working, a phone that was logged in stays logged in, and the shortcut's key
keeps uploading. After that, the rules that keep a household from locking itself out.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import User
from app.security import SESSION_COOKIE, issue_session
from tests.conftest import TEST_API_KEY, TEST_PASSWORD, requires_db

pytestmark = requires_db

PETRA_PASSWORD = "petra-jelszava-123"


async def login(client, password: str, username: str | None = None):
    body = {"password": password} if username is None else {
        "username": username, "password": password
    }
    return await client.post("/api/auth/login", json=body)


async def add_petra(client, **extra):
    """As the owner, through the API key: create a second login."""
    return await client.post(
        "/api/users",
        json={"username": "Petra", "display_name": "Petra", "password": PETRA_PASSWORD, **extra},
        headers={"X-API-Key": TEST_API_KEY},
    )


class TestUpgradingFromOneLogin:
    async def test_the_old_password_still_logs_in_without_a_username(self, client):
        response = await login(client, TEST_PASSWORD)
        assert response.status_code == 200
        assert response.json()["is_admin"] is True

    async def test_it_became_an_admin_account_called_admin(self, client, session):
        await login(client, TEST_PASSWORD)
        owner = await session.scalar(select(User))
        assert (owner.username, owner.is_admin) == ("admin", True)

    async def test_a_phone_logged_in_before_the_upgrade_stays_logged_in(
        self, client, app_settings
    ):
        """The old cookie said "owner"; it proved the owner's password then."""
        await login(client, TEST_PASSWORD)  # creates the account
        client.cookies.clear()
        client.cookies.set(SESSION_COOKIE, issue_session(app_settings, "owner"))
        me = (await client.get("/api/auth/me")).json()
        assert me["authenticated"] and me["is_admin"]

    async def test_the_shortcut_key_still_uploads_as_the_owner(self, auth_client):
        me = (await auth_client.get("/api/auth/me")).json()
        assert me["authenticated"] and me["display_name"] == "admin"


class TestLoggingIn:
    async def test_a_second_person_logs_in_with_their_own_name(self, client):
        assert (await add_petra(client)).status_code == 201
        response = await login(client, PETRA_PASSWORD, "petra")
        assert response.status_code == 200
        assert response.json()["display_name"] == "Petra"
        assert response.json()["is_admin"] is False

    async def test_the_username_is_not_case_sensitive(self, client):
        await add_petra(client)
        assert (await login(client, PETRA_PASSWORD, " PETRA ")).status_code == 200

    async def test_a_wrong_name_and_a_wrong_password_look_the_same(self, client):
        """The reply must not say which logins exist."""
        await add_petra(client)
        wrong_name = await login(client, PETRA_PASSWORD, "nobody")
        wrong_password = await login(client, "rossz-jelszo", "petra")
        assert wrong_name.status_code == wrong_password.status_code == 401
        assert wrong_name.json() == wrong_password.json()

    async def test_one_persons_password_does_not_open_anothers_account(self, client):
        await add_petra(client)
        assert (await login(client, PETRA_PASSWORD, "admin")).status_code == 401


class TestManagingLogins:
    async def test_only_an_admin_adds_people(self, client):
        await add_petra(client)
        await login(client, PETRA_PASSWORD, "petra")
        response = await client.post("/api/users", json={
            "username": "harmadik", "display_name": "X", "password": "valami-hosszu",
        })
        assert response.status_code == 403

    async def test_everyone_sees_the_household(self, client):
        await add_petra(client)
        await login(client, PETRA_PASSWORD, "petra")
        users = (await client.get("/api/users")).json()
        assert {u["display_name"] for u in users} == {"admin", "Petra"}
        assert [u["is_me"] for u in users if u["display_name"] == "Petra"] == [True]

    async def test_changing_your_own_password_needs_the_current_one(self, client):
        petra = (await add_petra(client)).json()
        await login(client, PETRA_PASSWORD, "petra")

        refused = await client.patch(
            f"/api/users/{petra['id']}", json={"password": "uj-jelszo-123"}
        )
        assert refused.status_code == 403
        accepted = await client.patch(f"/api/users/{petra['id']}", json={
            "password": "uj-jelszo-123", "current_password": PETRA_PASSWORD,
        })
        assert accepted.status_code == 200
        assert (await login(client, "uj-jelszo-123", "petra")).status_code == 200

    async def test_an_admin_resets_a_forgotten_password(self, client):
        petra = (await add_petra(client)).json()
        await login(client, TEST_PASSWORD)
        response = await client.patch(
            f"/api/users/{petra['id']}", json={"password": "uj-jelszo-123"}
        )
        assert response.status_code == 200
        assert (await login(client, "uj-jelszo-123", "petra")).status_code == 200

    async def test_you_cannot_edit_someone_else_unless_admin(self, client, session):
        await add_petra(client)
        await login(client, PETRA_PASSWORD, "petra")
        owner = await session.scalar(select(User).where(User.username == "admin"))
        response = await client.patch(f"/api/users/{owner.id}", json={"display_name": "x"})
        assert response.status_code == 403

    async def test_the_last_admin_cannot_stop_being_one(self, client, session):
        await login(client, TEST_PASSWORD)
        owner = await session.scalar(select(User))
        response = await client.patch(f"/api/users/{owner.id}", json={"is_admin": False})
        assert response.status_code == 422

    async def test_a_switched_off_login_is_out_at_once(self, client):
        """Not only at the next login: the cookie already in their browser stops working."""
        petra = (await add_petra(client)).json()
        await login(client, PETRA_PASSWORD, "petra")
        petra_cookie = client.cookies.get(SESSION_COOKIE)

        await client.patch(
            f"/api/users/{petra['id']}", json={"active": False},
            headers={"X-API-Key": TEST_API_KEY},
        )
        client.cookies.clear()
        client.cookies.set(SESSION_COOKIE, petra_cookie)
        assert (await client.get("/api/receipts")).status_code == 401
        assert (await login(client, PETRA_PASSWORD, "petra")).status_code == 401

    async def test_names_and_passwords_are_checked(self, client):
        await add_petra(client)
        assert (await add_petra(client)).status_code == 409  # taken
        bad_name = await client.post("/api/users", json={
            "username": "petra kovács", "display_name": "P", "password": "valami-hosszu",
        }, headers={"X-API-Key": TEST_API_KEY})
        assert bad_name.status_code == 422
        short = await client.post("/api/users", json={
            "username": "kati", "display_name": "Kati", "password": "rovid",
        }, headers={"X-API-Key": TEST_API_KEY})
        assert short.status_code == 422
