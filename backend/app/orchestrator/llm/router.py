"""LLMRouter — maps provider name to the correct LLMClient concrete class (PR1.1/PR1.4).

PR1.4 adds route() which resolves credentials from the per-user credential store
via credential_resolver before constructing the provider client.
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.orchestrator.llm.base import LLMClient


class LLMRouter:
    """Return the appropriate LLMClient for a given provider name."""

    def get_client(self, provider: str, api_key: str = "") -> LLMClient:
        p = provider.lower()
        if p == "anthropic":
            from app.orchestrator.llm.anthropic_provider import AnthropicProvider  # noqa: PLC0415
            return AnthropicProvider(api_key=api_key)
        if p == "openai":
            from app.orchestrator.llm.openai_provider import OpenAIProvider  # noqa: PLC0415
            return OpenAIProvider(api_key=api_key)
        if p == "google":
            from app.orchestrator.llm.google_provider import GoogleProvider  # noqa: PLC0415
            return GoogleProvider(api_key=api_key)
        if p == "ollama":
            # Ollama is a local, key-less provider — no credential is required,
            # so api_key defaults to "" and no credential lookup ever runs.
            from app.orchestrator.ollama_client import OllamaClient  # noqa: PLC0415
            return OllamaClient()
        if p == "copilot":
            # GitHub Copilot: api_key is the stored GitHub OAuth token; the
            # provider exchanges it for a short-lived Copilot token internally.
            from app.orchestrator.llm.copilot_provider import CopilotProvider  # noqa: PLC0415
            return CopilotProvider(api_key=api_key)
        raise ValueError(
            f"Unknown LLM provider: {provider!r}. "
            "Supported values: 'anthropic', 'openai', 'google', 'ollama', 'copilot'."
        )

    async def route(
        self,
        db: AsyncSession,
        provider: str,
        user_id: uuid.UUID | None = None,
    ) -> LLMClient:
        """Resolve the credential for *provider* then return a ready LLMClient.

        Credential lookup uses credential_resolver which reads CURRENT_USER_ID
        from the contextvar when user_id is None.  Each call to route() issues a
        fresh DB lookup so a revoked-then-recreated credential is picked up
        immediately on the next call without any cache invalidation step.

        Ollama is short-circuited BEFORE any credential resolution: it is a
        local, key-less provider, so no per-user credential is required and no
        DB lookup is performed.
        """
        if provider == "ollama":
            return self.get_client("ollama")
        from app.orchestrator.llm.credential_resolver import resolve_provider_credential  # noqa: PLC0415
        api_key = await resolve_provider_credential(db=db, provider=provider, user_id=user_id)
        return self.get_client(provider, api_key)
