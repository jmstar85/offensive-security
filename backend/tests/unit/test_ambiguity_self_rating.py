"""Plan v3.2.1 §4.3 — model self-rating parse + sanity guard + state transitions."""
from __future__ import annotations

import json

import pytest

from app.orchestrator.workflow_service import (
    AssistantTurn,
    _next_state_after_turn,
    _parse_assistant_text,
    min_required_fields_present,
)


_DEFAULT_STEPS = [
    {"order": 1, "agent": "passive_recon", "action": "passive_dns_recon", "tier": "passive_no_target_contact"}
]


def _full_plan(steps=_DEFAULT_STEPS):
    return {
        "target_summary": "ACME corp staging",
        "risk_level": "low",
        "steps": list(steps),
    }


def test_parse_strict_json_envelope():
    raw = json.dumps(
        {
            "ambiguity": 0.2,
            "blockers": ["none"],
            "reasoning": "clear",
            "draft_plan": _full_plan(),
        }
    )
    turn = _parse_assistant_text(raw)
    assert isinstance(turn, AssistantTurn)
    assert turn.ambiguity == 0.2
    assert turn.blockers == ["none"]
    assert turn.draft_plan["risk_level"] == "low"


def test_parse_strips_markdown_fences():
    raw = "```json\n" + json.dumps({"ambiguity": 0.5, "blockers": [], "reasoning": "x", "draft_plan": {}}) + "\n```"
    turn = _parse_assistant_text(raw)
    assert turn.ambiguity == 0.5


def test_parse_clamps_out_of_range_ambiguity():
    raw = json.dumps({"ambiguity": 1.5, "blockers": [], "reasoning": "x", "draft_plan": {}})
    turn = _parse_assistant_text(raw)
    assert turn.ambiguity == 1.0
    raw2 = json.dumps({"ambiguity": -0.4, "blockers": [], "reasoning": "x", "draft_plan": {}})
    assert _parse_assistant_text(raw2).ambiguity == 0.0


def test_parse_raises_on_non_json():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        _parse_assistant_text("not even json")
    assert ei.value.status_code == 502


def test_min_required_fields_rejects_missing_summary():
    plan = _full_plan()
    plan["target_summary"] = ""
    assert min_required_fields_present(plan) is False


def test_min_required_fields_rejects_no_steps():
    plan = _full_plan(steps=[])
    assert min_required_fields_present(plan) is False


def test_min_required_fields_rejects_step_missing_tier():
    plan = _full_plan(steps=[{"order": 1, "agent": "nmap", "action": "port_scan"}])
    assert min_required_fields_present(plan) is False


def test_min_required_fields_accepts_complete_plan():
    assert min_required_fields_present(_full_plan()) is True


def test_state_transition_ready_when_low_ambiguity_and_plan_complete():
    turn = AssistantTurn(ambiguity=0.2, blockers=[], reasoning="", draft_plan=_full_plan())
    assert _next_state_after_turn(turn, new_turn_count=1) == "ready_for_review"


def test_state_transition_keeps_interviewing_when_high_ambiguity():
    turn = AssistantTurn(ambiguity=0.8, blockers=["x"], reasoning="", draft_plan=_full_plan())
    assert _next_state_after_turn(turn, new_turn_count=3) == "interviewing"


def test_state_transition_needs_human_at_turn_cap():
    turn = AssistantTurn(ambiguity=0.9, blockers=["x"], reasoning="", draft_plan=_full_plan())
    assert _next_state_after_turn(turn, new_turn_count=6) == "needs_human_review"


def test_sanity_guard_overrides_low_ambiguity_when_plan_incomplete():
    """Critic D-3 — model ambiguity 0.1 but plan missing target_summary → still interviewing."""
    plan = _full_plan()
    plan["target_summary"] = ""
    turn = AssistantTurn(ambiguity=0.1, blockers=[], reasoning="", draft_plan=plan)
    assert _next_state_after_turn(turn, new_turn_count=2) == "interviewing"


def test_sanity_guard_with_cap_triggers_needs_human():
    plan = _full_plan()
    plan["steps"] = []  # incomplete
    turn = AssistantTurn(ambiguity=0.1, blockers=[], reasoning="", draft_plan=plan)
    assert _next_state_after_turn(turn, new_turn_count=6) == "needs_human_review"
