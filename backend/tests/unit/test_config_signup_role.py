"""Unit: config validators for signup role and admin email normalization.

Guards the fixes for:
  - An invalid DEFAULT_SIGNUP_ROLE must fail fast at startup (not 500 on the
    first signup) — including the legacy 'user' literal that the DB CHECK allows
    but no UserRole / auth gate recognises.
  - admin_email is lowercased so the seeded admin (written from it) can log in
    via the now-lowercased login lookup.
"""
import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_default_signup_role_default_is_admin():
    assert Settings().default_signup_role == "admin"


def test_member_signup_role_accepted():
    assert Settings(default_signup_role="member").default_signup_role == "member"


def test_invalid_signup_role_rejected():
    with pytest.raises(ValidationError):
        Settings(default_signup_role="superuser")


def test_legacy_user_literal_rejected():
    # 'user' passes the DB CHECK but is not a UserRole — would land accounts in
    # a no-privilege limbo; the validator must reject it at startup.
    with pytest.raises(ValidationError):
        Settings(default_signup_role="user")


def test_admin_email_is_normalized():
    assert Settings(admin_email="  Admin@KT.com ").admin_email == "admin@kt.com"


def test_blank_admin_email_stays_blank():
    # Empty stays falsy so the seed-skip check keeps working.
    assert Settings(admin_email="").admin_email == ""
