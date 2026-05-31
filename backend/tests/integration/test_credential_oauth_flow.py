"""Integration tests: OAuth PKCE flow for LLM provider credentials.

Uses httpx MockTransport to stub provider token-exchange endpoints.
No real network calls are made.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from httpx import Request, Response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_token_response(access_token: str = "tok_abc123", expires_in: int = 3600) -> Response:
    return Response(
        200,
        content=json.dumps({"access_token": access_token, "expires_in": expires_in}).encode(),
        headers={"content-type": "application/json"},
    )


def _make_mock_user(user_id: uuid.UUID | None = None) -> MagicMock:
    u = MagicMock()
    u.id = user_id or uuid.uuid4()
    u.is_active = True
    return u


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_oauth_start_returns_auth_url_and_state(monkeypatch):
    from cryptography.fernet import Fernet as _F
    key = _F.generate_key().decode()

    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "credential_fernet_key", key)
    monkeypatch.setattr(cfg.settings, "oauth_redirect_uri", "http://localhost:8000/api/v1/auth/llm-providers/oauth/callback")

    from app.api.v1.credentials import _oauth_pending, oauth_start

    user = _make_mock_user()
    result = await oauth_start(provider="google", current_user=user)

    assert result.state in _oauth_pending
    assert "accounts.google.com" in result.auth_url
    assert "code_challenge" in result.auth_url
    assert "code_challenge_method=S256" in result.auth_url
    assert cfg.settings.oauth_redirect_uri in result.auth_url

    pending = _oauth_pending[result.state]
    assert pending["user_id"] == str(user.id)
    assert len(pending["code_verifier"]) >= 43

    # cleanup
    del _oauth_pending[result.state]


@pytest.mark.asyncio
async def test_pkce_verifier_round_trips(monkeypatch):
    import hashlib
    import base64
    from app.api.v1.credentials import _pkce_challenge

    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    challenge = _pkce_challenge(verifier)
    digest = hashlib.sha256(verifier.encode()).digest()
    expected = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    assert challenge == expected


@pytest.mark.asyncio
async def test_state_tampering_rejected(monkeypatch):
    from fastapi import HTTPException
    from app.api.v1.credentials import _oauth_pending, oauth_callback

    # Insert a pending entry with a manipulated state key
    tampered_state = "tampered_state_value_xyz"
    _oauth_pending[tampered_state] = {
        "user_id": str(uuid.uuid4()),
        "code_verifier": "verifier",
        "expires_at": datetime(2099, 1, 1, tzinfo=timezone.utc),
        "provider": "google",
    }

    db = AsyncMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        await oauth_callback(code="somecode", state=tampered_state, db=db)

    assert exc_info.value.status_code == 400
    assert "HMAC" in exc_info.value.detail or "state" in exc_info.value.detail.lower()
    _oauth_pending.pop(tampered_state, None)


@pytest.mark.asyncio
async def test_expired_state_rejected(monkeypatch):
    from fastapi import HTTPException
    from app.api.v1.credentials import _make_state_token, _oauth_pending, oauth_callback

    user_id = str(uuid.uuid4())
    state = _make_state_token(user_id)
    _oauth_pending[state] = {
        "user_id": user_id,
        "code_verifier": "verifier",
        "expires_at": datetime(2000, 1, 1, tzinfo=timezone.utc),  # already expired
        "provider": "google",
    }

    db = AsyncMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        await oauth_callback(code="anycode", state=state, db=db)

    assert exc_info.value.status_code == 400
    assert "expired" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_successful_oauth_callback_persists_encrypted_cred(monkeypatch):
    from cryptography.fernet import Fernet as _F
    key = _F.generate_key().decode()

    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "credential_fernet_key", key)
    monkeypatch.setattr(cfg.settings, "oauth_redirect_uri", "http://localhost:8000/api/v1/auth/llm-providers/oauth/callback")

    from app.api.v1 import credentials as creds_mod
    from app.api.v1.credentials import _make_state_token, _oauth_pending

    user_id = str(uuid.uuid4())
    state = _make_state_token(user_id)
    _oauth_pending[state] = {
        "user_id": user_id,
        "code_verifier": "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        "expires_at": datetime(2099, 1, 1, tzinfo=timezone.utc),
        "provider": "openai",  # no introspection URL — skips scope check
    }

    raw_access_token = "real_access_token_value"

    # Stub httpx.AsyncClient.post to return a fake token response
    mock_response = _fake_token_response(access_token=raw_access_token)

    from unittest.mock import patch, AsyncMock as _AM

    saved_creds: list = []

    class _FakeDB:
        def add(self, obj):
            saved_creds.append(obj)

        async def flush(self):
            # Simulate SQLAlchemy default-population (uuid4 + now) so the
            # endpoint can build CredentialResponse from the model.
            from datetime import datetime, timezone
            for o in saved_creds:
                if getattr(o, "id", None) is None:
                    o.id = uuid.uuid4()
                if getattr(o, "created_at", None) is None:
                    o.created_at = datetime.now(timezone.utc)

        async def execute(self, stmt):
            from sqlalchemy.engine import Result
            mock_result = MagicMock()
            mock_user = _make_mock_user(uuid.UUID(user_id))
            mock_result.scalar_one_or_none.return_value = mock_user
            return mock_result

    class _FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, **kwargs):
            return mock_response

    with patch("app.api.v1.credentials.httpx.AsyncClient", _FakeAsyncClient):
        response = await creds_mod.oauth_callback(code="authcode", state=state, db=_FakeDB())

    # Credential should have been saved
    cred_objs = [o for o in saved_creds if isinstance(o, creds_mod.UserLLMCredential)]
    assert len(cred_objs) == 1
    cred = cred_objs[0]

    # encrypted_value must not equal plaintext
    assert cred.encrypted_value != raw_access_token.encode()
    # but must decrypt back to the original token
    from app.core.security import decrypt_credential
    assert decrypt_credential(cred.encrypted_value) == raw_access_token

    # Response must not include the secret
    assert response.id == cred.id
    assert not hasattr(response, "encrypted_value")
