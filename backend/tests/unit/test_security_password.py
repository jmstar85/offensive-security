"""Unit: password hashing uses bcrypt directly and round-trips correctly.

Regression guard for the migration off passlib (whose final release, 1.7.4,
crashes its backend self-test against bcrypt >= 4.1 / 5.x). See
app/core/security.py. These exercise REAL bcrypt — no patching.
"""
from app.core.security import hash_password, verify_password


def test_hash_is_bcrypt_and_verifies():
    h = hash_password("CorrectHorse123")
    assert h.startswith("$2b$")
    assert verify_password("CorrectHorse123", h) is True
    assert verify_password("wrong-password", h) is False


def test_hashes_are_salted_and_unique():
    # Same input, different salts -> different hashes, both verify.
    a = hash_password("samePW123")
    b = hash_password("samePW123")
    assert a != b
    assert verify_password("samePW123", a)
    assert verify_password("samePW123", b)


def test_long_password_truncated_not_crashing():
    # bcrypt >= 4 raises on > 72 bytes; security.py truncates to 72 first so
    # long passwords neither crash nor are rejected.
    long_pw = "A" * 200
    h = hash_password(long_pw)
    assert verify_password(long_pw, h) is True
    assert verify_password("A" * 72, h) is True  # identical first 72 bytes


def test_verify_rejects_malformed_hash():
    # A non-bcrypt hash makes bcrypt.checkpw raise; verify must return False.
    assert verify_password("whatever", "not-a-bcrypt-hash") is False
