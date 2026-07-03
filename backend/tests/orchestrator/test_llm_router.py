"""LLMRouter Ollama short-circuit + fresh-lookup contract (PR3).

Covers:
- ``get_client("ollama")`` returns an ``OllamaClient`` with a defaulted api_key
  and performs NO credential lookup.
- ``route("ollama")`` short-circuits before any ``resolve_provider_credential``.
- ``route("anthropic")`` still resolves a credential.
- ``route`` issues a FRESH DB lookup on every call (no cache): a
  revoked-then-recreated credential is honored on the next call.
"""
from __future__ import annotations

import pytest

from app.orchestrator.llm import credential_resolver as cred_mod
from app.orchestrator.llm.credential_resolver import CredentialNotFound
from app.orchestrator.llm.router import LLMRouter
from app.orchestrator.ollama_client import OllamaClient


@pytest.fixture()
def router() -> LLMRouter:
    return LLMRouter()


def test_get_client_ollama_returns_client_without_credential_lookup(
    router: LLMRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list = []

    async def _spy(*args, **kwargs):  # pragma: no cover - must not run
        calls.append((args, kwargs))
        return "should-not-be-called"

    monkeypatch.setattr(cred_mod, "resolve_provider_credential", _spy)

    client = router.get_client("ollama")  # api_key defaulted to ""
    assert isinstance(client, OllamaClient)
    assert calls == []  # ollama never triggers a credential lookup


@pytest.mark.asyncio
async def test_route_ollama_short_circuits_no_credential_lookup(
    router: LLMRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list = []

    async def _spy(*args, **kwargs):  # pragma: no cover - must not run
        calls.append((args, kwargs))
        return "unused"

    monkeypatch.setattr(cred_mod, "resolve_provider_credential", _spy)

    client = await router.route(db=None, provider="ollama")
    assert isinstance(client, OllamaClient)
    assert calls == []  # short-circuited BEFORE resolve_provider_credential


@pytest.mark.asyncio
async def test_route_anthropic_resolves_a_credential(
    router: LLMRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolved: list[str] = []

    async def _spy(db, provider, user_id=None):
        resolved.append(provider)
        return "sk-test-key"

    monkeypatch.setattr(cred_mod, "resolve_provider_credential", _spy)
    # Avoid constructing the real Anthropic SDK client.
    sentinel = object()
    monkeypatch.setattr(router, "get_client", lambda provider, api_key="": sentinel)

    result = await router.route(db=None, provider="anthropic")
    assert result is sentinel
    assert resolved == ["anthropic"]  # anthropic DOES resolve a credential


@pytest.mark.asyncio
async def test_route_fresh_lookup_per_call_no_cache(
    router: LLMRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A revoked-then-recreated credential is honored on the next route() call:
    route() consults the resolver freshly every call — it never caches."""
    outcomes: list = [
        CredentialNotFound("revoked"),  # 1st call: credential revoked
        "sk-recreated-key",             # 2nd call: recreated
    ]
    seen: list[str] = []

    async def _spy(db, provider, user_id=None):
        seen.append(provider)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(cred_mod, "resolve_provider_credential", _spy)
    sentinel = object()
    monkeypatch.setattr(router, "get_client", lambda provider, api_key="": sentinel)

    # 1st call: credential missing → raises (fresh lookup).
    with pytest.raises(CredentialNotFound):
        await router.route(db=None, provider="anthropic")

    # 2nd call: credential recreated → resolved (fresh lookup, no cache).
    result = await router.route(db=None, provider="anthropic")
    assert result is sentinel
    assert seen == ["anthropic", "anthropic"]  # resolver hit on EVERY call
