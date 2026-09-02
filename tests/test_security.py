"""Security regressions.

Every test here corresponds to a hole that was actually present and exploitable during
development, not a hypothetical. If one of these fails, the vulnerability is back.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from app.api.deps import require_auth
from app.config import Settings
from app.security import (
    MAX_FAILED_LOGINS,
    InsecureConfiguration,
    check_configuration,
    hash_password,
    issue_session,
    read_session,
    seconds_locked_out,
    verify_api_key,
    verify_password,
)
from app.services.ingest import MAX_PIXELS, IngestError, _verify_image
from tests.conftest import TEST_PASSWORD, TEST_SECRET, requires_db

REAL_SECRET = TEST_SECRET
PASSWORD = TEST_PASSWORD


# --------------------------------------------------------------------------------------
# Path traversal on the SPA route. This was a real unauthenticated arbitrary file read:
# GET /../../../../../etc/passwd returned the file with HTTP 200.
# --------------------------------------------------------------------------------------
# Without a built frontend the SPA route is never mounted, so every probe below would
# 404 and these tests would pass while proving nothing. Skip loudly instead.
frontend_built = pytest.mark.skipif(
    not (Path(__file__).resolve().parent.parent / "web" / "dist" / "index.html").is_file(),
    reason="needs a built frontend (npm run build in web/) for the SPA route to exist",
)


@frontend_built
class TestStaticFileTraversal:
    TRAVERSALS = [
        "/../../../../../etc/passwd",
        "/../../../../../../etc/passwd",
        "/../../alembic.ini",
        "/../../pyproject.toml",
        "/../../../app/config.py",
        "/..%2f..%2falembic.ini",
        "/%2e%2e/%2e%2e/alembic.ini",
        "/....//....//alembic.ini",
        "/assets/../../../alembic.ini",
    ]

    @pytest.mark.parametrize("path", TRAVERSALS)
    async def test_never_serves_a_file_outside_the_build_directory(self, client, path):
        response = await client.get(path)
        body = response.text

        # Whatever the routing does with the path, the answer is never file content.
        assert "root:x:0:0" not in body, "served /etc/passwd"
        assert "[alembic]" not in body, "served alembic.ini"
        assert "[project]" not in body, "served pyproject.toml"
        assert "ANTHROPIC_API_KEY" not in body, "served application source"
        if response.status_code == 200:
            assert "<!doctype html>" in body.lower(), "expected the SPA shell"

    async def test_null_byte_does_not_crash_the_route(self, client):
        # resolve() raises ValueError on an embedded null byte; that must not be a 500.
        for path in ("/%00", "/%00x", "/foo%00.js"):
            response = await client.get(path)
            assert response.status_code < 500, f"{path} produced {response.status_code}"

    async def test_the_spa_itself_still_loads(self, client):
        for path in ("/", "/statisztika", "/blokkok"):
            response = await client.get(path)
            assert response.status_code == 200
            assert "<!doctype html>" in response.text.lower()


# --------------------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------------------
class TestAuthentication:
    @pytest.mark.parametrize(
        "method,path",
        [
            ("GET", "/api/receipts"),
            ("GET", "/api/stats/summary"),
            ("GET", "/api/costs/summary"),
            ("GET", "/api/categories"),
            ("GET", "/api/products"),
            ("POST", "/api/receipts"),
        ],
    )
    @requires_db
    async def test_api_refuses_anonymous_callers(self, client, method, path):
        response = await client.request(method, path)
        assert response.status_code == 401

    @requires_db
    async def test_api_key_is_accepted(self, client, app_settings):
        response = await client.get(
            "/api/receipts", headers={"X-API-Key": app_settings.api_key}
        )
        assert response.status_code == 200

    @requires_db
    async def test_wrong_api_key_is_refused(self, client):
        response = await client.get("/api/receipts", headers={"X-API-Key": "nope"})
        assert response.status_code == 401

    @requires_db
    async def test_login_then_use_the_session_cookie(self, client):
        login = await client.post("/api/auth/login", json={"password": PASSWORD})
        assert login.status_code == 200 and login.json()["authenticated"] is True

        # The cookie the client kept is enough on its own.
        assert (await client.get("/api/receipts")).status_code == 200

        await client.post("/api/auth/logout")
        assert (await client.get("/api/receipts")).status_code == 401

    @requires_db
    async def test_wrong_password_is_refused(self, client):
        response = await client.post("/api/auth/login", json={"password": "rossz"})
        assert response.status_code == 401

    async def test_a_forged_cookie_is_rejected(self, app_settings):
        token = issue_session(app_settings)
        assert read_session(app_settings, token) == "owner"
        assert read_session(app_settings, token[:-4] + "AAAA") is None
        assert read_session(app_settings, "not-a-token") is None

    async def test_a_cookie_signed_with_another_key_is_rejected(self, app_settings):
        other = Settings(secret_key="a" * 64)
        assert read_session(app_settings, issue_session(other)) is None

    def test_api_key_comparison_rejects_empties(self):
        assert verify_api_key("abc", "abc") is True
        assert verify_api_key("abc", "xyz") is False
        assert verify_api_key(None, "abc") is False
        assert verify_api_key("abc", None) is False
        # An unconfigured key must not mean "everything matches".
        assert verify_api_key("", "") is False
        assert verify_api_key(None, None) is False

    def test_password_verification(self):
        stored = hash_password(PASSWORD)
        assert verify_password(PASSWORD, stored) is True
        assert verify_password("rossz", stored) is False
        assert verify_password(PASSWORD, None) is False
        assert verify_password(PASSWORD, "not-a-hash") is False


class TestLoginThrottle:
    """The lockout must slow an attacker down without letting one lock the owner out."""

    @requires_db
    async def test_repeated_failures_are_throttled(self, client):
        for _ in range(MAX_FAILED_LOGINS):
            await client.post("/api/auth/login", json={"password": "rossz"})

        blocked = await client.post("/api/auth/login", json={"password": "rossz"})
        assert blocked.status_code == 429
        assert "Retry-After" in blocked.headers

    def test_lockout_is_per_caller_not_global(self):
        """A stranger hammering the login must not lock the owner out of their own app."""
        from app.security import clear_failures, register_failure

        attacker, owner = "203.0.113.9", "192.168.1.50"
        clear_failures(attacker)
        clear_failures(owner)

        for _ in range(MAX_FAILED_LOGINS + 5):
            register_failure(attacker)

        assert seconds_locked_out(attacker) > 0
        assert seconds_locked_out(owner) == 0, "the owner was locked out by someone else"
        clear_failures(attacker)


# --------------------------------------------------------------------------------------
# Configuration that only looks secure
# --------------------------------------------------------------------------------------
class TestConfigurationGuard:
    @pytest.mark.parametrize(
        "secret",
        [
            "change-me-in-production",     # the pydantic default
            "CHANGE_ME_SECRET",            # deploy/docker-compose.yaml
            "dev-secret-not-for-real-use", # docker-compose.dev.yaml and .env.example
            "changeme",
            "hunter2",                     # too short to be a signing key
            "",
        ],
    )
    def test_placeholder_secrets_prevent_startup(self, secret):
        settings = Settings(secret_key=secret, app_password_hash="x", auth_disabled=False)
        with pytest.raises(InsecureConfiguration):
            check_configuration(settings)

    def test_a_real_secret_is_accepted(self):
        check_configuration(
            Settings(secret_key=REAL_SECRET, app_password_hash="x", auth_disabled=False)
        )

    def test_local_development_is_still_allowed(self):
        # AUTH_DISABLED is an explicit, logged choice; it must not be blocked.
        check_configuration(Settings(secret_key="change-me-in-production", auth_disabled=True))


# --------------------------------------------------------------------------------------
# Upload limits
# --------------------------------------------------------------------------------------
class TestUploadLimits:
    @staticmethod
    def png(width: int, height: int, mode: str = "RGB") -> bytes:
        buffer = io.BytesIO()
        Image.new(mode, (width, height)).save(buffer, format="PNG", compress_level=9)
        return buffer.getvalue()

    def test_decompression_bombs_are_rejected(self):
        """A few KB on the wire that would decode to hundreds of MB."""
        for width, height in ((12000, 12000), (20000, 20000)):
            data = self.png(width, height)
            assert len(data) < 2 * 1024 * 1024, "the point is that it is small on the wire"
            with pytest.raises(IngestError):
                _verify_image(data)

    def test_a_palette_bomb_is_rejected_too(self):
        with pytest.raises(IngestError):
            _verify_image(self.png(12000, 12000, mode="P"))

    def test_real_camera_photos_are_accepted(self):
        assert _verify_image(self.png(8000, 6000)) == "PNG"   # a 48 MP phone photo
        assert _verify_image(self.png(900, 1600)) == "PNG"    # an ordinary receipt shot

    def test_the_pixel_ceiling_is_enforced_exactly(self):
        # Just over the line must fail even though PIL itself would allow it.
        over = int(MAX_PIXELS ** 0.5) + 200
        with pytest.raises(IngestError, match="megapixel|too large"):
            _verify_image(self.png(over, over))

    def test_non_images_are_rejected(self):
        with pytest.raises(IngestError):
            _verify_image(b"#!/bin/sh\nrm -rf /\n")
        with pytest.raises(IngestError):
            _verify_image(b"")


class TestAuthDisabled:
    """The development escape hatch must work, and only when asked for."""

    async def test_auth_disabled_allows_anonymous_access(self, tmp_path, sessionmaker_fixture):
        settings = Settings(data_dir=tmp_path, auth_disabled=True, worker_enabled=False)
        assert await require_auth(settings, None, None) == "dev"
