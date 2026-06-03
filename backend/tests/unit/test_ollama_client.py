"""Unit tests for the Ollama planner client + provider-aware AttackPlanner."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from app.orchestrator.model_client import ModelUnreachable, Response


class _FakeResp:
    def __init__(self, payload: dict, status: int = 200):
        self._payload = payload
        self.status_code = status
        self.text = ""

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("err", request=MagicMock(), response=self)

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """Stand-in for httpx.AsyncClient capturing the POST payload."""

    last_url = None
    last_json = None
    resp_payload: dict = {}
    raise_exc: BaseException | None = None

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None):
        type(self).last_url = url
        type(self).last_json = json
        if type(self).raise_exc is not None:
            raise type(self).raise_exc
        return _FakeResp(type(self).resp_payload)


def _patch_client(monkeypatch, payload=None, raise_exc=None):
    import app.orchestrator.ollama_client as mod
    _FakeAsyncClient.resp_payload = payload or {}
    _FakeAsyncClient.raise_exc = raise_exc
    _FakeAsyncClient.last_url = None
    _FakeAsyncClient.last_json = None
    monkeypatch.setattr(mod.httpx, "AsyncClient", _FakeAsyncClient)


def test_send_builds_json_format_payload(monkeypatch):
    from app.orchestrator.ollama_client import OllamaClient

    _patch_client(monkeypatch, payload={
        "message": {"content": '{"ok": true}'},
        "prompt_eval_count": 11, "eval_count": 22,
    })
    client = OllamaClient(base_url="http://h:11434", model="qwen3-14b-96k:latest")
    resp = asyncio.run(client.send(
        model_id="qwen3-14b-96k:latest",
        messages=[{"role": "user", "content": "hi"}],
        system="SYS",
    ))
    assert isinstance(resp, Response)
    assert resp.text == '{"ok": true}'
    # format=json is mandatory so the planner's json.loads always succeeds
    assert _FakeAsyncClient.last_json["format"] == "json"
    assert _FakeAsyncClient.last_json["stream"] is False
    assert _FakeAsyncClient.last_url == "http://h:11434/api/chat"


def test_send_prepends_system_message(monkeypatch):
    from app.orchestrator.ollama_client import OllamaClient

    _patch_client(monkeypatch, payload={"message": {"content": "{}"}})
    client = OllamaClient(base_url="http://h:11434", model="m")
    asyncio.run(client.send(model_id="m", messages=[{"role": "user", "content": "u"}], system="SYS"))
    msgs = _FakeAsyncClient.last_json["messages"]
    assert msgs[0] == {"role": "system", "content": "SYS"}
    assert msgs[1] == {"role": "user", "content": "u"}


def test_send_strips_think_block(monkeypatch):
    from app.orchestrator.ollama_client import OllamaClient

    _patch_client(monkeypatch, payload={
        "message": {"content": '<think>reasoning…</think>{"steps": []}'},
    })
    client = OllamaClient(base_url="http://h:11434", model="m")
    resp = asyncio.run(client.send(model_id="m", messages=[{"role": "user", "content": "u"}], system=""))
    assert resp.text == '{"steps": []}'


def test_send_maps_token_counts(monkeypatch):
    from app.orchestrator.ollama_client import OllamaClient

    _patch_client(monkeypatch, payload={
        "message": {"content": "{}"}, "prompt_eval_count": 7, "eval_count": 13,
    })
    client = OllamaClient(base_url="http://h:11434", model="m")
    resp = asyncio.run(client.send(model_id="m", messages=[], system=""))
    assert resp.tokens_in == 7
    assert resp.tokens_out == 13


def test_send_connect_error_raises_model_unreachable(monkeypatch):
    import httpx
    from app.orchestrator.ollama_client import OllamaClient

    _patch_client(monkeypatch, raise_exc=httpx.ConnectError("refused"))
    client = OllamaClient(base_url="http://h:11434", model="m")
    with pytest.raises(ModelUnreachable):
        asyncio.run(client.send(model_id="m", messages=[], system=""))


def test_planner_uses_ollama_when_provider_ollama(monkeypatch):
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "osa_llm_provider", "ollama")
    from app.orchestrator.planner import AttackPlanner
    from app.orchestrator.ollama_client import OllamaClient

    planner = AttackPlanner()
    assert isinstance(planner._client, OllamaClient)
    assert planner._provider == "ollama"


def test_planner_uses_modelclient_by_default(monkeypatch):
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "osa_llm_provider", "anthropic")
    from app.orchestrator.planner import AttackPlanner
    from app.orchestrator.model_client import ModelClient

    planner = AttackPlanner()
    assert isinstance(planner._client, ModelClient)
    assert planner._provider == "anthropic"


def test_planner_injected_client_overrides_provider(monkeypatch):
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "osa_llm_provider", "ollama")
    from app.orchestrator.planner import AttackPlanner

    injected = MagicMock()
    planner = AttackPlanner(model_client=injected)
    assert planner._client is injected
    assert planner._provider == "anthropic"
