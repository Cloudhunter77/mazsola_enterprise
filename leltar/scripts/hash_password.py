"""Turn a password into the Argon2 hash that APP_PASSWORD_HASH expects.

    python scripts/hash_password.py

Reads the password without echoing it, and prints only the hash - so the password
itself never lands in your shell history or in the TrueNAS app configuration.
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from leltar.security import hash_password  # noqa: E402


def main() -> None:
    password = getpass.getpass("Password: ")
    if not password:
        raise SystemExit("No password given.")
    if password != getpass.getpass("Again: "):
        raise SystemExit("The two entries did not match.")
    if len(password) < 8:
        print("Warning: shorter than 8 characters.", file=sys.stderr)

    digest = hash_password(password)

    # An Argon2 hash contains `$` separators, and Docker Compose treats `$` as the start
    # of a variable substitution - so pasting the raw hash into a compose file silently
    # corrupts it and every login then fails for no visible reason. Doubling each `$`
    # escapes it. Both forms are printed because only the compose file needs escaping.
    print("\nFor a docker-compose file (TrueNAS 'Install via YAML'), paste this:\n")
    print(digest.replace("$", "$$"))
    print("\nFor a .env file or a plain environment variable, paste this instead:\n")
    print(digest)


if __name__ == "__main__":
    main()
