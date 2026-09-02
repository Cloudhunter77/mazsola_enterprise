"""The deployment files have to agree with themselves.

A database password lives in two places in every compose file - what Postgres is told to
use, and what the application's DSN sends - and nothing catches a mismatch until a
container refuses to start. That is exactly what happened when the project was renamed:
a rule rewrote POSTGRES_PASSWORD but not the password inside the DSN, and CI failed with
`password authentication failed`. Local tests could not catch it because a development
Postgres runs on trust authentication and accepts any password at all.

These are plain text checks, so they run everywhere and cost nothing.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

DSN = re.compile(r"postgresql\+asyncpg://(?P<user>[^:@\s]+):(?P<password>[^@\s]+)@")
SETTING = "{key}: *(?P<value>[^\\s#]+)"


def value_of(text: str, key: str) -> str | None:
    match = re.search(SETTING.format(key=key), text)
    return match.group("value") if match else None


@pytest.mark.parametrize(
    "relative",
    [".github/workflows/build.yml", "docker-compose.dev.yaml", "deploy/docker-compose.yaml"],
)
def test_the_dsn_matches_what_postgres_is_configured_with(relative: str):
    text = (ROOT / relative).read_text()

    dsn = DSN.search(text)
    assert dsn, f"{relative} has no asyncpg DSN to check"

    user = value_of(text, "POSTGRES_USER")
    password = value_of(text, "POSTGRES_PASSWORD")
    database = value_of(text, "POSTGRES_DB")
    assert user and password and database, f"{relative} does not configure Postgres"

    assert dsn.group("user") == user, (
        f"{relative}: the DSN connects as {dsn.group('user')!r} but Postgres is created "
        f"with POSTGRES_USER={user!r}"
    )
    assert dsn.group("password") == password, (
        f"{relative}: the DSN sends a different password than POSTGRES_PASSWORD - the "
        f"container will refuse every connection"
    )
    assert text.count(f"/{database}") >= 1, (
        f"{relative}: nothing connects to the database named {database!r}"
    )


def test_the_compose_file_and_the_image_the_workflow_publishes_agree():
    """A compose file pointing at an image name CI never publishes cannot be installed."""
    workflow = (ROOT / ".github/workflows/build.yml").read_text()
    compose = (ROOT / "deploy/docker-compose.yaml").read_text()

    published = re.search(r"images: *ghcr\.io/\$\{\{[^}]+\}\}/(?P<name>[\w.-]+)", workflow)
    referenced = re.search(r"image: *ghcr\.io/[\w.-]+/(?P<name>[\w.-]+):", compose)
    assert published and referenced, "could not find the image name in both files"
    assert published.group("name") == referenced.group("name"), (
        f"CI publishes {published.group('name')!r} but the compose file installs "
        f"{referenced.group('name')!r}"
    )
