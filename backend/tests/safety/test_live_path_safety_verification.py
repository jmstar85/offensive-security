"""PR9 (C7 close-out): verify the safety chain fires on the LIVE autonomous path —
widened egress detection, the conversation scrubber on the role-turn publish, and
MITM egress routing — rather than assuming it.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.orchestrator.performer import Performer
from app.orchestrator.roles.base import RoleResult
from app.orchestrator.roles.seed_xbow import AttackAgent
from app.safety.egress_monitor import EgressMonitor


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    return db


# ── egress widening ──────────────────────────────────────────────────────────

async def test_egress_extended_ipv4_verb_catches_offscope():
    mon = EgressMonitor(uuid.uuid4(), {"ip_ranges": ["45.33.32.0/24"]})
    with patch.object(EgressMonitor, "_trigger_kill", new_callable=AsyncMock) as kill:
        safe = await mon.monitor_log_line("connect() to 8.8.8.8:443", "a")
    assert safe.safe is False
    kill.assert_awaited_once()


async def test_egress_catches_ipv6_offscope():
    mon = EgressMonitor(uuid.uuid4(), {"ip_ranges": ["45.33.32.0/24"]})
    with patch.object(EgressMonitor, "_trigger_kill", new_callable=AsyncMock) as kill:
        safe = await mon.monitor_log_line("Connecting to [2001:4860:4860::8888]", "a")
    assert safe.safe is False
    kill.assert_awaited_once()


async def test_egress_catches_offscope_host_via_sni():
    mon = EgressMonitor(uuid.uuid4(), {"domains": ["scanme.nmap.org"]})
    with patch.object(EgressMonitor, "_trigger_kill", new_callable=AsyncMock) as kill:
        safe = await mon.monitor_log_line("TLS handshake SNI=evil.example.com", "a")
    assert safe.safe is False
    kill.assert_awaited_once()


async def test_egress_allows_inscope_host_and_subdomain():
    mon = EgressMonitor(uuid.uuid4(), {"domains": ["scanme.nmap.org"]})
    with patch.object(EgressMonitor, "_trigger_kill", new_callable=AsyncMock) as kill:
        assert (await mon.monitor_log_line("Host: scanme.nmap.org", "a")).safe is True
        assert (await mon.monitor_log_line("Host: api.scanme.nmap.org", "a")).safe is True
    kill.assert_not_awaited()


async def test_egress_no_domain_scope_does_not_flag_hosts():
    """Without a domain scope we cannot judge a hostname → no false-positive kill."""
    mon = EgressMonitor(uuid.uuid4(), {"ip_ranges": []})
    with patch.object(EgressMonitor, "_trigger_kill", new_callable=AsyncMock) as kill:
        assert (await mon.monitor_log_line("Host: anything.example.com", "a")).safe is True
    kill.assert_not_awaited()


# ── conversation scrubber on the live role-turn publish ──────────────────────

async def test_scrubber_runs_on_live_role_turn_publish():
    perf = Performer(_mock_db(), uuid.uuid4())
    secret = "sk-ant-api03-AAAABBBBCCCCDDDDEEEEFFFFGGGGHHHHIIIIJJJJ"
    captured: list[tuple[str, dict]] = []

    async def _capture(session_id, event, topic="session"):  # noqa: ANN001
        captured.append((topic, event))

    with patch("app.core.events.event_bus.publish", _capture):
        await perf._publish_role_turn(
            "pentester",
            RoleResult(role_name="pentester",
                       messages=[{"role": "assistant", "content": f"leaking {secret} now"}]),
        )

    convo = next(e for (t, e) in captured if t == "conversation")
    raw = next(e for (t, e) in captured if t == "raw_conversation")
    # Scrubbed on the operator-facing conversation topic; raw retained for admins.
    assert secret not in convo["content"]
    assert secret in raw["content"]


# ── MITM egress routing (Attack family only) ─────────────────────────────────

async def test_attack_agent_routes_egress_via_mitm_when_flagged(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "osa_traffic_via_mitm", True)
    agent = AttackAgent(name="attack_agent", system_prompt="x", llm_model="m")
    ctx: dict = {"attack_vector": "web_app"}
    result = await agent.run(performer=None, context=ctx)  # unbound → fixture + proxy
    assert ctx.get("_attack_agent_egress_proxy")  # proxy URL injected
    assert "egress_via_mitm=True" in result.messages[0]["content"]


async def test_attack_agent_direct_egress_when_flag_off(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "osa_traffic_via_mitm", False)
    agent = AttackAgent(name="attack_agent", system_prompt="x", llm_model="m")
    ctx: dict = {"attack_vector": "web_app"}
    result = await agent.run(performer=None, context=ctx)
    assert "_attack_agent_egress_proxy" not in ctx
    assert "egress_via_mitm=False" in result.messages[0]["content"]
