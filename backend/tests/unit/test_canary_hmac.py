"""Unit tests for backend/app/agents/canary.py."""
from __future__ import annotations

import hmac
import uuid
from unittest.mock import patch

import pytest

from app.agents.canary import derive_canary_hmac, verify_canary_hmac

_SECRET = b"test-secret"
_SESSION = uuid.UUID("12345678-1234-5678-1234-567812345678")


def test_canary_hmac_deterministic_for_same_session():
    results = [derive_canary_hmac(_SESSION, secret=_SECRET) for _ in range(5)]
    assert len(set(results)) == 1


def test_canary_hmac_differs_across_sessions():
    s1 = uuid.uuid4()
    s2 = uuid.uuid4()
    assert derive_canary_hmac(s1, secret=_SECRET) != derive_canary_hmac(s2, secret=_SECRET)


def test_verify_canary_hmac_constant_time_compare():
    candidate = derive_canary_hmac(_SESSION, secret=_SECRET)
    with patch("app.agents.canary.hmac.compare_digest", wraps=hmac.compare_digest) as mock_cd:
        result = verify_canary_hmac(_SESSION, candidate, secret=_SECRET)
        mock_cd.assert_called_once()
    assert result is True


def test_canary_hmac_length_is_32_hex():
    token = derive_canary_hmac(_SESSION, secret=_SECRET)
    assert len(token) == 32
    assert all(c in "0123456789abcdef" for c in token)


def test_canary_hmac_rejects_tampered():
    expected = derive_canary_hmac(_SESSION, secret=_SECRET)
    tampered = expected[:-1] + ("x" if expected[-1] != "x" else "y")
    assert verify_canary_hmac(_SESSION, tampered, secret=_SECRET) is False


def test_canary_hmac_secret_from_env(monkeypatch):
    monkeypatch.setenv("OSA_CANARY_SECRET", "env-secret-value")
    token_env = derive_canary_hmac(_SESSION)
    token_explicit = derive_canary_hmac(_SESSION, secret=b"env-secret-value")
    assert token_env == token_explicit
    token_default = derive_canary_hmac(_SESSION, secret=b"osa-canary-v1")
    assert token_env != token_default
