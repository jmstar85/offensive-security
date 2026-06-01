"""Unit tests for Fernet key rotation primitives — W5/PR5.1."""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.safety.credential_key_rotation import (
    MAX_KEY_RING_SIZE,
    LocalPassThroughKms,
    build_multi_fernet,
    parse_keyring_env,
    rotate,
)

KMS = LocalPassThroughKms()


def _raw_key() -> bytes:
    return Fernet.generate_key()


def test_build_multi_fernet_rejects_empty():
    with pytest.raises(ValueError, match="at least one Fernet key required"):
        build_multi_fernet([], KMS)


def test_build_multi_fernet_rejects_ring_too_large():
    keys = [_raw_key() for _ in range(MAX_KEY_RING_SIZE + 1)]
    with pytest.raises(ValueError, match="MAX_KEY_RING_SIZE"):
        build_multi_fernet(keys, KMS)


def test_build_multi_fernet_encrypts_with_first_key():
    k1 = _raw_key()
    k2 = _raw_key()
    mf = build_multi_fernet([k1, k2], KMS)
    token = mf.encrypt(b"secret")

    # k1 alone can decrypt (first key is the encrypting key)
    assert Fernet(k1).decrypt(token) == b"secret"

    # k2 alone cannot decrypt what was encrypted by k1
    with pytest.raises(InvalidToken):
        Fernet(k2).decrypt(token)


def test_rotation_prepends_and_purges_tail():
    k1, k2, k3 = _raw_key(), _raw_key(), _raw_key()
    k4 = _raw_key()
    result = rotate([k1, k2, k3], k4)
    assert result == [k4, k1, k2]  # k3 purged


def test_rotation_with_single_existing_key():
    k1 = _raw_key()
    k2 = _raw_key()
    result = rotate([k1], k2)
    assert result == [k2, k1]


def test_parse_keyring_env_comma_separated():
    result = parse_keyring_env("k1,k2,k3")
    assert result == [b"k1", b"k2", b"k3"]


def test_parse_keyring_env_falls_back_to_legacy_single_key(monkeypatch):
    monkeypatch.setenv("OSA_CREDENTIAL_FERNET_KEY", "legacy")
    monkeypatch.delenv("CREDENTIAL_FERNET_KEY", raising=False)
    result = parse_keyring_env(None)
    assert result == [b"legacy"]


def test_parse_keyring_env_returns_empty_when_unset(monkeypatch):
    monkeypatch.delenv("OSA_CREDENTIAL_FERNET_KEY", raising=False)
    monkeypatch.delenv("CREDENTIAL_FERNET_KEY", raising=False)
    result = parse_keyring_env(None)
    assert result == []


def test_local_pass_through_kms_returns_key_verbatim():
    kms = LocalPassThroughKms()
    raw = b"somekey"
    assert kms.unwrap(raw) == raw


def test_rotation_maintains_backward_decrypt_compat():
    k1 = _raw_key()
    k2 = _raw_key()

    # encrypt under k1 alone
    token = Fernet(k1).encrypt(b"old-secret")

    # rotate: new ring is [k2, k1]
    new_ring = rotate([k1], k2)
    mf = build_multi_fernet(new_ring, KMS)

    # MultiFernet with k2 current + k1 legacy can still decrypt k1-encrypted token
    assert mf.decrypt(token) == b"old-secret"
