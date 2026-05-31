"""credential_resolver — per-request LLM credential lookup (PR1.4).

Resolution order:
1. Query user_llm_credentials for (user_id, provider) — most recent non-revoked row.
2. Decrypt via Fernet and return the plaintext API key.
3. If no row AND osa_multi_provider_llm=False AND provider="anthropic": fall back to
   settings.anthropic_api_key (legacy single-provider mode).
4. Otherwise raise CredentialNotFound.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decrypt_credential
from app.models.credential import UserLLMCredential
from app.orchestrator.llm.context import get_current_user_id


class CredentialNotFound(Exception):
    """No usable LLM credential found for the given user + provider."""


async def resolve_provider_credential(
    db: AsyncSession,
    provider: str,
    user_id: uuid.UUID | None = None,
) -> str:
    """Return the decrypted API key for *provider* belonging to *user_id*.

    If *user_id* is None, reads from CURRENT_USER_ID contextvar.
    """
    resolved_user_id = user_id if user_id is not None else get_current_user_id()

    if resolved_user_id is not None:
        result = await db.execute(
            select(UserLLMCredential)
            .where(
                UserLLMCredential.user_id == resolved_user_id,
                UserLLMCredential.provider == provider,
                UserLLMCredential.revoked_at.is_(None),
            )
            .order_by(UserLLMCredential.last_used_at.desc().nullslast())
            .limit(1)
        )
        row: UserLLMCredential | None = result.scalar_one_or_none()
        if row is not None:
            plaintext = decrypt_credential(row.encrypted_value)
            await db.execute(
                update(UserLLMCredential)
                .where(UserLLMCredential.id == row.id)
                .values(last_used_at=datetime.now(timezone.utc))
            )
            return plaintext

    # No credential row found — check fallback eligibility.
    if not settings.osa_multi_provider_llm:
        if provider == "anthropic" and settings.anthropic_api_key:
            return settings.anthropic_api_key
    raise CredentialNotFound(
        f"No active credential found for provider={provider!r} "
        f"user_id={resolved_user_id!r}"
    )
