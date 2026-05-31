"""Tests that each provider normalises its SDK response to the shared Response dataclass (PR1.1)."""
from __future__ import annotations

import types
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.orchestrator.model_client import Response


# ---------------------------------------------------------------------------
# Anthropic provider
# ---------------------------------------------------------------------------

def test_anthropic_provider_normalises_response(monkeypatch: pytest.MonkeyPatch) -> None:
    import anthropic as _anthropic

    fake_usage = MagicMock(input_tokens=10, output_tokens=20)
    fake_content_block = MagicMock()
    fake_content_block.type = "text"
    fake_content_block.text = "hello from anthropic"
    fake_msg = MagicMock()
    fake_msg.content = [fake_content_block]
    fake_msg.usage = fake_usage

    fake_async_client = MagicMock()
    fake_async_client.messages.create = AsyncMock(return_value=fake_msg)

    monkeypatch.setattr(
        _anthropic, "AsyncAnthropic", lambda api_key: fake_async_client
    )

    from app.orchestrator.llm.anthropic_provider import AnthropicProvider
    import importlib
    import app.orchestrator.llm.anthropic_provider as _mod
    importlib.reload(_mod)

    provider = _mod.AnthropicProvider(api_key="fake")
    provider._client = fake_async_client

    import asyncio
    resp = asyncio.run(
        provider.send(model_id="claude-3-5-sonnet-20241022", messages=[{"role": "user", "content": "hi"}])
    )

    assert isinstance(resp, Response)
    assert resp.text == "hello from anthropic"
    assert resp.tokens_in == 10
    assert resp.tokens_out == 20


# ---------------------------------------------------------------------------
# OpenAI provider
# ---------------------------------------------------------------------------

def test_openai_provider_normalises_response(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_openai = types.ModuleType("openai")

    fake_choice_message = MagicMock()
    fake_choice_message.content = "hello from openai"
    fake_choice_message.tool_calls = None

    fake_choice = MagicMock()
    fake_choice.message = fake_choice_message

    fake_usage = MagicMock()
    fake_usage.prompt_tokens = 5
    fake_usage.completion_tokens = 15

    fake_completion = MagicMock()
    fake_completion.choices = [fake_choice]
    fake_completion.usage = fake_usage
    fake_completion.model = "gpt-4o"

    fake_async_openai = MagicMock()
    fake_async_openai.chat = MagicMock()
    fake_async_openai.chat.completions = MagicMock()
    fake_async_openai.chat.completions.create = AsyncMock(return_value=fake_completion)

    fake_openai.AsyncOpenAI = lambda api_key: fake_async_openai  # type: ignore[attr-defined]
    fake_openai.APIConnectionError = ConnectionError  # type: ignore[attr-defined]
    fake_openai.APITimeoutError = TimeoutError  # type: ignore[attr-defined]
    fake_openai.APIStatusError = Exception  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    from app.orchestrator.llm.openai_provider import OpenAIProvider

    provider = OpenAIProvider.__new__(OpenAIProvider)
    provider._openai = fake_openai
    provider._client = fake_async_openai

    import asyncio
    resp = asyncio.run(
        provider.send(model_id="gpt-4o", messages=[{"role": "user", "content": "hi"}])
    )

    assert isinstance(resp, Response)
    assert resp.text == "hello from openai"
    assert resp.tokens_in == 5
    assert resp.tokens_out == 15


# ---------------------------------------------------------------------------
# Google provider
# ---------------------------------------------------------------------------

def test_google_provider_normalises_response(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_genai = types.ModuleType("google.generativeai")

    fake_usage = MagicMock()
    fake_usage.prompt_token_count = 8
    fake_usage.candidates_token_count = 12

    fake_resp = MagicMock()
    fake_resp.text = "hello from google"
    fake_resp.usage_metadata = fake_usage

    fake_model_instance = MagicMock()
    fake_model_instance.generate_content_async = AsyncMock(return_value=fake_resp)

    fake_genai.configure = lambda api_key: None  # type: ignore[attr-defined]
    fake_genai.GenerativeModel = lambda model_id: fake_model_instance  # type: ignore[attr-defined]

    fake_google = types.ModuleType("google")
    fake_google.generativeai = fake_genai  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.generativeai", fake_genai)

    from app.orchestrator.llm.google_provider import GoogleProvider

    provider = GoogleProvider.__new__(GoogleProvider)
    provider._genai = fake_genai

    import asyncio
    resp = asyncio.run(
        provider.send(model_id="gemini-1.5-pro", messages=[{"role": "user", "content": "hi"}])
    )

    assert isinstance(resp, Response)
    assert resp.text == "hello from google"
    assert resp.tokens_in == 8
    assert resp.tokens_out == 12
