"""GET /config/ollama/models — live Ollama model list (newflow PR8).

Covers:
    - route registered on the FastAPI app
    - success: proxies Ollama's /api/tags, returns model names + reachable=true
    - httpx.ConnectError / timeout: falls back to settings.ollama_model with
      reachable=false (never a hard 500, so the provider selector stays usable)
    - Ollama reachable but returns an empty/malformed model list: falls back
      to settings.ollama_model, reachable stays true (Ollama itself answered)
    - Ollama reachable but 4xx/5xx: treated as unreachable for UI purposes
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from app.models.user import UserRole


def _user(role=UserRole.MEMBER):
    return SimpleNamespace(
        id=uuid.uuid4(),
        email="op@example.com",
        full_name="Op",
        role=role,
        is_active=True,
        team_id=uuid.uuid4(),
    )


class _FakeResp:
    def __init__(self, payload: dict, status: int = 200):
        self._payload = payload
        self.status_code = status
        self.text = ""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=MagicMock(), response=self)

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """Stand-in for httpx.AsyncClient capturing the GET url."""

    last_url = None
    resp_payload: dict = {}
    resp_status = 200
    raise_exc: BaseException | None = None

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url):
        type(self).last_url = url
        if type(self).raise_exc is not None:
            raise type(self).raise_exc
        return _FakeResp(type(self).resp_payload, type(self).resp_status)


def _patch_client(monkeypatch, payload=None, status=200, raise_exc=None):
    import app.api.v1.ollama_models as mod

    _FakeAsyncClient.resp_payload = payload or {}
    _FakeAsyncClient.resp_status = status
    _FakeAsyncClient.raise_exc = raise_exc
    _FakeAsyncClient.last_url = None
    monkeypatch.setattr(mod.httpx, "AsyncClient", _FakeAsyncClient)


def test_ollama_models_route_registered():
    from app.main import app

    paths = [r.path for r in app.routes]
    assert "/api/v1/config/ollama/models" in paths


@pytest.mark.asyncio
async def test_ollama_models_success_returns_names_and_reachable_true(monkeypatch):
    from app.api.v1.ollama_models import get_ollama_models
    from app.core import config

    monkeypatch.setattr(config.settings, "ollama_base_url", "http://h:11434")
    _patch_client(
        monkeypatch,
        payload={
            "models": [
                {"name": "qwen3-14b-96k:latest"},
                {"name": "llama3:8b"},
            ]
        },
    )

    result = await get_ollama_models(current_user=_user())

    assert result == {
        "models": ["qwen3-14b-96k:latest", "llama3:8b"],
        "reachable": True,
    }
    assert _FakeAsyncClient.last_url == "http://h:11434/api/tags"


@pytest.mark.asyncio
async def test_ollama_models_connect_error_falls_back(monkeypatch):
    from app.api.v1.ollama_models import get_ollama_models
    from app.core import config

    monkeypatch.setattr(config.settings, "ollama_model", "qwen3-14b-96k:latest")
    _patch_client(monkeypatch, raise_exc=httpx.ConnectError("refused"))

    result = await get_ollama_models(current_user=_user())

    assert result == {"models": ["qwen3-14b-96k:latest"], "reachable": False}


@pytest.mark.asyncio
async def test_ollama_models_timeout_falls_back(monkeypatch):
    from app.api.v1.ollama_models import get_ollama_models
    from app.core import config

    monkeypatch.setattr(config.settings, "ollama_model", "qwen3-14b-96k:latest")
    _patch_client(monkeypatch, raise_exc=httpx.ConnectTimeout("timed out"))

    result = await get_ollama_models(current_user=_user())

    assert result == {"models": ["qwen3-14b-96k:latest"], "reachable": False}


@pytest.mark.asyncio
async def test_ollama_models_empty_list_falls_back_but_stays_reachable(monkeypatch):
    from app.api.v1.ollama_models import get_ollama_models
    from app.core import config

    monkeypatch.setattr(config.settings, "ollama_model", "qwen3-14b-96k:latest")
    _patch_client(monkeypatch, payload={"models": []})

    result = await get_ollama_models(current_user=_user())

    assert result == {"models": ["qwen3-14b-96k:latest"], "reachable": True}


@pytest.mark.asyncio
async def test_ollama_models_http_error_treated_as_unreachable(monkeypatch):
    from app.api.v1.ollama_models import get_ollama_models
    from app.core import config

    monkeypatch.setattr(config.settings, "ollama_model", "qwen3-14b-96k:latest")
    _patch_client(monkeypatch, payload={}, status=500)

    result = await get_ollama_models(current_user=_user())

    assert result == {"models": ["qwen3-14b-96k:latest"], "reachable": False}
