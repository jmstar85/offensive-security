"""Unit tests for PR4.1 — OSA_TRAFFIC_VIA_MITM flag wiring on AttackAgent."""
from __future__ import annotations

import pytest

from app.orchestrator.roles.seed_xbow import (
    AttackAgent,
    DiscoveryAgent,
    SessionManagementAgent,
    AttackVector,
)


def _role_args(name: str) -> dict:
    return {"name": name, "system_prompt": "", "llm_model": "claude-sonnet-4-6"}


@pytest.fixture()
def attack_agent():
    return AttackAgent(**_role_args("attack_agent"))


@pytest.mark.asyncio
async def test_attack_agent_uses_direct_egress_when_flag_off(attack_agent, monkeypatch):
    from app.core import config as config_mod
    monkeypatch.setattr(config_mod.settings, "osa_traffic_via_mitm", False)
    context: dict = {}
    result = await attack_agent.run(performer=None, context=context)
    content = result.messages[0]["content"]
    assert "egress_via_mitm=False" in content
    assert "proxy=direct" in content
    assert "_attack_agent_egress_proxy" not in context


@pytest.mark.asyncio
async def test_attack_agent_routes_via_mitm_when_flag_on(attack_agent, monkeypatch):
    from app.core import config as config_mod
    monkeypatch.setattr(config_mod.settings, "osa_traffic_via_mitm", True)
    monkeypatch.delenv("OSA_MITM_PROXY_URL", raising=False)
    context: dict = {}
    result = await attack_agent.run(performer=None, context=context)
    content = result.messages[0]["content"]
    assert "egress_via_mitm=True" in content
    assert "proxy=http://mitmproxy:8080" in content
    assert context["_attack_agent_egress_proxy"] == "http://mitmproxy:8080"


@pytest.mark.asyncio
async def test_attack_agent_honors_OSA_MITM_PROXY_URL_env(attack_agent, monkeypatch):
    from app.core import config as config_mod
    monkeypatch.setattr(config_mod.settings, "osa_traffic_via_mitm", True)
    monkeypatch.setenv("OSA_MITM_PROXY_URL", "http://custom:1234")
    context: dict = {}
    result = await attack_agent.run(performer=None, context=context)
    content = result.messages[0]["content"]
    assert "proxy=http://custom:1234" in content
    assert context["_attack_agent_egress_proxy"] == "http://custom:1234"


@pytest.mark.asyncio
async def test_discovery_agent_never_routes_via_mitm(monkeypatch):
    from app.core import config as config_mod
    monkeypatch.setattr(config_mod.settings, "osa_traffic_via_mitm", True)
    agent = DiscoveryAgent(**_role_args("discovery_agent"))
    context: dict = {}
    await agent.run(performer=None, context=context)
    assert "_attack_agent_egress_proxy" not in context


@pytest.mark.asyncio
async def test_session_management_agent_never_routes_via_mitm(monkeypatch):
    from app.core import config as config_mod
    monkeypatch.setattr(config_mod.settings, "osa_traffic_via_mitm", True)
    agent = SessionManagementAgent(**_role_args("session_management_agent"))
    context: dict = {}
    await agent.run(performer=None, context=context)
    assert "_attack_agent_egress_proxy" not in context


@pytest.mark.asyncio
async def test_attack_agent_emits_egress_decision_in_message(attack_agent, monkeypatch):
    from app.core import config as config_mod
    monkeypatch.setattr(config_mod.settings, "osa_traffic_via_mitm", False)
    context: dict = {}
    result = await attack_agent.run(performer=None, context=context)
    assert "egress_via_mitm=" in result.messages[0]["content"]
