"""Safety tests: every credential mutation emits an audit_logs row.

Invariant: audit_logs.details_json MUST NOT contain any plaintext secret.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet


def _make_mock_user(user_id: uuid.UUID | None = None) -> MagicMock:
    u = MagicMock()
    u.id = user_id or uuid.uuid4()
    u.is_active = True
    return u


def _patch_fernet(monkeypatch):
    key = Fernet.generate_key().decode()
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "credential_fernet_key", key)
    monkeypatch.setattr(cfg.settings, "oauth_redirect_uri", "http://localhost:8000/callback")
    return key


class _FakeDB:
    def __init__(self):
        self._added: list = []

    def add(self, obj):
        self._added.append(obj)

    async def flush(self):
        # Mirror SQLAlchemy default-population for the columns SQLAlchemy
        # would normally fill at flush time (Python-side default=uuid.uuid4
        # for id, server_default=func.now() for created_at). Without this
        # the endpoint's CredentialResponse construction would see None.
        for obj in self._added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()
            if getattr(obj, "created_at", None) is None:
                obj.created_at = datetime.now(timezone.utc)

    async def execute(self, stmt):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_result.scalar_one_or_none.return_value = None
        return mock_result

    def audit_entries(self):
        from app.models.audit import AuditLog
        return [o for o in self._added if isinstance(o, AuditLog)]

    def cred_entries(self):
        from app.models.credential import UserLLMCredential
        return [o for o in self._added if isinstance(o, UserLLMCredential)]


@pytest.mark.asyncio
async def test_create_api_key_emits_audit(monkeypatch):
    _patch_fernet(monkeypatch)
    from app.api.v1.credentials import CreateApiKeyRequest, create_api_key_credential

    db = _FakeDB()
    user = _make_mock_user()
    body = CreateApiKeyRequest(provider="openai", api_key="sk-supersecret", label="my-key")

    await create_api_key_credential(body=body, db=db, current_user=user)

    audits = db.audit_entries()
    assert len(audits) == 1
    assert audits[0].action == "credential.created"
    # Must NOT contain the raw api_key
    details = audits[0].details_json or {}
    assert "sk-supersecret" not in str(details)


@pytest.mark.asyncio
async def test_revoke_credential_emits_audit(monkeypatch):
    _patch_fernet(monkeypatch)
    from app.api.v1.credentials import revoke_credential
    from app.models.credential import UserLLMCredential

    cred_id = uuid.uuid4()
    user = _make_mock_user()

    existing_cred = MagicMock(spec=UserLLMCredential)
    existing_cred.id = cred_id
    existing_cred.provider = "google"
    existing_cred.credential_type = "api_key"
    existing_cred.revoked_at = None

    db = _FakeDB()

    async def fake_execute(stmt):
        result = MagicMock()
        result.scalar_one_or_none.return_value = existing_cred
        return result

    db.execute = fake_execute

    await revoke_credential(cred_id=cred_id, db=db, current_user=user)

    audits = db.audit_entries()
    assert len(audits) == 1
    assert audits[0].action == "credential.revoked"
    details = audits[0].details_json or {}
    assert "sk-" not in str(details)
    assert "secret" not in str(details).lower()


@pytest.mark.asyncio
async def test_oauth_exchange_emits_audit(monkeypatch):
    key = _patch_fernet(monkeypatch)

    from app.api.v1 import credentials as creds_mod
    from app.api.v1.credentials import _make_state_token, _oauth_pending
    from app.models.audit import AuditLog

    user_id = str(uuid.uuid4())
    state = _make_state_token(user_id)
    _oauth_pending[state] = {
        "user_id": user_id,
        "code_verifier": "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        "expires_at": datetime(2099, 1, 1, tzinfo=timezone.utc),
        "provider": "anthropic",
    }

    import json
    raw_token = "raw_oauth_token_do_not_log"
    token_payload = json.dumps({"access_token": raw_token, "expires_in": 3600}).encode()

    from httpx import Response as HxResponse

    class _FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, **kwargs):
            return HxResponse(200, content=token_payload, headers={"content-type": "application/json"})

    added: list = []

    class _FakeDB2:
        def add(self, obj):
            added.append(obj)

        async def flush(self):
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
        await creds_mod.oauth_callback(code="authcode", state=state, db=_FakeDB2())

    audit_entries = [o for o in added if isinstance(o, AuditLog)]
    assert any(a.action == "credential.oauth_exchanged" for a in audit_entries)

    # The raw token must NOT appear in any audit details
    for entry in audit_entries:
        details_str = str(entry.details_json or {})
        assert raw_token not in details_str


@pytest.mark.asyncio
async def test_audit_details_never_contains_api_key_value(monkeypatch):
    _patch_fernet(monkeypatch)
    from app.api.v1.credentials import CreateApiKeyRequest, create_api_key_credential
    from app.models.audit import AuditLog

    secret = "sk-ULTRASECRET-12345"
    db = _FakeDB()
    user = _make_mock_user()
    body = CreateApiKeyRequest(provider="anthropic", api_key=secret, label="prod")

    await create_api_key_credential(body=body, db=db, current_user=user)

    for entry in db.audit_entries():
        assert secret not in str(entry.details_json or {})
