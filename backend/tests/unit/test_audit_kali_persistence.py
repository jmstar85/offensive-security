"""Fix #D — kali_exec.* block events are persisted per-step to audit_logs.

The helper is exercised in isolation with an AsyncMock AuditLogger so we
can assert the exact action strings, the row count, and the details
payload shape without spinning up a DB.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.safety.audit_kali import (
    ACTION_FILTER_PLAN,
    ACTION_TIER_GATE,
    persist_kali_blocked_steps,
)


SESSION_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
ACTOR_ID = "00000000-0000-0000-0000-000000000001"


def _kali_step(slug: str, *, reason: str, tier: str = "active_recon") -> dict:
    return {
        "agent": f"kali_{slug}",
        "tier": tier,
        "config": {"tool_slug": slug, "args": []},
        "block_reason": reason,
    }


@pytest.mark.asyncio
async def test_persists_one_row_per_kali_plan_block():
    audit = AsyncMock()
    n = await persist_kali_blocked_steps(
        audit,
        session_id=SESSION_ID,
        actor_id=ACTOR_ID,
        plan_blocked=[
            _kali_step("sqlmap", reason="kali_exec: deny_flag:--os-shell",
                       tier="active_exploit"),
            _kali_step("gobuster", reason="kali_exec: path_deny_prefix:/etc/"),
        ],
        tier_blocked=[],
    )
    assert n == 2
    assert audit.log.await_count == 2
    actions = [call.kwargs["action"] for call in audit.log.await_args_list]
    assert actions == [ACTION_FILTER_PLAN, ACTION_FILTER_PLAN]


@pytest.mark.asyncio
async def test_persists_tier_gate_blocks_with_distinct_action():
    audit = AsyncMock()
    n = await persist_kali_blocked_steps(
        audit,
        session_id=SESSION_ID,
        actor_id=ACTOR_ID,
        plan_blocked=[],
        tier_blocked=[
            _kali_step("sqlmap",
                       reason="tier 'active_exploit' requires session flag approved_active_exploit=true",
                       tier="active_exploit"),
        ],
    )
    assert n == 1
    call = audit.log.await_args_list[0]
    assert call.kwargs["action"] == ACTION_TIER_GATE
    assert call.kwargs["target_id"] == str(SESSION_ID)
    assert call.kwargs["target_entity"] == "pentest_session"
    details = call.kwargs["details"]
    assert details["agent"] == "kali_sqlmap"
    assert details["tool_slug"] == "sqlmap"
    assert details["tier"] == "active_exploit"
    assert "approved_active_exploit" in details["block_reason"]


@pytest.mark.asyncio
async def test_non_kali_blocked_steps_are_ignored():
    audit = AsyncMock()
    n = await persist_kali_blocked_steps(
        audit,
        session_id=SESSION_ID,
        actor_id=ACTOR_ID,
        plan_blocked=[
            {"agent": "nmap", "block_reason": "out_of_scope"},
            {"agent": "metasploit", "block_reason": "Unapproved MSF module: ..."},
        ],
        tier_blocked=[
            {"agent": "nuclei", "tier": "active_recon",
             "block_reason": "tier 'active_recon' requires session flag approved_active_recon=true"},
        ],
    )
    assert n == 0
    audit.log.assert_not_called()


@pytest.mark.asyncio
async def test_mixed_kali_and_legacy_only_kali_get_rows():
    audit = AsyncMock()
    n = await persist_kali_blocked_steps(
        audit,
        session_id=SESSION_ID,
        actor_id=ACTOR_ID,
        plan_blocked=[
            {"agent": "nmap", "block_reason": "out_of_scope"},
            _kali_step("nikto", reason="kali_exec: unknown_flag:--xx"),
        ],
        tier_blocked=[
            {"agent": "nuclei", "tier": "active_recon",
             "block_reason": "..."},
            _kali_step("sqlmap",
                       reason="tier 'active_exploit' requires session flag approved_active_exploit=true",
                       tier="active_exploit"),
        ],
    )
    assert n == 2
    actions = [call.kwargs["action"] for call in audit.log.await_args_list]
    assert actions == [ACTION_FILTER_PLAN, ACTION_TIER_GATE]


@pytest.mark.asyncio
async def test_details_payload_shape_is_stable():
    audit = AsyncMock()
    await persist_kali_blocked_steps(
        audit,
        session_id=SESSION_ID,
        actor_id=ACTOR_ID,
        plan_blocked=[_kali_step("gobuster", reason="kali_exec: deny_flag:-x")],
        tier_blocked=[],
    )
    details = audit.log.await_args_list[0].kwargs["details"]
    assert set(details.keys()) == {"agent", "tool_slug", "tier", "block_reason"}


@pytest.mark.asyncio
async def test_empty_input_does_nothing():
    audit = AsyncMock()
    n = await persist_kali_blocked_steps(
        audit,
        session_id=SESSION_ID,
        actor_id=ACTOR_ID,
        plan_blocked=[],
        tier_blocked=[],
    )
    assert n == 0
    audit.log.assert_not_called()
