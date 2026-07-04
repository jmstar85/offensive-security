"""GET /config/copilot/models — live GitHub Copilot model list.

Backend companion to the new-flow provider/model selector: when the operator
picks "GitHub Copilot", the frontend calls this to populate the model dropdown
with whatever Copilot currently offers *this* account (the same catalog the
editor model picker uses), instead of a hardcoded list that goes stale.

Resolves the user's stored Copilot (GitHub OAuth) credential, exchanges it for a
Copilot token, and lists ``https://api.githubcopilot.com/models``. Fails soft: if
no credential is connected yet, or Copilot is unreachable, returns a modern
curated fallback with ``reachable: false`` so the UI still offers usable options
(and prompts the operator to connect Copilot to see the live list).

Model ids are namespaced ``copilot/<id>`` so per-role routing (``provider_of``)
can distinguish them from bare openai/anthropic ids.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User

router = APIRouter()

# Shown only before a Copilot credential is connected (the live catalog
# supersedes this once connected). Kept to current, non-deprecated families.
CURATED_COPILOT_MODELS: list[str] = [
    "copilot/gpt-4.1",
    "copilot/gpt-4o",
    "copilot/o4-mini",
    "copilot/o3",
    "copilot/claude-sonnet-4.5",
    "copilot/claude-sonnet-4",
    "copilot/claude-3.7-sonnet",
    "copilot/gemini-2.5-pro",
]


@router.get("/config/copilot/models")
async def get_copilot_models(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from app.orchestrator.llm.copilot_provider import CopilotProvider  # noqa: PLC0415
    from app.orchestrator.llm.credential_resolver import (  # noqa: PLC0415
        CredentialNotFound,
        resolve_provider_credential,
    )

    try:
        github_token = await resolve_provider_credential(
            db=db, provider="copilot", user_id=current_user.id
        )
    except CredentialNotFound:
        # Not connected yet — offer the curated modern list so the dropdown is
        # never empty; the UI nudges the operator to connect for the live list.
        return {"models": CURATED_COPILOT_MODELS, "reachable": False}

    try:
        ids = await CopilotProvider(api_key=github_token).list_models()
    except Exception:
        # Token invalid / Copilot unreachable / no subscription — fail soft.
        return {"models": CURATED_COPILOT_MODELS, "reachable": False}

    models = [f"copilot/{i}" for i in ids]
    if not models:
        return {"models": CURATED_COPILOT_MODELS, "reachable": False}
    return {"models": models, "reachable": True}
