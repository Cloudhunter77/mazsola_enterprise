"""The version panel, which exists so an update can be verified without a shell.

Pulling the image is a menu item on the TrueNAS Apps screen. What used to need SSH was
proving the pull took - comparing image digests, reading container logs. These fields make
that a page you look at instead.
"""

from __future__ import annotations

import os
from unittest import mock

from app.version import app_version, build_info, schema_revision
from tests.conftest import requires_db


class TestTheBuildStamp:
    def test_the_expected_schema_revision_is_readable(self):
        """Read from the migration scripts, so it says what this code wants."""
        revision = schema_revision()
        assert revision and len(revision) >= 8

    def test_an_unstamped_build_says_so_rather_than_guessing(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            assert build_info() == {"commit": None, "built_at": None, "image": None}

    def test_the_stamp_is_read_from_the_environment(self):
        with mock.patch.dict(os.environ, {"BUILD_COMMIT": "abc123", "BUILD_TIME": "2026-09-06"}):
            info = build_info()
            assert info["commit"] == "abc123"
            assert info["built_at"] == "2026-09-06"

    def test_a_version_is_always_reported(self):
        assert app_version()


@requires_db
class TestTheEndpoint:
    async def test_it_reports_what_the_code_expects(self, auth_client):
        body = (await auth_client.get("/api/system")).json()
        assert body["schema"]["expected"], "the revision this image wants"

    async def test_a_database_with_no_alembic_table_does_not_break_the_page(self, auth_client):
        """The test schema is built by create_all, so `alembic_version` does not exist.

        That failing query aborts the PostgreSQL transaction, and swallowing the error
        without rolling back used to poison every later query in the same request - the
        receipt counts below it included. This is the regression test for that.
        """
        response = await auth_client.get("/api/system")
        assert response.status_code == 200

        body = response.json()
        assert body["schema"]["applied"] is None
        assert body["schema"]["up_to_date"] is False
        assert body["receipts"]["total"] == 0, "the query after the failed one still ran"

    async def test_it_reports_the_engine_actually_configured(self, auth_client, app_settings):
        body = (await auth_client.get("/api/system")).json()
        assert body["extractor"] == app_settings.extractor

    async def test_it_counts_receipts_by_state(self, auth_client, receipt_photo):
        await auth_client.post(
            "/api/receipts", files={"file": ("blokk.jpg", receipt_photo, "image/jpeg")}
        )
        body = (await auth_client.get("/api/system")).json()

        assert body["receipts"]["total"] == 1
        assert body["receipts"]["pending"] == 1

    async def test_it_needs_a_login(self, client):
        assert (await client.get("/api/system")).status_code == 401

    async def test_health_carries_the_version_for_a_one_line_check(self, client):
        """/health stays unauthenticated, so a curl can still answer "which build?"."""
        body = (await client.get("/health")).json()
        assert body["version"]
        assert "commit" in body
