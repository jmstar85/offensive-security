"""Unit tests for LLMRouter.get_client() (PR1.1)."""
from __future__ import annotations

import pytest

from app.orchestrator.llm.router import LLMRouter
from app.orchestrator.llm.anthropic_provider import AnthropicProvider
from app.orchestrator.llm.openai_provider import OpenAIProvider
from app.orchestrator.llm.google_provider import GoogleProvider


@pytest.fixture()
def router() -> LLMRouter:
    return LLMRouter()


def test_get_client_anthropic(router: LLMRouter, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.orchestrator.llm.anthropic_provider.anthropic.AsyncAnthropic",
        lambda api_key: object(),
    )
    client = router.get_client("anthropic", api_key="test-key")
    assert isinstance(client, AnthropicProvider)


def test_get_client_openai(router: LLMRouter, monkeypatch: pytest.MonkeyPatch) -> None:
    import types

    fake_openai = types.ModuleType("openai")
    fake_openai.AsyncOpenAI = lambda api_key: object()  # type: ignore[attr-defined]

    import sys
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    # Re-instantiate so the lazy import picks up our stub.
    class _StubOpenAIProvider(OpenAIProvider):
        def __init__(self, api_key: str) -> None:
            # bypass real import
            self._openai = fake_openai
            self._client = fake_openai.AsyncOpenAI(api_key=api_key)

    monkeypatch.setattr(
        "app.orchestrator.llm.router.OpenAIProvider",
        _StubOpenAIProvider,
        raising=False,
    )
    # Also patch in the router module's lazy import path.
    import app.orchestrator.llm.router as router_mod
    monkeypatch.setattr(router_mod, "LLMRouter", LLMRouter, raising=False)

    client = router.get_client("openai", api_key="test-key")
    assert isinstance(client, OpenAIProvider)


def test_get_client_google(router: LLMRouter, monkeypatch: pytest.MonkeyPatch) -> None:
    import types
    import sys

    fake_genai = types.ModuleType("google.generativeai")
    fake_genai.configure = lambda api_key: None  # type: ignore[attr-defined]
    fake_google = types.ModuleType("google")
    fake_google.generativeai = fake_genai  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.generativeai", fake_genai)

    class _StubGoogleProvider(GoogleProvider):
        def __init__(self, api_key: str) -> None:
            self._genai = fake_genai

    monkeypatch.setattr(
        "app.orchestrator.llm.router.GoogleProvider",
        _StubGoogleProvider,
        raising=False,
    )

    client = router.get_client("google", api_key="test-key")
    assert isinstance(client, GoogleProvider)


def test_get_client_unknown_raises(router: LLMRouter) -> None:
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        router.get_client("cohere", api_key="test-key")
