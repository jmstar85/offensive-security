"""Unit tests: Fernet encrypt/decrypt round-trip and tamper detection."""
import os

import pytest
from cryptography.fernet import Fernet, InvalidToken


def _patch_fernet_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("CREDENTIAL_FERNET_KEY", key)
    # Force settings to re-read the env var
    from app.core import config as cfg_module
    monkeypatch.setattr(cfg_module.settings, "credential_fernet_key", key)


def test_round_trip(monkeypatch):
    _patch_fernet_key(monkeypatch)
    from app.core.security import decrypt_credential, encrypt_credential

    plaintext = "sk-test-supersecretkey"
    ciphertext = encrypt_credential(plaintext)

    assert isinstance(ciphertext, bytes)
    assert plaintext.encode() not in ciphertext  # not stored in plaintext
    assert decrypt_credential(ciphertext) == plaintext


def test_tampered_ciphertext_raises(monkeypatch):
    _patch_fernet_key(monkeypatch)
    from app.core.security import decrypt_credential, encrypt_credential

    ciphertext = encrypt_credential("some-secret")
    tampered = bytearray(ciphertext)
    tampered[10] ^= 0xFF
    with pytest.raises(InvalidToken):
        decrypt_credential(bytes(tampered))


def test_decrypted_value_not_equal_to_ciphertext(monkeypatch):
    _patch_fernet_key(monkeypatch)
    from app.core.security import decrypt_credential, encrypt_credential

    secret = "do-not-log-me"
    ciphertext = encrypt_credential(secret)
    recovered = decrypt_credential(ciphertext)

    assert recovered == secret
    assert recovered.encode() not in ciphertext


def test_missing_key_raises_runtime_error(monkeypatch):
    from app.core import config as cfg_module
    monkeypatch.setattr(cfg_module.settings, "credential_fernet_key", "")

    # Re-import to pick up patched settings
    import importlib
    import app.core.security as sec_mod
    importlib.reload(sec_mod)

    with pytest.raises(RuntimeError, match="CREDENTIAL_FERNET_KEY"):
        sec_mod.get_fernet()
