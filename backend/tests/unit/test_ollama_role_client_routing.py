"""PR3: provider-aware role LLM client/model routing (Ollama seam, default-OFF).

Asserts the seam mirrors the planner's provider switch: injected client wins;
osa_llm_provider="ollama" routes roles to OllamaClient; the default ("anthropic")
keeps role behavior byte-identical (nominal llm_model alias unchanged, smoke
fallback preserved for unit isolation).
"""
from __future__ import annotations

from types import SimpleNamespace

from app.core.config import settings
from app.orchestrator.roles.adviser import Adviser
from app.orchestrator.roles.generator import Generator
from app.orchestrator.roles.llm_provider import (
    resolve_role_client,
    resolve_role_llm_model,
    resolve_role_send_model,
)
from app.orchestrator.roles.pentester import Pentester


def test_default_provider_is_anthropic_and_unchanged():
    assert settings.osa_llm_provider == "anthropic"
    # No injected client → None so the role's smoke fallback runs (no network).
    assert resolve_role_client(None) is None
    assert resolve_role_llm_model() == settings.anthropic_default_model
    assert resolve_role_send_model(None) == settings.anthropic_default_model_anthropic_id
    assert resolve_role_send_model("override-id") == "override-id"


def test_injected_client_always_wins(monkeypatch):
    sentinel = object()
    assert resolve_role_client(sentinel) is sentinel
    monkeypatch.setattr(settings, "osa_llm_provider", "ollama")
    assert resolve_role_client(sentinel) is sentinel


def test_ollama_provider_routes_to_ollama_client(monkeypatch):
    monkeypatch.setattr(settings, "osa_llm_provider", "ollama")
    from app.orchestrator.ollama_client import OllamaClient

    assert isinstance(resolve_role_client(None), OllamaClient)
    assert resolve_role_llm_model() == settings.ollama_model
    assert resolve_role_send_model(None) == settings.ollama_model
    # Ollama ignores an anthropic context override.
    assert resolve_role_send_model("ignored-for-ollama") == settings.ollama_model


def test_role_constructors_follow_provider(monkeypatch):
    # Default anthropic → the legacy alias (byte-identical).
    assert Generator().llm_model == settings.anthropic_default_model
    assert Pentester().llm_model == settings.anthropic_default_model
    assert Adviser().llm_model == settings.anthropic_default_model
    # Ollama → the configured ollama model.
    monkeypatch.setattr(settings, "osa_llm_provider", "ollama")
    assert Generator().llm_model == settings.ollama_model
    assert Pentester().llm_model == settings.ollama_model
    assert Adviser().llm_model == settings.ollama_model


async def test_generator_smoke_fallback_preserved_under_default():
    """Default anthropic + no injected client → deterministic smoke fixture."""
    result = await Generator().run(
        performer=None, context={"user_content": "scan example.com"}
    )
    assert result.finished is False
    assert "fallback envelope" in result.messages[0]["content"]


async def test_generator_uses_injected_client_over_ollama(monkeypatch):
    """An injected client is used even when provider=ollama (per-user path wins)."""
    monkeypatch.setattr(settings, "osa_llm_provider", "ollama")

    class _FakeClient:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def send(self, model_id, messages, system):  # noqa: ANN001
            self.calls.append(model_id)
            return SimpleNamespace(text="ok", tokens_in=1, tokens_out=1)

    fake = _FakeClient()
    result = await Generator().run(
        performer=None,
        context={"user_content": "x", "model_client": fake},
    )
    assert result.messages[0]["content"] == "ok"
    # Provider=ollama → send model resolves to the ollama model.
    assert fake.calls == [settings.ollama_model]
