"""PR-4 — kali_* branch in safety.risk_filter.RiskFilter.assess_step."""
from __future__ import annotations

import pytest

from app.agents.base import RiskLevel
from app.safety.risk_filter import RiskFilter, kali_risk_band_score


@pytest.fixture
def rf():
    return RiskFilter()


def test_kali_sqlmap_high(rf):
    step = {"agent": "kali_sqlmap", "config": {"tool_slug": "sqlmap"}}
    assert rf.assess_step(step) == RiskLevel.HIGH


def test_kali_gobuster_medium(rf):
    step = {"agent": "kali_gobuster", "config": {"tool_slug": "gobuster"}}
    assert rf.assess_step(step) == RiskLevel.MEDIUM


def test_kali_nikto_medium(rf):
    step = {"agent": "kali_nikto", "config": {"tool_slug": "nikto"}}
    assert rf.assess_step(step) == RiskLevel.MEDIUM


def test_kali_unknown_slug_falls_back_to_high(rf):
    # Defense-in-depth: filter_plan_steps gate would have dropped this; here
    # we still want a maximally cautious band score.
    step = {"agent": "kali_nope", "config": {"tool_slug": "nope"}}
    assert rf.assess_step(step) == RiskLevel.HIGH


def test_kali_risk_band_score_direct():
    assert kali_risk_band_score("sqlmap") == 0.8
    assert kali_risk_band_score("gobuster") == 0.5
    assert kali_risk_band_score("nikto") == 0.5
    assert kali_risk_band_score(None) == 1.0
    assert kali_risk_band_score("unknown") == 1.0


def test_no_fallthrough_to_legacy_map(rf):
    # If a legacy fallthrough existed, kali_* agents would hit
    # _AGENT_BASE_RISK.get(agent, 0.5) → MEDIUM regardless of slug. We assert
    # the kali path is strictly slug-driven.
    step_high = {"agent": "kali_sqlmap", "config": {"tool_slug": "sqlmap"}}
    step_med = {"agent": "kali_gobuster", "config": {"tool_slug": "gobuster"}}
    assert rf.assess_step(step_high) != rf.assess_step(step_med)


def test_legacy_agent_unchanged(rf):
    # nmap legacy entry is 0.1 → LOW
    assert rf.assess_step({"agent": "nmap"}) == RiskLevel.LOW
    # metasploit legacy entry is 0.8 → HIGH
    assert rf.assess_step({"agent": "metasploit"}) == RiskLevel.HIGH
