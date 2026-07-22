"""(b) Deterministic-lane Agents narration: PlanExecutor writes a per-step
MsgChain (role_name = tool slug) narrating intent + result, so the Agents tab
shows a conversational per-sub-agent record on the deterministic lane (not only
the autonomous Performer lane)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.msgchain import MsgChain
from app.orchestrator.executor import PlanExecutor, _summarize_findings


def test_summarize_findings_is_tolerant():
    assert _summarize_findings([]) == ""
    s = _summarize_findings([{"service": "ssh", "port": 22}, {"name": "XSS", "severity": "high"}])
    assert "ssh" in s and "XSS" in s
    big = _summarize_findings([{"type": "x"}] * 9)
    assert "and 4 more" in big  # caps at 5 shown


@pytest.mark.asyncio
async def test_narrate_step_writes_completed_chain(db):
    ex = PlanExecutor(db)
    sid = uuid.uuid4()
    await ex._narrate_step(
        sid,
        {"agent": "nmap", "action": "service_detection", "description": "scan services"},
        {"target": "10.0.0.5"},
        datetime.now(timezone.utc),
        SimpleNamespace(killed=False, safety_violation=None, error=None,
                        findings=[{"service": "ssh", "port": 22}]),
    )
    rows = (
        await db.execute(select(MsgChain).where(MsgChain.pentest_session_id == sid))
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].role_name == "nmap"
    assert rows[0].status == "finished"
    convo = " ".join(m["content"] for m in rows[0].messages_json)
    assert "nmap" in convo and "10.0.0.5" in convo and "1 finding" in convo


@pytest.mark.asyncio
async def test_narrate_step_writes_failed_chain_on_timeout(db):
    ex = PlanExecutor(db)
    sid = uuid.uuid4()
    await ex._narrate_step(
        sid,
        {"agent": "nuclei", "action": "vuln_template_scan"},
        {"target": "10.0.0.5"},
        datetime.now(timezone.utc),
        SimpleNamespace(killed=False, safety_violation=None,
                        error="execution timed out after 420s", findings=[]),
    )
    row = (
        await db.execute(select(MsgChain).where(MsgChain.pentest_session_id == sid))
    ).scalars().one()
    assert row.role_name == "nuclei"
    assert row.status == "failed"
    assert "timed out" in row.messages_json[1]["content"]
