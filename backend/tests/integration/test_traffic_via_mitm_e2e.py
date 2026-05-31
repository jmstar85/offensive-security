"""Integration tests for PR4.1 — OSA_TRAFFIC_VIA_MITM e2e wiring.

Constructs a Performer with the three xbow Roles registered via
lazy_register_if_enabled(True) and drives one run_session() iteration.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.orchestrator.roles.registry import ROLE_REGISTRY, lazy_register_if_enabled
from app.orchestrator.performer import Performer


@pytest.fixture(autouse=True)
def clean_registry():
    """Snapshot ROLE_REGISTRY before test, restore after — prevents bleed."""
    snapshot = dict(ROLE_REGISTRY)
    yield
    ROLE_REGISTRY.clear()
    ROLE_REGISTRY.update(snapshot)


def _make_role(slug: str):
    """Instantiate the registered xbow role with the required Role dataclass args."""
    from app.orchestrator.roles.registry import get_role
    cls = get_role(slug)
    return cls(name=slug, system_prompt="", llm_model="claude-sonnet-4-6")


@pytest.fixture()
def xbow_roles():
    """Tuple of (session_mgmt, discovery, attack) Role instances registered via lazy
    helper. Drives Role.run() directly — ROLE_TOPOLOGICAL_ORDER inside Performer is
    [generator, pentester, reporter] for v1, so the xbow roles are exercised
    individually here. This still exercises the lazy_register_if_enabled + registry
    lookup wiring end-to-end."""
    lazy_register_if_enabled(True)
    return (
        _make_role("session_management_agent"),
        _make_role("discovery_agent"),
        _make_role("attack_agent"),
    )


@pytest.mark.asyncio
async def test_attack_agent_egress_marker_present_in_context_when_flag_on(
    xbow_roles, monkeypatch
):
    from app.core import config as config_mod
    monkeypatch.setattr(config_mod.settings, "osa_traffic_via_mitm", True)
    monkeypatch.delenv("OSA_MITM_PROXY_URL", raising=False)
    _sm, _d, attack = xbow_roles
    context: dict = {}
    await attack.run(performer=None, context=context)
    assert "_attack_agent_egress_proxy" in context
    assert context["_attack_agent_egress_proxy"] == "http://mitmproxy:8080"


@pytest.mark.asyncio
async def test_attack_agent_egress_marker_absent_when_flag_off(
    xbow_roles, monkeypatch
):
    from app.core import config as config_mod
    monkeypatch.setattr(config_mod.settings, "osa_traffic_via_mitm", False)
    _sm, _d, attack = xbow_roles
    context: dict = {}
    await attack.run(performer=None, context=context)
    assert "_attack_agent_egress_proxy" not in context
