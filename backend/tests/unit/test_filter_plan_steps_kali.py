"""PR-4 — kali_* branch in safety.exploit_allowlist.filter_plan_steps."""
from __future__ import annotations

import pytest

from app.safety import exploit_allowlist, kali_allowlist


@pytest.fixture
def audit_events(monkeypatch):
    captured: list[tuple[str, dict]] = []

    def fake_emit(event: str, payload: dict) -> None:
        captured.append((event, dict(payload)))

    monkeypatch.setattr(kali_allowlist, "audit_safety_event", fake_emit)
    monkeypatch.setattr(exploit_allowlist, "audit_safety_event", fake_emit)
    return captured


def _kali_step(slug: str, tool_slug: str, args: list[str]) -> dict:
    return {"agent": slug, "config": {"tool_slug": tool_slug, "args": args}}


def test_kali_sqlmap_os_shell_blocked(audit_events):
    step = _kali_step("kali_sqlmap", "sqlmap", ["--os-shell"])
    approved, blocked = exploit_allowlist.filter_plan_steps([step])
    assert approved == []
    assert len(blocked) == 1
    assert blocked[0]["block_reason"].startswith("kali_exec: deny_flag:")
    assert any(
        e[0] == "kali_exec.filter_plan_steps_block" and e[1]["slug"] == "sqlmap"
        for e in audit_events
    )


def test_kali_gobuster_etc_shadow_blocked(audit_events):
    step = _kali_step(
        "kali_gobuster", "gobuster",
        ["dir", "--wordlist=/etc/shadow"],
    )
    approved, blocked = exploit_allowlist.filter_plan_steps([step])
    assert approved == []
    assert len(blocked) == 1
    assert "path_deny" in blocked[0]["block_reason"]
    assert any(
        e[0] == "kali_exec.filter_plan_steps_block" and e[1]["slug"] == "gobuster"
        for e in audit_events
    )


def test_kali_gobuster_valid_passes(audit_events):
    step = _kali_step(
        "kali_gobuster", "gobuster",
        ["dir", "-u", "http://t/", "-w", "/wordlists/c.txt"],
    )
    approved, blocked = exploit_allowlist.filter_plan_steps([step])
    assert approved == [step]
    assert blocked == []
    assert not any(e[0] == "kali_exec.filter_plan_steps_block" for e in audit_events)


def test_existing_branches_unchanged():
    # legacy metasploit + nuclei steps are unaffected.
    steps = [
        {"agent": "metasploit", "config": {"module": "auxiliary/scanner/foo"}},
        {"agent": "nuclei", "config": {"tags": ["dos"]}},
        {"agent": "nmap"},
    ]
    approved, blocked = exploit_allowlist.filter_plan_steps(steps)
    assert {s["agent"] for s in approved} == {"metasploit", "nmap"}
    assert blocked[0]["agent"] == "nuclei"
