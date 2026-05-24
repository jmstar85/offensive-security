"""Schema-disjointness invariant test (SF-2 from v4.0 plan revision v2).

`PentestSession.draft_plan_json.steps[*]` and `MsgChain.messages_json[*]` MUST
have disjoint key sets. The invariant prevents the "double source of truth"
bug for transient chat state flagged in Open Issue #4 of v4.0 Phase 1 review.

Canonical key sets (locked v4.0):
- draft_plan_json.steps[*]: {order, agent, action, description, config, tier, status}
- MsgChain.messages_json[*]: {role, content, tool_use_id, usage, timestamp}

If P4 introduces a new field in either schema, this test will fail until the
disjointness is restored (or the contract is amended via a plan ADR).
"""
from __future__ import annotations



DRAFT_PLAN_STEP_KEYS = {"order", "agent", "action", "description", "config", "tier", "status"}
MSGCHAIN_MESSAGE_KEYS = {"role", "content", "tool_use_id", "usage", "timestamp"}


def test_key_sets_disjoint():
    """The two key sets must not share any element."""
    overlap = DRAFT_PLAN_STEP_KEYS & MSGCHAIN_MESSAGE_KEYS
    assert overlap == set(), (
        f"Schema disjointness violated. Overlapping keys: {overlap}. "
        f"v4.0 SF-2 invariant requires draft_plan_json.steps[*] and "
        f"MsgChain.messages_json[*] to have disjoint key sets."
    )


def test_draft_plan_step_keys_canonical():
    """The canonical draft_plan_json.steps[*] key set is locked to 7 fields.

    If you add a new field to a plan step, update this constant AND
    ensure it does not collide with MSGCHAIN_MESSAGE_KEYS.
    """
    assert DRAFT_PLAN_STEP_KEYS == {
        "order", "agent", "action", "description", "config", "tier", "status"
    }


def test_msgchain_message_keys_canonical():
    """The canonical MsgChain.messages_json[*] key set is locked to 5 fields."""
    assert MSGCHAIN_MESSAGE_KEYS == {
        "role", "content", "tool_use_id", "usage", "timestamp"
    }


def test_realistic_step_does_not_have_msgchain_keys():
    """A realistic v3.2.1-shaped plan step must not carry any MsgChain field."""
    sample_step = {
        "order": 1,
        "agent": "nmap",
        "action": "port_scan",
        "description": "Initial TCP SYN scan on /24",
        "config": {"targets": ["192.168.1.0/24"], "rate": 100},
        "tier": "active_recon",
        "status": "pending",
    }
    assert set(sample_step.keys()) <= DRAFT_PLAN_STEP_KEYS
    assert MSGCHAIN_MESSAGE_KEYS.isdisjoint(sample_step.keys())


def test_realistic_msgchain_message_does_not_have_step_keys():
    """A realistic MsgChain message must not carry any plan-step field."""
    sample_msg = {
        "role": "assistant",
        "content": "I'll run nmap port_scan first.",
        "tool_use_id": None,
        "usage": {"input_tokens": 28, "output_tokens": 15},
        "timestamp": "2026-05-16T12:34:56Z",
    }
    assert set(sample_msg.keys()) <= MSGCHAIN_MESSAGE_KEYS
    assert DRAFT_PLAN_STEP_KEYS.isdisjoint(sample_msg.keys())
