"""PR6: dispatch is driven by the Understanding (target_kind/AttackVector), not by
hardcoded phases. The PlanOfWork phases + family palettes differ per target, and the
family roles dispatch their vector palette through the safety-wired delegator.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.base import AgentEvent
from app.orchestrator.coordinator import CoordinatorService, UnderstandingOfTarget
from app.orchestrator.performer import Performer
from app.orchestrator.roles.seed_xbow import DiscoveryAgent


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()

    async def _flush() -> None:
        pass

    db.flush = _flush
    db.execute = AsyncMock()
    return db


def _bound_performer(*, approval_flags=None) -> Performer:
    p = Performer(_mock_db(), uuid.uuid4())
    p.bind_live_execution(
        target={"ip_ranges": [], "domains": []},
        approval_flags=approval_flags or {"approved_active_recon": True},
        whitelist_rules={},
        actor_id="actor-1",
    )
    return p


def _fake_adapter(agent_type: str = "nmap"):
    class _A:
        async def execute(self, target, config, holder=None) -> AsyncGenerator[AgentEvent, None]:
            if holder is not None:
                holder.append(f"container-{agent_type}")
            yield AgentEvent("status", agent_type, "x", {"status": "running"})
            yield AgentEvent("status", agent_type, "x",
                             {"status": "completed", "result": {"findings": []}})

    return _A()


def _discovery_agent() -> DiscoveryAgent:
    # seed_xbow roles inherit the @dataclass Role contract (name/system_prompt/llm_model).
    return DiscoveryAgent(name="discovery_agent", system_prompt="x", llm_model="m")


# ── understanding-driven PlanOfWork (non-hardcoded) ──────────────────────────

async def test_understanding_drives_dispatch():
    coord = CoordinatorService(_mock_db())
    web = coord.derive_plan_of_work(UnderstandingOfTarget(target_kind="web_app"))
    net = coord.derive_plan_of_work(UnderstandingOfTarget(target_kind="network"))

    # Phases are derived from the target, not the hardcoded constant.
    assert web.ordered_phases == ["recon", "web_discovery", "web_exploit"]
    assert net.ordered_phases == ["recon", "network_enum", "service_probe"]
    assert web.ordered_phases != net.ordered_phases

    web_attack = next(f for f in web.family_recommendations if f["family_kind"] == "attack")
    net_attack = next(f for f in net.family_recommendations if f["family_kind"] == "attack")
    assert "nuclei" in web_attack["palette"] and "nmap" not in web_attack["palette"]
    assert "nmap" in net_attack["palette"] and "nuclei" not in net_attack["palette"]


async def test_unknown_target_kind_falls_back_to_unknown_vector():
    coord = CoordinatorService(_mock_db())
    pow_ = coord.derive_plan_of_work(UnderstandingOfTarget(target_kind="something-weird"))
    assert pow_.ordered_phases == ["recon"]


# ── family role dispatches its vector palette through the safety chain ────────

async def test_autonomous_dispatch_from_understanding():
    """DiscoveryAgent (network vector) dispatches the network palette head through
    the safety-wired delegator when bound."""
    performer = _bound_performer(approval_flags={"approved_active_recon": True})
    with patch("app.orchestrator.safety_exec.get_adapter", return_value=_fake_adapter()):
        result = await _discovery_agent().run(
            performer=performer, context={"attack_vector": "network"}
        )
    content = result.messages[0]["content"]
    assert "dispatched" in content
    # network palette head = nmap, passive_recon — both reached dispatch.
    assert "nmap" in content
    assert "'approved': True" in content


async def test_family_role_returns_fixture_when_unbound():
    """Without a bound performer the family role stays a palette fixture (isolation)."""
    result = await _discovery_agent().run(performer=None, context={"attack_vector": "web_app"})
    content = result.messages[0]["content"]
    assert "palette=" in content
    assert "nuclei" in content
