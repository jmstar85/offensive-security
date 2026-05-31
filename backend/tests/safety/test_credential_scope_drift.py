"""Safety tests: scope-drift detector emits audit event and revokes credential."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from httpx import Response as HxResponse


def _patch_fernet(monkeypatch):
    key = Fernet.generate_key().decode()
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "credential_fernet_key", key)
    monkeypatch.setattr(cfg.settings, "oauth_redirect_uri", "http://localhost:8000/callback")
    return key


def _make_mock_user(user_id: uuid.UUID | None = None) -> MagicMock:
    u = MagicMock()
    u.id = user_id or uuid.uuid4()
    u.is_active = True
    return u


@pytest.mark.asyncio
async def test_scope_drift_emits_audit_and_raises(monkeypatch):
    _patch_fernet(monkeypatch)

    from app.api.v1 import credentials as creds_mod
    from app.api.v1.credentials import EXPECTED_SCOPES, _make_state_token, _oauth_pending
    from app.models.audit import AuditLog

    user_id = str(uuid.uuid4())
    state = _make_state_token(user_id)
    _oauth_pending[state] = {
        "user_id": user_id,
        "code_verifier": "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        "expires_at": datetime(2099, 1, 1, tzinfo=timezone.utc),
        "provider": "google",
    }

    # Token exchange returns OK
    token_payload = json.dumps({"access_token": "goog_tok", "expires_in": 3600}).encode()

    # Introspection returns scopes OUTSIDE the expected set
    extra_scope = "https://www.googleapis.com/auth/drive.full"
    expected = EXPECTED_SCOPES["google"]
    all_scopes = " ".join(expected | {extra_scope})
    introspect_payload = json.dumps({"scope": all_scopes}).encode()

    call_count = {"n": 0}

    class _FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, **kwargs):
            return HxResponse(200, content=token_payload, headers={"content-type": "application/json"})

        async def get(self, url, **kwargs):
            return HxResponse(200, content=introspect_payload, headers={"content-type": "application/json"})

    added: list = []

    class _FakeDB:
        def add(self, obj):
            added.append(obj)

        async def flush(self):
            from datetime import datetime, timezone
            for o in added:
                if getattr(o, "id", None) is None:
                    o.id = uuid.uuid4()
                if getattr(o, "created_at", None) is None:
                    o.created_at = datetime.now(timezone.utc)

        async def execute(self, stmt):
            result = MagicMock()
            mock_user = _make_mock_user(uuid.UUID(user_id))
            result.scalar_one_or_none.return_value = mock_user
            return result

    from fastapi import HTTPException

    with patch("app.api.v1.credentials.httpx.AsyncClient", _FakeAsyncClient):
        with pytest.raises(HTTPException) as exc_info:
            await creds_mod.oauth_callback(code="authcode", state=state, db=_FakeDB())

    assert exc_info.value.status_code == 400
    assert "scope_drift" in exc_info.value.detail or "scope" in exc_info.value.detail.lower()

    audit_entries = [o for o in added if isinstance(o, AuditLog)]
    drift_audits = [a for a in audit_entries if a.action == "credential.scope_drift"]
    assert len(drift_audits) == 1
    details = drift_audits[0].details_json or {}
    assert extra_scope in details.get("unexpected_scopes", [])


@pytest.mark.asyncio
async def test_no_scope_drift_when_scopes_subset(monkeypatch):
    _patch_fernet(monkeypatch)

    from app.api.v1 import credentials as creds_mod
    from app.api.v1.credentials import EXPECTED_SCOPES, _make_state_token, _oauth_pending
    from app.models.audit import AuditLog

    user_id = str(uuid.uuid4())
    state = _make_state_token(user_id)
    _oauth_pending[state] = {
        "user_id": user_id,
        "code_verifier": "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        "expires_at": datetime(2099, 1, 1, tzinfo=timezone.utc),
        "provider": "google",
    }

    token_payload = json.dumps({"access_token": "goog_tok2", "expires_in": 3600}).encode()
    # Only a subset of expected scopes
    subset_scopes = "openid email"
    introspect_payload = json.dumps({"scope": subset_scopes}).encode()

    class _FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, **kwargs):
            return HxResponse(200, content=token_payload, headers={"content-type": "application/json"})

        async def get(self, url, **kwargs):
            return HxResponse(200, content=introspect_payload, headers={"content-type": "application/json"})

    added: list = []

    class _FakeDB:
        def add(self, obj):
            added.append(obj)

        async def flush(self):
            from datetime import datetime, timezone
            for o in added:
                if getattr(o, "id", None) is None:
                    o.id = uuid.uuid4()
                if getattr(o, "created_at", None) is None:
                    o.created_at = datetime.now(timezone.utc)

        async def execute(self, stmt):
            result = MagicMock()
            mock_user = _make_mock_user(uuid.UUID(user_id))
            result.scalar_one_or_none.return_value = mock_user
            return result

    with patch("app.api.v1.credentials.httpx.AsyncClient", _FakeAsyncClient):
        response = await creds_mod.oauth_callback(code="authcode", state=state, db=_FakeDB())

    audit_entries = [o for o in added if isinstance(o, AuditLog)]
    drift_audits = [a for a in audit_entries if a.action == "credential.scope_drift"]
    assert len(drift_audits) == 0

    exchange_audits = [a for a in audit_entries if a.action == "credential.oauth_exchanged"]
    assert len(exchange_audits) == 1
