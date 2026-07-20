"""Group B: interview autoblock tightens the session-start ambiguity gate.

When ``osa_interview_autoblock_enabled`` is on, an interview turn must drive
ambiguity to ≤ 0.20 (the "until ≤ 20%" contract) before it may advance to
ready_for_review; with the flag off the legacy 0.35 threshold applies. The turn
cap still forces needs_human_review when the interview can't converge.
"""
from __future__ import annotations

import pytest

from app.core.config import settings
from app.orchestrator.workflow_service import (
    AssistantTurn,
    _next_state_after_turn,
    interview_ambiguity_target,
)

_VALID_PLAN = {
    "target_summary": "acme staging",
    "risk_level": "low",
    "steps": [{"agent": "nmap", "action": "port_scan", "tier": "active_recon"}],
}


def _turn(ambiguity: float) -> AssistantTurn:
    return AssistantTurn(ambiguity=ambiguity, blockers=[], reasoning="", draft_plan=_VALID_PLAN)


def test_target_is_020_when_autoblock_on(monkeypatch):
    monkeypatch.setattr(settings, "osa_interview_autoblock_enabled", True)
    assert interview_ambiguity_target() == pytest.approx(0.20)


def test_target_is_legacy_035_when_autoblock_off(monkeypatch):
    monkeypatch.setattr(settings, "osa_interview_autoblock_enabled", False)
    assert interview_ambiguity_target() == pytest.approx(settings.workflow_ambiguity_threshold)


def test_ambiguity_between_020_and_035_blocks_when_autoblock_on(monkeypatch):
    # 0.30 clears the legacy 0.35 gate but NOT the 0.20 autoblock target.
    monkeypatch.setattr(settings, "osa_interview_autoblock_enabled", True)
    assert _next_state_after_turn(_turn(0.30), new_turn_count=2) == "interviewing"


def test_same_ambiguity_passes_when_autoblock_off(monkeypatch):
    monkeypatch.setattr(settings, "osa_interview_autoblock_enabled", False)
    assert _next_state_after_turn(_turn(0.30), new_turn_count=2) == "ready_for_review"


def test_ambiguity_at_target_passes_when_autoblock_on(monkeypatch):
    monkeypatch.setattr(settings, "osa_interview_autoblock_enabled", True)
    assert _next_state_after_turn(_turn(0.20), new_turn_count=2) == "ready_for_review"


def test_turn_cap_forces_human_review_when_still_ambiguous(monkeypatch):
    monkeypatch.setattr(settings, "osa_interview_autoblock_enabled", True)
    cap = settings.workflow_max_interview_turns
    assert _next_state_after_turn(_turn(0.30), new_turn_count=cap) == "needs_human_review"
