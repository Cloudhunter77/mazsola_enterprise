"""The app must refuse to start in a configuration that only looks secure.

The signing key's default is published in this repository, so an installation left with it
can have its session cookie forged by anyone who has read the source. That is a silent
failure - everything appears to work - which is exactly the kind worth making loud.
"""

from __future__ import annotations

import pytest

from leltar.config import Settings
from leltar.security import (
    InsecureConfiguration,
    check_configuration,
    hash_password,
    issue_session,
    read_session,
    verify_api_key,
    verify_password,
)

GOOD_SECRET = "0f9c1b2a3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8"


def settings(**overrides) -> Settings:
    base = dict(secret_key=GOOD_SECRET, app_password_hash=hash_password("jelszo"))
    base.update(overrides)
    return Settings(**base)


@pytest.mark.parametrize(
    "secret",
    [
        "change-me-in-production",
        "dev-secret-not-for-real-use",
        "change_me_secret",
        "secret",
        "",
        "rovid",  # a typed-in password used as a signing key
    ],
)
def test_a_placeholder_or_short_secret_stops_the_app(secret: str):
    with pytest.raises(InsecureConfiguration):
        check_configuration(settings(secret_key=secret))


def test_a_real_secret_is_accepted():
    check_configuration(settings())


def test_local_development_may_disable_auth_entirely():
    """The escape hatch has to work, or nobody can run this on a laptop."""
    check_configuration(settings(secret_key="dev-secret-not-for-real-use", auth_disabled=True))


def test_a_session_cookie_signed_with_another_key_is_rejected():
    other = settings(secret_key="1" * 64)
    token = issue_session(other)
    assert read_session(settings(), token) is None
    assert read_session(other, token) == "owner"


def test_passwords_and_api_keys_are_checked_properly():
    stored = hash_password("helyes-jelszo")
    assert verify_password("helyes-jelszo", stored) is True
    assert verify_password("rossz", stored) is False
    assert verify_password("barmi", None) is False

    assert verify_api_key("kulcs", "kulcs") is True
    assert verify_api_key("kulcs", "masik") is False
    assert verify_api_key(None, "kulcs") is False
    # An unset server key must not turn every caller into an authorised one.
    assert verify_api_key("kulcs", None) is False


def test_the_two_apps_do_not_share_a_session_cookie():
    """Installed side by side on one host, each app's cookie must mean nothing to the other."""
    from leltar.security import SESSION_COOKIE

    assert SESSION_COOKIE == "home_inventory_session"
