"""Unit tests for the GitHub Copilot provider + routing wiring.

No real network calls — httpx.AsyncClient is patched with scripted responses.
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from app.orchestrator.llm.base import ModelUnreachable
from app.orchestrator.llm.copilot_provider import CopilotProvider, strip_copilot_prefix
from app.orchestrator.llm.router import LLMRouter
from app.orchestrator.roles.llm_provider import default_model_for, provider_of


class _Resp:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


def _fake_client(get_resp=None, post_resp=None):
    class _C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            if isinstance(get_resp, Exception):
                raise get_resp
            return get_resp

        async def post(self, *a, **k):
            if isinstance(post_resp, Exception):
                raise post_resp
            return post_resp

    return _C


def test_strip_copilot_prefix():
    assert strip_copilot_prefix("copilot/gpt-4o") == "gpt-4o"
    assert strip_copilot_prefix("copilot/claude-3.5-sonnet") == "claude-3.5-sonnet"
    assert strip_copilot_prefix("gpt-4o") == "gpt-4o"  # bare id passes through


def test_provider_of_copilot():
    assert provider_of("copilot/gpt-4o") == "copilot"
    assert provider_of("copilot/claude-3.5-sonnet") == "copilot"
    # bare ids still map to their real provider — the copilot/ namespace is what
    # marks a Copilot session.
    assert provider_of("gpt-4o") == "openai"
    assert provider_of("claude-opus-4-8") == "anthropic"


def test_default_model_for_copilot():
    assert default_model_for("copilot") == "copilot/gpt-4.1"


def test_router_get_client_copilot():
    assert isinstance(LLMRouter().get_client("copilot", api_key="ghtok"), CopilotProvider)


@pytest.mark.asyncio
async def test_copilot_send_success_strips_prefix_and_normalizes():
    token_resp = _Resp(200, {"token": "cop_tok", "expires_at": time.time() + 1000})
    chat_resp = _Resp(200, {
        "choices": [{"message": {"content": "pong"}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2},
    })
    with patch(
        "app.orchestrator.llm.copilot_provider.httpx.AsyncClient",
        _fake_client(token_resp, chat_resp),
    ):
        provider = CopilotProvider(api_key="ghtok")
        resp = await provider.send("copilot/gpt-4o", [{"role": "user", "content": "ping"}])
    assert resp.text == "pong"
    assert resp.tokens_in == 5
    assert resp.tokens_out == 2


@pytest.mark.asyncio
async def test_copilot_token_exchange_401_raises_unreachable():
    with patch(
        "app.orchestrator.llm.copilot_provider.httpx.AsyncClient",
        _fake_client(_Resp(401), None),
    ):
        provider = CopilotProvider(api_key="badtok")
        with pytest.raises(ModelUnreachable):
            await provider.send("copilot/gpt-4o", [{"role": "user", "content": "x"}])


@pytest.mark.asyncio
async def test_copilot_chat_5xx_raises_unreachable():
    token_resp = _Resp(200, {"token": "cop_tok", "expires_at": time.time() + 1000})
    with patch(
        "app.orchestrator.llm.copilot_provider.httpx.AsyncClient",
        _fake_client(token_resp, _Resp(503)),
    ):
        provider = CopilotProvider(api_key="ghtok")
        with pytest.raises(ModelUnreachable):
            await provider.send("copilot/gpt-4o", [{"role": "user", "content": "x"}])
