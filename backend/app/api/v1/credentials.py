"""LLM provider credential management + OAuth (PKCE) endpoints.

Security invariants enforced here:
- Encrypted values are NEVER returned in any response.
- audit_logs.details_json never contains the raw secret.
- OAuth redirect URI is exact-match only (no prefix/wildcard).
- Scope-drift triggers audit + credential revocation.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.security import decrypt_credential, encrypt_credential
from app.models.audit import AuditLog
from app.models.credential import UserLLMCredential
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Expected OAuth scopes per provider (v1 — Anthropic/OpenAI undocumented)
# ---------------------------------------------------------------------------
EXPECTED_SCOPES: dict[str, set[str]] = {
    "google": {
        "openid",
        "email",
        "https://www.googleapis.com/auth/generative-language.retriever",
    },
    # TODO: populate once Anthropic/OpenAI publish their OAuth scope vocabulary
    "anthropic": set(),
    "openai": set(),
}

# Provider OAuth endpoints (Anthropic/OpenAI are placeholders pending public docs)
_PROVIDER_AUTH_URLS: dict[str, str] = {
    "anthropic": "https://auth.anthropic.com/oauth/authorize",
    "openai": "https://platform.openai.com/oauth/authorize",
    "google": "https://accounts.google.com/o/oauth2/v2/auth",
}

_PROVIDER_TOKEN_URLS: dict[str, str] = {
    "anthropic": "https://auth.anthropic.com/oauth/token",
    "openai": "https://platform.openai.com/oauth/token",
    "google": "https://oauth2.googleapis.com/token",
}

_PROVIDER_REVOKE_URLS: dict[str, str | None] = {
    "anthropic": None,
    "openai": None,
    "google": "https://oauth2.googleapis.com/revoke",
}

_PROVIDER_INTROSPECT_URLS: dict[str, str | None] = {
    "anthropic": None,
    "openai": None,
    "google": "https://oauth2.googleapis.com/tokeninfo",
}

# GitHub Copilot uses the OAuth *device flow* (poll-based), not the
# authorization-code+redirect PKCE flow above — so it has its own endpoints.
# The client id is GitHub's public Copilot GitHub-App id (no client secret).
_GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
_GITHUB_DEVICE_TOKEN_URL = "https://github.com/login/oauth/access_token"
_DEVICE_FLOW_PROVIDERS = {"copilot"}

# ---------------------------------------------------------------------------
# In-memory short-term store for pending OAuth state (TTL-checked on each call)
# Keyed by state token → {user_id, code_verifier, expires_at, provider}
# ---------------------------------------------------------------------------
_oauth_pending: dict[str, dict[str, Any]] = {}


def _purge_expired_states() -> None:
    now = datetime.now(timezone.utc)
    expired = [k for k, v in _oauth_pending.items() if v["expires_at"] <= now]
    for k in expired:
        del _oauth_pending[k]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CredentialResponse(BaseModel):
    id: uuid.UUID
    provider: str
    credential_type: str
    label: str | None
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None


class CreateApiKeyRequest(BaseModel):
    provider: str
    credential_type: str = "api_key"
    label: str | None = None
    api_key: str


class OAuthStartResponse(BaseModel):
    auth_url: str
    state: str


class DeviceStartResponse(BaseModel):
    user_code: str
    verification_uri: str
    interval: int
    expires_in: int
    state: str


class DevicePollRequest(BaseModel):
    state: str


class DevicePollResponse(BaseModel):
    status: str  # "pending" | "complete" | "expired" | "denied"
    credential: CredentialResponse | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_credential_response(cred: UserLLMCredential) -> CredentialResponse:
    return CredentialResponse(
        id=cred.id,
        provider=cred.provider,
        credential_type=cred.credential_type,
        label=cred.label,
        created_at=cred.created_at,
        expires_at=cred.expires_at,
        revoked_at=cred.revoked_at,
        last_used_at=cred.last_used_at,
    )


def _make_state_token(user_id: str) -> str:
    """HMAC-signed state token: base64url(sha256(user_id || timestamp || random))."""
    timestamp = str(int(datetime.now(timezone.utc).timestamp()))
    nonce = secrets.token_hex(16)
    raw = f"{user_id}|{timestamp}|{nonce}"
    sig = hmac.new(settings.secret_key.encode(), raw.encode(), hashlib.sha256).hexdigest()
    payload = base64.urlsafe_b64encode(f"{raw}|{sig}".encode()).decode().rstrip("=")
    return payload


def _verify_state_token(state: str, user_id: str) -> bool:
    try:
        padded = state + "=" * (4 - len(state) % 4)
        decoded = base64.urlsafe_b64decode(padded).decode()
        parts = decoded.rsplit("|", 1)
        if len(parts) != 2:
            return False
        raw, sig = parts
        expected_sig = hmac.new(
            settings.secret_key.encode(), raw.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return False
        raw_parts = raw.split("|")
        if raw_parts[0] != user_id:
            return False
        return True
    except Exception:
        return False


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/credentials/llm-providers", response_model=list[CredentialResponse])
async def list_credentials(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(UserLLMCredential)
        .where(UserLLMCredential.user_id == current_user.id)
        .order_by(UserLLMCredential.created_at.desc())
    )
    return [_build_credential_response(c) for c in result.scalars().all()]


@router.post("/credentials/llm-providers", response_model=CredentialResponse, status_code=201)
async def create_api_key_credential(
    body: CreateApiKeyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if body.provider not in _PROVIDER_AUTH_URLS:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {body.provider}")

    encrypted = encrypt_credential(body.api_key)
    cred = UserLLMCredential(
        user_id=current_user.id,
        provider=body.provider,
        credential_type="api_key",
        encrypted_value=encrypted,
        label=body.label,
    )
    db.add(cred)
    await db.flush()

    db.add(AuditLog(
        actor_id=current_user.id,
        action="credential.created",
        target_entity="user_llm_credentials",
        target_id=str(cred.id),
        details_json={"provider": body.provider, "label": body.label},
    ))
    await db.flush()

    return _build_credential_response(cred)


@router.delete("/credentials/llm-providers/{cred_id}", status_code=204)
async def revoke_credential(
    cred_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(UserLLMCredential).where(
            UserLLMCredential.id == cred_id,
            UserLLMCredential.user_id == current_user.id,
        )
    )
    cred = result.scalar_one_or_none()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")

    now = datetime.now(timezone.utc)
    cred.revoked_at = now

    # RFC 7009: best-effort remote revocation for OAuth tokens
    if cred.credential_type == "oauth_token":
        revoke_url = _PROVIDER_REVOKE_URLS.get(cred.provider)
        if revoke_url:
            try:
                plaintext = decrypt_credential(cred.encrypted_value)
                async with httpx.AsyncClient() as client:
                    await client.post(revoke_url, data={"token": plaintext})
            except Exception as exc:
                logger.warning("Remote OAuth revocation failed for cred %s: %s", cred_id, exc)

    db.add(AuditLog(
        actor_id=current_user.id,
        action="credential.revoked",
        target_entity="user_llm_credentials",
        target_id=str(cred_id),
        details_json={"provider": cred.provider, "credential_type": cred.credential_type},
    ))
    await db.flush()


@router.post("/auth/llm-providers/{provider}/oauth/start", response_model=OAuthStartResponse)
async def oauth_start(
    provider: str,
    current_user: User = Depends(get_current_user),
):
    if provider not in _PROVIDER_AUTH_URLS:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    _purge_expired_states()

    code_verifier = secrets.token_urlsafe(43)
    code_challenge = _pkce_challenge(code_verifier)
    state = _make_state_token(str(current_user.id))
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)

    _oauth_pending[state] = {
        "user_id": str(current_user.id),
        "code_verifier": code_verifier,
        "expires_at": expires_at,
        "provider": provider,
    }

    # Exact-match redirect URI — no wildcards, no prefix matching (SF-CRITIC-7)
    redirect_uri = settings.oauth_redirect_uri

    base_url = _PROVIDER_AUTH_URLS[provider]
    params = (
        f"?response_type=code"
        f"&client_id={provider}_client_id_placeholder"
        f"&redirect_uri={redirect_uri}"
        f"&state={state}"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
    )
    auth_url = base_url + params

    return OAuthStartResponse(auth_url=auth_url, state=state)


@router.get("/auth/llm-providers/oauth/callback")
async def oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    _purge_expired_states()

    pending = _oauth_pending.get(state)
    if not pending:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    now = datetime.now(timezone.utc)
    if pending["expires_at"] <= now:
        del _oauth_pending[state]
        raise HTTPException(status_code=400, detail="OAuth state expired")

    user_id = pending["user_id"]
    if not _verify_state_token(state, user_id):
        raise HTTPException(status_code=400, detail="OAuth state HMAC validation failed")

    code_verifier = pending["code_verifier"]
    provider = pending["provider"]
    del _oauth_pending[state]

    # Exact-match redirect URI re-derived identically to /oauth/start (SF-CRITIC-7)
    redirect_uri = settings.oauth_redirect_uri

    token_url = _PROVIDER_TOKEN_URLS[provider]
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
                "client_id": f"{provider}_client_id_placeholder",
            },
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail="Token exchange failed")

    token_data = resp.json()
    access_token = token_data.get("access_token", "")
    expires_in = token_data.get("expires_in")
    expires_at = None
    if expires_in:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))

    # Scope-drift detection
    introspect_url = _PROVIDER_INTROSPECT_URLS.get(provider)
    if introspect_url:
        try:
            async with httpx.AsyncClient() as client:
                intro_resp = await client.get(introspect_url, params={"id_token": access_token})
            if intro_resp.status_code == 200:
                intro_data = intro_resp.json()
                granted_scope_str = intro_data.get("scope", "")
                granted_scopes = set(granted_scope_str.split()) if granted_scope_str else set()
                expected = EXPECTED_SCOPES.get(provider, set())
                if expected and not granted_scopes.issubset(expected):
                    drift = granted_scopes - expected
                    db.add(AuditLog(
                        actor_id=None,
                        action="credential.scope_drift",
                        target_entity="user_llm_credentials",
                        target_id=user_id,
                        details_json={
                            "provider": provider,
                            "unexpected_scopes": sorted(drift),
                        },
                    ))
                    await db.flush()
                    raise HTTPException(
                        status_code=400,
                        detail=f"OAuth scope drift detected: unexpected scopes {sorted(drift)}",
                    )
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("Scope introspection failed for provider %s: %s", provider, exc)

    result = await db.execute(
        select(User).where(User.id == uuid.UUID(user_id))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="User not found")

    encrypted = encrypt_credential(access_token)
    cred = UserLLMCredential(
        user_id=user.id,
        provider=provider,
        credential_type="oauth_token",
        encrypted_value=encrypted,
        expires_at=expires_at,
    )
    db.add(cred)
    await db.flush()

    db.add(AuditLog(
        actor_id=user.id,
        action="credential.oauth_exchanged",
        target_entity="user_llm_credentials",
        target_id=str(cred.id),
        details_json={"provider": provider},
    ))
    await db.flush()

    return _build_credential_response(cred)


# ---------------------------------------------------------------------------
# OAuth device flow (GitHub Copilot) — start returns a user_code the operator
# enters at github.com/login/device; poll trades the device_code for a token.
# ---------------------------------------------------------------------------

@router.post("/auth/llm-providers/{provider}/device/start", response_model=DeviceStartResponse)
async def device_flow_start(
    provider: str,
    current_user: User = Depends(get_current_user),
):
    if provider not in _DEVICE_FLOW_PROVIDERS:
        raise HTTPException(
            status_code=400, detail=f"Device flow not supported for provider: {provider}"
        )
    _purge_expired_states()

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                _GITHUB_DEVICE_CODE_URL,
                data={"client_id": settings.github_copilot_client_id},
                headers={"Accept": "application/json"},
            )
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise HTTPException(status_code=502, detail="GitHub device-code request unreachable") from exc

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="GitHub device-code request failed")

    data = resp.json()
    device_code = data.get("device_code")
    user_code = data.get("user_code")
    if not device_code or not user_code:
        raise HTTPException(status_code=502, detail="GitHub device-code response malformed")

    verification_uri = data.get("verification_uri") or "https://github.com/login/device"
    interval = int(data.get("interval", 5))
    expires_in = int(data.get("expires_in", 900))

    state = _make_state_token(str(current_user.id))
    _oauth_pending[state] = {
        "user_id": str(current_user.id),
        "device_code": device_code,
        "provider": provider,
        "interval": interval,
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=expires_in),
    }

    return DeviceStartResponse(
        user_code=user_code,
        verification_uri=verification_uri,
        interval=interval,
        expires_in=expires_in,
        state=state,
    )


@router.post("/auth/llm-providers/{provider}/device/poll", response_model=DevicePollResponse)
async def device_flow_poll(
    provider: str,
    body: DevicePollRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if provider not in _DEVICE_FLOW_PROVIDERS:
        raise HTTPException(
            status_code=400, detail=f"Device flow not supported for provider: {provider}"
        )
    _purge_expired_states()

    pending = _oauth_pending.get(body.state)
    if not pending or pending.get("provider") != provider:
        raise HTTPException(status_code=400, detail="Invalid or expired device state")
    # Bind the poll to the authenticated user (HMAC-signed state + stored user_id).
    if pending["user_id"] != str(current_user.id) or not _verify_state_token(
        body.state, str(current_user.id)
    ):
        raise HTTPException(status_code=403, detail="Device state does not belong to this user")
    if pending["expires_at"] <= datetime.now(timezone.utc):
        del _oauth_pending[body.state]
        return DevicePollResponse(status="expired")

    # Server-side poll-rate cap. GitHub's device token endpoint returns
    # `slow_down` (and WITHHOLDS the token, even after the user authorizes) if
    # polled faster than the interval. The browser may run multiple/overlapping
    # poll timers (React StrictMode double-invoke, re-selects), so enforce the
    # interval HERE: never hit GitHub more than once per interval per device
    # code, regardless of how often the client polls. Too-soon polls report
    # `pending` without a GitHub round-trip.
    now = datetime.now(timezone.utc)
    interval = int(pending.get("interval", 5))
    last_poll = pending.get("last_poll_at")
    if last_poll is not None and (now - last_poll).total_seconds() < interval:
        return DevicePollResponse(status="pending")
    pending["last_poll_at"] = now

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                _GITHUB_DEVICE_TOKEN_URL,
                data={
                    "client_id": settings.github_copilot_client_id,
                    "device_code": pending["device_code"],
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                headers={"Accept": "application/json"},
            )
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise HTTPException(status_code=502, detail="GitHub token poll unreachable") from exc

    data = resp.json() if resp.status_code == 200 else {}
    access_token = data.get("access_token")
    error = data.get("error")

    if access_token:
        del _oauth_pending[body.state]
        encrypted = encrypt_credential(access_token)
        cred = UserLLMCredential(
            user_id=current_user.id,
            provider=provider,
            credential_type="oauth_token",
            encrypted_value=encrypted,
            label="GitHub Copilot",
        )
        db.add(cred)
        await db.flush()
        db.add(AuditLog(
            actor_id=current_user.id,
            action="credential.oauth_exchanged",
            target_entity="user_llm_credentials",
            target_id=str(cred.id),
            details_json={"provider": provider, "flow": "device"},
        ))
        await db.flush()
        return DevicePollResponse(status="complete", credential=_build_credential_response(cred))

    if error == "access_denied":
        del _oauth_pending[body.state]
        return DevicePollResponse(status="denied")
    if error == "expired_token":
        del _oauth_pending[body.state]
        return DevicePollResponse(status="expired")
    if error == "slow_down":
        # GitHub is rate-limiting us — adopt the (higher) interval it returns so
        # the next real GitHub poll waits longer.
        pending["interval"] = int(data.get("interval", interval + 5))
        return DevicePollResponse(status="pending")
    # authorization_pending / transient → keep polling.
    return DevicePollResponse(status="pending")
