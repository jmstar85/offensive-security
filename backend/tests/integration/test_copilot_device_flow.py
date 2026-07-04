"""Integration tests: GitHub Copilot OAuth device-flow endpoints.

httpx.AsyncClient is patched to stub GitHub's device-code/token endpoints and a
fake DB captures the persisted credential — no real network or DB.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException


def _mock_user(user_id: uuid.UUID | None = None) -> MagicMock:
    u = MagicMock()
    u.id = user_id or uuid.uuid4()
    u.is_active = True
    return u


class _Resp:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _fake_client(post_resp: _Resp):
    class _C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return post_resp

    return _C


class _FakeDB:
    def __init__(self):
        self.saved: list = []

    def add(self, obj):
        self.saved.append(obj)

    async def flush(self):
        for o in self.saved:
            if getattr(o, "id", None) is None:
                o.id = uuid.uuid4()
            if getattr(o, "created_at", None) is None:
                o.created_at = datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_device_start_returns_user_code_and_stores_pending():
    from app.api.v1 import credentials as cred

    device_resp = _Resp(200, {
        "device_code": "dev_code_123",
        "user_code": "ABCD-1234",
        "verification_uri": "https://github.com/login/device",
        "interval": 5,
        "expires_in": 900,
    })
    user = _mock_user()
    with patch("app.api.v1.credentials.httpx.AsyncClient", _fake_client(device_resp)):
        resp = await cred.device_flow_start(provider="copilot", current_user=user)

    assert resp.user_code == "ABCD-1234"
    assert resp.verification_uri.endswith("/login/device")
    assert resp.state in cred._oauth_pending
    assert cred._oauth_pending[resp.state]["device_code"] == "dev_code_123"
    del cred._oauth_pending[resp.state]


@pytest.mark.asyncio
async def test_device_start_rejects_non_device_provider():
    from app.api.v1 import credentials as cred

    with pytest.raises(HTTPException) as ei:
        await cred.device_flow_start(provider="anthropic", current_user=_mock_user())
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_device_poll_pending_keeps_state():
    from app.api.v1 import credentials as cred

    user = _mock_user()
    state = cred._make_state_token(str(user.id))
    cred._oauth_pending[state] = {
        "user_id": str(user.id),
        "device_code": "dc",
        "provider": "copilot",
        "interval": 5,
        "expires_at": datetime(2099, 1, 1, tzinfo=timezone.utc),
    }
    with patch(
        "app.api.v1.credentials.httpx.AsyncClient",
        _fake_client(_Resp(200, {"error": "authorization_pending"})),
    ):
        resp = await cred.device_flow_poll(
            provider="copilot",
            body=cred.DevicePollRequest(state=state),
            db=MagicMock(),
            current_user=user,
        )
    assert resp.status == "pending"
    assert state in cred._oauth_pending  # still pending
    del cred._oauth_pending[state]


@pytest.mark.asyncio
async def test_device_poll_complete_persists_encrypted_copilot_credential(monkeypatch):
    from cryptography.fernet import Fernet

    from app.core import config as cfg

    monkeypatch.setattr(cfg.settings, "credential_fernet_key", Fernet.generate_key().decode())

    from app.api.v1 import credentials as cred
    from app.core.security import decrypt_credential

    user = _mock_user()
    state = cred._make_state_token(str(user.id))
    cred._oauth_pending[state] = {
        "user_id": str(user.id),
        "device_code": "dc",
        "provider": "copilot",
        "interval": 5,
        "expires_at": datetime(2099, 1, 1, tzinfo=timezone.utc),
    }
    db = _FakeDB()
    with patch(
        "app.api.v1.credentials.httpx.AsyncClient",
        _fake_client(_Resp(200, {"access_token": "gho_realtoken"})),
    ):
        resp = await cred.device_flow_poll(
            provider="copilot",
            body=cred.DevicePollRequest(state=state),
            db=db,
            current_user=user,
        )

    assert resp.status == "complete"
    assert resp.credential is not None and resp.credential.provider == "copilot"
    creds = [o for o in db.saved if isinstance(o, cred.UserLLMCredential)]
    assert len(creds) == 1
    # stored encrypted, decrypts back to the GitHub token, never plaintext
    assert creds[0].encrypted_value != b"gho_realtoken"
    assert decrypt_credential(creds[0].encrypted_value) == "gho_realtoken"
    assert state not in cred._oauth_pending  # consumed


@pytest.mark.asyncio
async def test_device_poll_access_denied():
    from app.api.v1 import credentials as cred

    user = _mock_user()
    state = cred._make_state_token(str(user.id))
    cred._oauth_pending[state] = {
        "user_id": str(user.id),
        "device_code": "dc",
        "provider": "copilot",
        "interval": 5,
        "expires_at": datetime(2099, 1, 1, tzinfo=timezone.utc),
    }
    with patch(
        "app.api.v1.credentials.httpx.AsyncClient",
        _fake_client(_Resp(200, {"error": "access_denied"})),
    ):
        resp = await cred.device_flow_poll(
            provider="copilot",
            body=cred.DevicePollRequest(state=state),
            db=MagicMock(),
            current_user=user,
        )
    assert resp.status == "denied"
    assert state not in cred._oauth_pending
