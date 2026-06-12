"""Provider-aware LLM client/model resolution for Performer roles (PR3 / C2 prep).

Single seam mirroring ``AttackPlanner``'s provider switch (planner.py) so the whole
engine shares one knob: ``settings.osa_llm_provider`` (default ``"anthropic"``,
default-OFF for Ollama until PR10).

Resolution rules:
- A caller-injected client (``context["model_client"]``, e.g. a per-user credentialed
  path) always wins.
- Otherwise, when ``osa_llm_provider == "ollama"``, roles route to a local
  ``OllamaClient``.
- Otherwise (``"anthropic"`` with no injected client) ``resolve_role_client`` returns
  ``None`` so the role's smoke fallback keeps unit/offline runs deterministic — it
  does NOT silently construct a real Anthropic client (that would make unit tests
  hit the network). The live Anthropic path is always reached via an injected client.

This keeps the default (anthropic) behavior byte-identical: ``resolve_role_llm_model``
returns the same alias the roles used before, and ``resolve_role_send_model`` returns
the same vendor id the Generator already passed to ``ModelClient.send``.
"""
from __future__ import annotations

from typing import Any

from app.core.config import settings


def _provider() -> str:
    return getattr(settings, "osa_llm_provider", "anthropic")


def resolve_role_client(injected: Any | None = None) -> Any | None:
    """Resolve the LLM client a role should use this turn.

    Injected client wins; else OllamaClient when provider=ollama; else None
    (anthropic-without-injection → caller's smoke fallback).
    """
    if injected is not None:
        return injected
    if _provider() == "ollama":
        from app.orchestrator.ollama_client import OllamaClient

        return OllamaClient()
    return None


def resolve_role_llm_model() -> str:
    """Nominal model label for the ``Role.llm_model`` attribute.

    Anthropic → the legacy alias (unchanged); Ollama → the configured ollama model.
    """
    if _provider() == "ollama":
        return settings.ollama_model
    return settings.anthropic_default_model


def resolve_role_send_model(context_model_id: str | None = None) -> str:
    """Model id to pass to the resolved client's ``.send()``.

    Anthropic → an explicit context override else the vendor default id (matches the
    Generator's prior behavior); Ollama → the configured ollama model.
    """
    if _provider() == "ollama":
        return settings.ollama_model
    return context_model_id or settings.anthropic_default_model_anthropic_id
