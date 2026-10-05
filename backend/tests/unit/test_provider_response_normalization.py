"""Tests that each provider normalises its SDK response to the shared Response dataclass (PR1.1)."""
from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.orchestrator.model_client import Response
import app.orchestrator.llm.anthropic_provider as anthropic_provider
from app.orchestrator.llm.anthropic_provider import AnthropicProvider
from app.orchestrator.llm.google_provider import GoogleProvider
from app.orchestrator.llm.openai_provider import OpenAIProvider


# ---------------------------------------------------------------------------
# Anthropic provider
# ---------------------------------------------------------------------------

async def test_anthropic_provider_normalises_response(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_usage = MagicMock(input_tokens=10, output_tokens=20)
    fake_content_block = MagicMock()
    fake_content_block.type = "text"
    fake_content_block.text = "hello from anthropic"
    fake_msg = MagicMock()
    fake_msg.content = [fake_content_block]
    fake_msg.usage = fake_usage

    fake_async_client = MagicMock()
    fake_async_client.messages.create = AsyncMock(return_value=fake_msg)

    constructor = MagicMock(return_value=fake_async_client)
    monkeypatch.setattr(anthropic_provider.anthropic, "AsyncAnthropic", constructor)

    provider = AnthropicProvider(api_key="fake")
    resp = await provider.send(
        model_id="claude-3-5-sonnet-20241022", messages=[{"role": "user", "content": "hi"}]
    )

    constructor.assert_called_once_with(api_key="fake")
    fake_async_client.messages.create.assert_awaited_once_with(
        model="claude-3-5-sonnet-20241022",
        max_tokens=4096,
        messages=[{"role": "user", "content": "hi"}],
    )
    assert isinstance(resp, Response)
    assert resp.text == "hello from anthropic"
    assert resp.tokens_in == 10
    assert resp.tokens_out == 20
    assert resp.raw is fake_msg


# ---------------------------------------------------------------------------
# OpenAI provider
# ---------------------------------------------------------------------------

async def test_openai_provider_normalises_response(monkeypatch: pytest.MonkeyPatch) -> None:
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

    constructor = MagicMock(return_value=fake_async_openai)
    fake_openai = SimpleNamespace(
        AsyncOpenAI=constructor,
        APIConnectionError=ConnectionError,
        APITimeoutError=TimeoutError,
        APIStatusError=Exception,
    )

    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    provider = OpenAIProvider(api_key="fake")
    resp = await provider.send(
        model_id="gpt-4o", messages=[{"role": "user", "content": "hi"}]
    )

    constructor.assert_called_once_with(api_key="fake")
    fake_async_openai.chat.completions.create.assert_awaited_once_with(
        model="gpt-4o", max_tokens=4096, messages=[{"role": "user", "content": "hi"}]
    )
    assert isinstance(resp, Response)
    assert resp.text == "hello from openai"
    assert resp.tokens_in == 5
    assert resp.tokens_out == 15
    assert resp.raw is fake_completion


# ---------------------------------------------------------------------------
# Google provider
# ---------------------------------------------------------------------------

async def test_google_provider_normalises_response(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_usage = MagicMock()
    fake_usage.prompt_token_count = 8
    fake_usage.candidates_token_count = 12

    fake_resp = MagicMock()
    fake_resp.text = "hello from google"
    fake_resp.usage_metadata = fake_usage

    fake_model_instance = MagicMock()
    fake_model_instance.generate_content_async = AsyncMock(return_value=fake_resp)

    configure = MagicMock()
    constructor = MagicMock(return_value=fake_model_instance)
    fake_genai = SimpleNamespace(configure=configure, GenerativeModel=constructor)
    fake_google = SimpleNamespace(generativeai=fake_genai)

    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.generativeai", fake_genai)

    provider = GoogleProvider(api_key="fake")
    resp = await provider.send(
        model_id="gemini-1.5-pro", messages=[{"role": "user", "content": "hi"}]
    )

    configure.assert_called_once_with(api_key="fake")
    constructor.assert_called_once_with("gemini-1.5-pro")
    fake_model_instance.generate_content_async.assert_awaited_once_with("User: hi")
    assert isinstance(resp, Response)
    assert resp.text == "hello from google"
    assert resp.tokens_in == 8
    assert resp.tokens_out == 12
    assert resp.raw is fake_resp
