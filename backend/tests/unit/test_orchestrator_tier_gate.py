"""Fix #1 — orchestrator wires filter_by_tier_flags into the safety chain.

The PR-4 unit tests proved that filter_by_tier_flags itself blocks
kali_sqlmap when approved_active_exploit is False, but the function was
never called by OrchestratorService.run before this fix. These tests
exercise the integration directly via the OrchestratorService internals
(without spinning up the DB) by invoking the same safety chain in the
same order the service does, with a synthetic plan.
"""
from __future__ import annotations

import pytest

from app.safety.exploit_allowlist import filter_by_tier_flags, filter_plan_steps
from app.safety.risk_filter import RiskFilter
from app.agents.registry import get_tool_entry


def _enrich_with_tier(steps: list[dict]) -> list[dict]:
    """Mirror the loop in OrchestratorService.run that backfills step.tier."""
    for step in steps:
        if step.get("tier"):
            continue
        entry = get_tool_entry(step.get("agent", ""))
        if entry is not None:
            step["tier"] = entry.tier
    return steps


def _run_safety_chain(
    steps: list[dict],
    approval_flags: dict,
) -> tuple[list[dict], list[dict]]:
    """Replicate the order in OrchestratorService.run for testing."""
    steps = _enrich_with_tier(steps)
    approved, blocked = filter_plan_steps(steps)
    approved, tier_blocked = filter_by_tier_flags(approved, approval_flags)
    blocked.extend(tier_blocked)
    approved, risk_blocked = RiskFilter().filter_steps(approved)
    blocked.extend(risk_blocked)
    return approved, blocked


def test_kali_sqlmap_blocked_without_active_exploit_flag():
    steps = [
        {
            "agent": "kali_sqlmap",
            "config": {
                "tool_slug": "sqlmap",
                "args": ["-u", "http://t/q?id=1", "--batch"],
            },
        }
    ]
    approved, blocked = _run_safety_chain(steps, approval_flags={})
    assert approved == []
    assert len(blocked) == 1
    assert "active_exploit" in blocked[0]["block_reason"]


def test_kali_sqlmap_passes_with_active_exploit_flag():
    steps = [
        {
            "agent": "kali_sqlmap",
            "config": {
                "tool_slug": "sqlmap",
                "args": ["-u", "http://t/q?id=1", "--batch"],
            },
        }
    ]
    approved, blocked = _run_safety_chain(
        steps,
        approval_flags={
            "approved_active_exploit": True,
            "approved_active_recon": True,
        },
    )
    assert len(approved) == 1
    assert blocked == []


def test_kali_gobuster_blocked_without_active_recon_flag():
    steps = [
        {
            "agent": "kali_gobuster",
            "config": {
                "tool_slug": "gobuster",
                "args": ["dir", "-u", "http://t/", "-w", "/wordlists/c.txt"],
            },
        }
    ]
    approved, blocked = _run_safety_chain(steps, approval_flags={})
    assert approved == []
    assert "active_recon" in blocked[0]["block_reason"]


def test_tier_backfill_from_registry():
    """Steps without an explicit tier still get gated correctly."""
    step = {
        "agent": "kali_sqlmap",
        "config": {"tool_slug": "sqlmap", "args": ["-u", "http://t/?a=1", "--batch"]},
    }
    assert "tier" not in step
    _enrich_with_tier([step])
    assert step["tier"] == "active_exploit"


def test_legacy_passive_step_unaffected():
    """Tools whose tier requires no flag (passive_*) pass through with empty flags."""
    steps = [{"agent": "passive_recon"}]
    approved, blocked = _run_safety_chain(steps, approval_flags={})
    assert len(approved) == 1
    assert blocked == []


def test_mixed_kali_and_legacy_plan():
    """Realistic plan: legacy passive step + kali_gobuster step. Only the kali
    step needs approved_active_recon."""
    steps = [
        {"agent": "passive_recon"},
        {
            "agent": "kali_gobuster",
            "config": {
                "tool_slug": "gobuster",
                "args": ["dir", "-u", "http://t/", "-w", "/wordlists/c.txt"],
            },
        },
    ]
    approved, blocked = _run_safety_chain(
        steps, approval_flags={"approved_active_recon": True}
    )
    approved_agents = {s["agent"] for s in approved}
    assert approved_agents == {"passive_recon", "kali_gobuster"}
    assert blocked == []


def test_session_approval_flags_default_blocks_active_tiers():
    """Per the model default ({}), all active_recon and active_exploit steps
    are blocked until the operator explicitly opts in."""
    steps = [
        {"agent": "nmap"},  # active_recon
        {"agent": "metasploit", "config": {"module": "auxiliary/scanner/portscan/tcp"}},  # active_exploit
    ]
    approved, blocked = _run_safety_chain(steps, approval_flags={})
    assert approved == []
    blocked_tiers = {b.get("tier") for b in blocked}
    assert blocked_tiers == {"active_recon", "active_exploit"}
