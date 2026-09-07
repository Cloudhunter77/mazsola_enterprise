"""Which build is actually running.

This exists so "did the update take?" can be answered by looking at the app rather than by
opening a shell on the NAS and comparing image digests. The build stamp is baked in by the
Dockerfile from arguments CI supplies; running from a source checkout it is simply absent,
which is itself the honest answer.
"""

from __future__ import annotations

import os
from importlib import metadata

FALLBACK_VERSION = "0.0.0+source"


def app_version() -> str:
    """The package version, or a marker that this is an unpackaged checkout."""
    try:
        return metadata.version("receipt-tracker")
    except metadata.PackageNotFoundError:
        return FALLBACK_VERSION


def build_info() -> dict[str, str | None]:
    """Commit and build time, as stamped into the image. None when running from source."""
    return {
        "commit": os.environ.get("BUILD_COMMIT") or None,
        "built_at": os.environ.get("BUILD_TIME") or None,
        "image": os.environ.get("BUILD_IMAGE") or None,
    }


def schema_revision() -> str | None:
    """The Alembic revision this code expects - not necessarily the one applied.

    Read from the migration scripts rather than the database, so it answers "what does this
    image want" and can be compared against what the database actually has.
    """
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    root = Path(__file__).resolve().parent.parent
    try:
        config = Config(str(root / "alembic.ini"))
        config.set_main_option("script_location", str(root / "app" / "migrations"))
        return ScriptDirectory.from_config(config).get_current_head()
    except Exception:  # noqa: BLE001 - a version panel must never be the thing that 500s
        return None
