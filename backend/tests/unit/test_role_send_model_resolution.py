"""FIX (session 09484046): the autonomous Performer's roles must send a model the
SESSION's provider actually serves. The bug: the role CLIENT was resolved from the
session provider (copilot) but the send-MODEL defaulted to an Anthropic id, so a
copilot client got an Anthropic id -> Copilot 400 model_not_supported -> the
tool-dispatching Pentester role failed -> 0 executions. resolve_session_role_send_model
mirrors resolve_session_role_client's precedence so client + send-model stay coherent.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.orchestrator.roles import llm_provider as lp


def _session(*, provider=None, model_id=None, model_map=None):
    return SimpleNamespace(llm_provider_pref=provider, model_id=model_id, model_map=model_map)


def test_copilot_session_sends_copilot_model_never_anthropic():
    s = _session(provider="copilot", model_id="copilot/claude-sonnet-5")
    got = lp.resolve_session_role_send_model(s, "pentester")
    assert got == "copilot/claude-sonnet-5"
    assert "claude-sonnet-4-6" not in got  # never the anthropic default id


def test_ollama_session_sends_ollama_model():
    s = _session(provider="ollama", model_id=None)
    assert lp.resolve_session_role_send_model(s, "generator") == settings.ollama_model


def test_anthropic_alias_maps_to_vendor_id():
    s = _session(provider="anthropic", model_id=settings.anthropic_default_model)
    assert (
        lp.resolve_session_role_send_model(s, "pentester")
        == settings.anthropic_default_model_anthropic_id
    )


def test_per_role_model_map_override_is_honored():
    s = _session(
        provider="copilot",
        model_id="copilot/claude-sonnet-5",
        model_map={"reporter": "copilot/gpt-4.1"},
    )
    assert lp.resolve_session_role_send_model(s, "reporter") == "copilot/gpt-4.1"
    # a role without a model_map entry falls back to the session model
    assert lp.resolve_session_role_send_model(s, "pentester") == "copilot/claude-sonnet-5"


def test_null_provider_uses_global_switch(monkeypatch):
    monkeypatch.setattr(settings, "osa_llm_provider", "ollama")
    s = _session(provider=None, model_id=None)
    assert lp.resolve_session_role_send_model(s, "pentester") == settings.ollama_model


@pytest.mark.asyncio
async def test_generator_uses_send_model_resolver_over_anthropic_default():
    """Role-level regression: with a send_model_resolver in context (autonomous
    lane) and NO send_model_id, the Generator sends the resolver's copilot model,
    not the Anthropic default that caused the 400."""
    from app.orchestrator.roles.generator import Generator

    resp = SimpleNamespace(
        text='{"ambiguity":0.1,"blockers":[],"reasoning":"","draft_plan":{"steps":[]}}',
        tokens_in=1, tokens_out=1,
    )
    client = SimpleNamespace(send=AsyncMock(return_value=resp))

    async def factory(_role):
        return client

    session = _session(provider="copilot", model_id="copilot/claude-sonnet-5")
    await Generator().run(
        performer=None,
        context={
            "user_content": "scan",
            "history": [],
            "send_model_resolver": lp.build_send_model_resolver(session),
        },
        client_factory=factory,
    )
    client.send.assert_awaited_once()
    assert client.send.await_args.kwargs["model_id"] == "copilot/claude-sonnet-5"
