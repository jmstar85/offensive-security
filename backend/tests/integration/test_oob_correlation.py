"""PR8: finding evidence tags + Interactsh OOB canary correlation (C5)."""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select

from app.models.oob import OOBCallback
from app.models.project import Project
from app.models.session import PentestSession
from app.models.user import Team, User, UserRole
from app.orchestrator.oob_correlation import OOBCorrelationService
from app.reports.generator import ReportGenerator
from app.safety.evidence import tag_finding_evidence


async def _seed_session(db) -> PentestSession:
    team = Team(name=f"team-{uuid.uuid4()}")
    db.add(team)
    await db.flush()
    user = User(
        email=f"u-{uuid.uuid4()}@example.com", password_hash="x" * 60,
        full_name="T", role=UserRole.MEMBER, team_id=team.id,
    )
    db.add(user)
    await db.flush()
    project = Project(name="p", client_name="acme", status="active", created_by=user.id)
    db.add(project)
    await db.flush()
    s = PentestSession(
        project_id=project.id, prompt="scan", status="running",
        interview_state="ready_for_review", interview_turn_count=1,
        ambiguity_score=Decimal("0.100"),
    )
    db.add(s)
    await db.flush()
    return s


# ── evidence tags ────────────────────────────────────────────────────────────

def test_evidence_tag_added():
    tagged = tag_finding_evidence(
        {"agent_type": "nmap", "type": "port", "port": 80, "severity": "low"}
    )
    assert tagged["evidence_tag"] == "nmap:port|port=80"
    assert tagged["evidence_source"] == "nmap"


def test_evidence_tag_is_idempotent():
    f = {"agent_type": "nuclei", "type": "vuln", "evidence_tag": "preset"}
    assert tag_finding_evidence(f)["evidence_tag"] == "preset"


async def test_report_findings_carry_evidence_tags(db):
    session = await _seed_session(db)
    findings = [
        {"agent_type": "nmap", "type": "port", "port": 22, "severity": "info"},
        {"agent_type": "nuclei", "type": "cve", "cve": "CVE-2024-1", "severity": "high"},
    ]
    report = await ReportGenerator(db).generate(session.id, findings, {"steps": []})
    tagged = report.findings_json["findings"]
    assert all("evidence_tag" in f for f in tagged)
    assert tagged[1]["evidence_tag"] == "nuclei:cve|cve=CVE-2024-1"


# ── OOB canary correlation ───────────────────────────────────────────────────

async def test_oob_callback_valid_canary_persists_and_correlates(db):
    session = await _seed_session(db)
    svc = OOBCorrelationService(db)
    canary = svc.mint_canary(session.id)

    row = await svc.ingest_callback(
        session_id=session.id, canary_token=canary, protocol="dns",
        source_ip="45.33.32.156", correlation_id="abc-123",
    )
    assert row is not None
    assert row.canary_verified is True
    assert row.protocol == "dns"
    assert row.correlation_id == "abc-123"

    persisted = (await db.execute(
        select(OOBCallback).where(OOBCallback.pentest_session_id == session.id)
    )).scalars().all()
    assert len(persisted) == 1


async def test_oob_callback_rejects_cross_session_canary(db):
    session = await _seed_session(db)
    svc = OOBCorrelationService(db)
    # A canary minted for a DIFFERENT session must not correlate to this one.
    foreign_canary = svc.mint_canary(uuid.uuid4())

    row = await svc.ingest_callback(
        session_id=session.id, canary_token=foreign_canary, protocol="http",
    )
    assert row is None
    persisted = (await db.execute(
        select(OOBCallback).where(OOBCallback.pentest_session_id == session.id)
    )).scalars().all()
    assert len(persisted) == 0
