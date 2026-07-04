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

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.orchestrator.llm.credential_resolver import CredentialNotFound

logger = logging.getLogger(__name__)


def _provider() -> str:
    return getattr(settings, "osa_llm_provider", "anthropic")


def context_is_bound_live(performer: Any) -> bool:
    """True when *performer* is bound to a live execution context (PR4a).

    The bound-live marker is a non-None ``performer.state.egress_monitor`` (set
    by ``Performer.bind_live_execution``). Consuming roles use this to decide
    whether a ``None`` client is a fail-closed error (live lane → raise
    ``CredentialNotFound``) or an acceptable smoke fallback (unbound/demo).
    Tolerant of ``performer is None`` (unbound unit contexts).
    """
    state = getattr(performer, "state", None)
    return getattr(state, "egress_monitor", None) is not None


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


# ── Per-session, per-role client resolution (PR3 / PM1) ──────────────────────
# Additive to the global-switch helpers above. ``resolve_role_client`` remains
# the NULL/global-switch fallback path used by legacy Path-A fresh-plan runs;
# ``resolve_session_role_client`` is the per-user, per-role, per-invocation
# resolver the redesigned new-flow page routes through.

# Provider prefix heuristics (pragmatic + documented, Principle 10):
#   anthropic → ids start with 'claude'   (e.g. claude-opus-4-8)
#   openai    → ids start with 'gpt'/'o1'/'o3' (e.g. gpt-4o-mini, o1-preview)
#   ollama    → everything else           (qwen*, llama*, mistral*, …)
_ANTHROPIC_PREFIX = "claude"
_OPENAI_PREFIXES = ("gpt", "o1", "o3")


def provider_of(model_id: str) -> str:
    """Best-effort map a model id to the provider that serves it.

    Anthropic ids start ``claude``; OpenAI ids start ``gpt``/``o1``/``o3``;
    everything else (local models like ``qwen3-14b-96k:latest``, ``llama3``)
    resolves to ``ollama``.
    """
    m = (model_id or "").lower()
    # Copilot ids are namespaced ``copilot/<model>`` so they don't collide with
    # bare openai/anthropic ids that Copilot also proxies (gpt-4o, claude-*).
    if m.startswith("copilot/"):
        return "copilot"
    if m.startswith(_ANTHROPIC_PREFIX):
        return "anthropic"
    if m.startswith(_OPENAI_PREFIXES):
        return "openai"
    return "ollama"


def default_model_for(provider: str) -> str:
    """Configured default model id for *provider*.

    ollama → ``settings.ollama_model``; openai → ``settings.openai_default_model``
    (falls back to ``gpt-4o`` until PR4 adds the setting); anthropic (and any
    other) → ``settings.anthropic_default_model``.
    """
    p = (provider or "").lower()
    if p == "ollama":
        return settings.ollama_model
    if p == "openai":
        return getattr(settings, "openai_default_model", "gpt-4o")
    if p == "copilot":
        return getattr(settings, "github_copilot_default_model", "copilot/gpt-4o")
    return settings.anthropic_default_model


async def resolve_session_role_client(
    db: AsyncSession,
    session: Any,
    role: str,
    user_id: uuid.UUID | str,
) -> Any:
    """Resolve the LLM client for *role* on *session*, per invocation.

    Called on EVERY role invocation and NEVER cached for the session
    (Blocking 2): each call issues a fresh ``LLMRouter.route`` — which does a
    fresh DB credential lookup (router.py:43-45) — so a mid-session credential
    revoke is honored on the next call and ``last_used_at``/the credential-touch
    audit is written on every resolve.

    Provider/model precedence (Principle 10):
      1. ``session.model_map[role]`` set → that model; provider = ``provider_of(model)``.
      2. else ``session.llm_provider_pref`` explicit (not NULL) → that provider;
         model = ``session.model_id`` or ``default_model_for(provider)``.
      3. else (NULL — legacy/Path-A fresh-plan) → GLOBAL SWITCH PRESERVED:
         provider = ``settings.osa_llm_provider``; model = ``default_model_for(provider)``.

    ``user_id`` is coerced to ``uuid.UUID`` at the boundary and passed EXPLICITLY
    into ``route`` (a ``str`` must never silently compare against the UUID
    credential column and match zero rows). A missing credential propagates as
    ``CredentialNotFound`` — never ``None`` (fail-closed).
    """
    # (a) UUID coercion at the boundary (Principle 5).
    if isinstance(user_id, str):
        user_id = uuid.UUID(user_id)

    # (b) Provider/model precedence (Principle 10).
    model_map = getattr(session, "model_map", None) or {}
    override = model_map.get(role)
    if override:
        model = override
        provider = provider_of(model)
    elif session.llm_provider_pref is not None:
        provider = session.llm_provider_pref
        model = session.model_id or default_model_for(provider)
    else:
        # NULL llm_provider_pref → global switch preserved (byte-identical to the
        # legacy resolve_role_client path the scanme→nmap Ollama E2E rides on).
        provider = _provider()
        model = default_model_for(provider)

    logger.debug(
        "resolve_session_role_client role=%s provider=%s model=%s user_id=%s",
        role, provider, model, user_id,
    )

    # (c) Mint the client via the router; user_id passed EXPLICITLY as a UUID.
    from app.orchestrator.llm.router import LLMRouter  # noqa: PLC0415

    try:
        return await LLMRouter().route(db, provider, user_id=user_id)
    except CredentialNotFound:
        # Fail-closed: never degrade a missing credential to None (which would
        # let a live role fall through to its smoke fixture). PR6/PR7 depend on
        # this propagating.
        raise


def build_client_factory(
    db: AsyncSession,
    session: Any,
    actor_id: uuid.UUID | str,
):
    """Build a per-invocation ``client_factory(role_name)`` (Improvement 3).

    Bound once to the session-constant inputs ``{db, session, actor_id}``; the
    returned async callable resolves the role's client via
    ``resolve_session_role_client`` on EVERY call — there is no whole-session
    client cache (Blocking 2), so a mid-session credential revoke is honored on
    the next role invocation. Propagates ``CredentialNotFound``.
    """

    async def client_factory(role_name: str) -> Any:
        return await resolve_session_role_client(
            db, session, role_name, user_id=actor_id
        )

    return client_factory
