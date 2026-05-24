"""PR-4 — kali_sqlmap step must pass filter_by_tier_flags only when
``approved_active_exploit=True`` is set on the session.

This guarantees the active-exploit session gate is not silently bypassed
by the kali_* parallel adapter path (Critic S1-3).
"""
from __future__ import annotations

import pytest

from app.safety.exploit_allowlist import filter_by_tier_flags


@pytest.fixture
def sqlmap_step():
    return {
        "agent": "kali_sqlmap",
        "tier": "active_exploit",
        "config": {"tool_slug": "sqlmap", "args": ["-u", "http://t/q?id=1", "--batch"]},
    }


@pytest.fixture
def gobuster_step():
    return {
        "agent": "kali_gobuster",
        "tier": "active_recon",
        "config": {"tool_slug": "gobuster", "args": ["dir", "-u", "http://t/", "-w", "/wordlists/c.txt"]},
    }


def test_kali_sqlmap_blocked_without_active_exploit_flag(sqlmap_step):
    approved, blocked = filter_by_tier_flags(
        [sqlmap_step],
        session_flags={"approved_active_exploit": False},
    )
    assert approved == []
    assert len(blocked) == 1
    assert "active_exploit" in blocked[0]["block_reason"]


def test_kali_sqlmap_passes_with_active_exploit_flag(sqlmap_step):
    approved, blocked = filter_by_tier_flags(
        [sqlmap_step],
        session_flags={"approved_active_exploit": True, "approved_active_recon": True},
    )
    assert approved == [sqlmap_step]
    assert blocked == []


def test_kali_gobuster_requires_active_recon_flag(gobuster_step):
    approved_no, blocked_no = filter_by_tier_flags(
        [gobuster_step], session_flags={"approved_active_recon": False}
    )
    assert approved_no == []
    assert len(blocked_no) == 1

    approved_yes, _ = filter_by_tier_flags(
        [gobuster_step], session_flags={"approved_active_recon": True}
    )
    assert approved_yes == [gobuster_step]


def test_missing_tier_is_passthrough():
    # Legacy back-compat: a kali step without a tier field is passed through.
    step = {"agent": "kali_nikto", "config": {"tool_slug": "nikto"}}
    approved, blocked = filter_by_tier_flags([step], session_flags={})
    assert approved == [step] and blocked == []
