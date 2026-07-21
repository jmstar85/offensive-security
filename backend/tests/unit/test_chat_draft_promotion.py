"""FIX (session 09484046): the operator's reviewed interview draft must be able to
run. executable_agent_types() is now registry-derived (the stale 4-slug literal
rejected real runnable agents like httpx/kali_*/subfinder), and
chat_draft_to_workflow_plan() adapts the chat-shaped draft into an executable plan.
"""
from __future__ import annotations

import pytest

from app.orchestrator.workflow_plan import (
    WorkflowPlanError,
    chat_draft_to_workflow_plan,
    executable_agent_types,
    topologically_sorted_steps,
)


def test_executable_agent_types_is_registry_derived():
    ex = executable_agent_types()
    # the DVWA plan's agents (previously wrongly rejected) are now executable
    for slug in ("httpx", "kali_gobuster", "kali_nikto", "subfinder", "dnsx", "passive_recon"):
        assert slug in ex
    # the legacy four are still present
    for slug in ("nmap", "nuclei", "metasploit", "pyrit"):
        assert slug in ex


def test_chat_draft_adapts_to_executable_plan_with_linear_edges():
    draft = {
        "steps": [
            {"order": 1, "agent": "nmap", "action": "service_detection",
             "tier": "active_recon", "config": {"target": "10.0.0.5"}},
            {"order": 2, "agent": "httpx", "action": "tech_detect",
             "tier": "passive_low_touch", "config": {"target": "10.0.0.5"}},
        ],
    }
    plan = chat_draft_to_workflow_plan(draft)
    assert [s["agent"] for s in plan["steps"]] == ["nmap", "httpx"]
    assert [s["id"] for s in plan["steps"]] == ["s1", "s2"]
    # linear DAG → deterministic order preserved
    assert [s["agent"] for s in topologically_sorted_steps(plan)] == ["nmap", "httpx"]
    # config carried through; tier dropped (re-derived authoritatively downstream)
    assert plan["steps"][0]["config"] == {"target": "10.0.0.5"}
    assert "tier" not in plan["steps"][0]


def test_ids_off_loop_index_survive_duplicate_or_missing_order():
    """LLM `order` values may collide or be omitted; ids must still be unique
    (keying off order would raise 'Duplicate step id' → silent autonomous fallback)."""
    draft = {"steps": [
        {"agent": "nmap", "action": "port_scan", "config": {}},          # no order
        {"order": 1, "agent": "httpx", "action": "http_status", "config": {}},
        {"order": 1, "agent": "subfinder", "action": "subdomain_enumeration", "config": {}},  # dup order
    ]}
    plan = chat_draft_to_workflow_plan(draft)
    ids = [s["id"] for s in plan["steps"]]
    assert ids == ["s1", "s2", "s3"]
    assert len(set(ids)) == 3


def test_chat_draft_unknown_slug_raises_for_autonomous_fallback():
    with pytest.raises(WorkflowPlanError):
        chat_draft_to_workflow_plan(
            {"steps": [{"order": 1, "agent": "totally_made_up", "action": "x", "config": {}}]}
        )
