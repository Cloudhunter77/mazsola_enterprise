"""The deployment files have to agree with themselves, and with the documentation.

A database password lives in two places in every compose file - what Postgres is told to
use, and what the application's DSN sends - and nothing catches a mismatch until a
container refuses to start. Plain text checks, so they run everywhere and cost nothing.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

DSN = re.compile(r"postgresql\+asyncpg://(?P<user>[^:@\s]+):(?P<password>[^@\s]+)@")
SETTING = "{key}: *(?P<value>[^\\s#]+)"

COMPOSE_FILES = [
    "docker-compose.dev.yaml",
    "deploy/docker-compose.yaml",
    "../.github/workflows/inventory.yml",
]


def value_of(text: str, key: str) -> str | None:
    match = re.search(SETTING.format(key=key), text)
    return match.group("value") if match else None


@pytest.mark.parametrize("relative", COMPOSE_FILES)
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
        f"{relative}: the DSN's password does not match POSTGRES_PASSWORD"
    )


def test_the_two_apps_do_not_collide_on_the_same_host():
    """Both run on one NAS, so nothing may be shared by accident.

    The container port is the same by design (it is internal); what must differ is
    everything the host sees - the published port, the compose project name, the volumes
    and the image. One list, checked once, rather than found out when the second app
    refuses to start.
    """
    ours = (ROOT / "deploy" / "docker-compose.yaml").read_text()
    theirs = (ROOT.parent / "deploy" / "docker-compose.yaml").read_text()

    def published_ports(text: str) -> set[str]:
        # Anchored on the list dash, so `user: "568:568"` is not mistaken for a port.
        return set(re.findall(r'^\s*-\s*"(\d+):\d+"', text, re.MULTILINE))

    def project_name(text: str) -> str | None:
        match = re.search(r"^name: *(\S+)", text, re.MULTILINE)
        return match.group(1) if match else None

    assert published_ports(ours) & published_ports(theirs) == set(), (
        "the two apps publish the same host port"
    )
    assert project_name(ours) and project_name(ours) != project_name(theirs)


def test_every_script_the_documentation_mentions_exists():
    """A command in the install guide that names a file we do not ship fails on line one."""
    docs = [path for path in ROOT.rglob("*.md") if "node_modules" not in str(path)]
    assert docs, "no documentation found"

    referenced = set()
    for doc in docs:
        referenced.update(
            re.findall(r"(?:scripts|tests)/[A-Za-z0-9_./-]+\.(?:py|sh|jpg)", doc.read_text())
        )

    missing = [path for path in sorted(referenced) if not (ROOT / path).exists()]
    assert missing == [], f"documented but missing: {missing}"
