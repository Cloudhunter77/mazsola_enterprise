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

from app.security import hash_password  # noqa: E402


def main() -> None:
    password = getpass.getpass("Password: ")
    if not password:
        raise SystemExit("No password given.")
    if password != getpass.getpass("Again: "):
        raise SystemExit("The two entries did not match.")
    if len(password) < 8:
        print("Warning: shorter than 8 characters.", file=sys.stderr)

    print("\nPaste this as APP_PASSWORD_HASH:\n")
    print(hash_password(password))


if __name__ == "__main__":
    main()
