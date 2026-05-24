"""Reporter role tests (v4.0 P2a)."""
from __future__ import annotations

import pytest

from app.orchestrator.roles.reporter import Reporter, REPORTER_SYSTEM_PROMPT


def test_reporter_palette_is_done_only():
    """Reporter only emits `done` — no new scans, no tool dispatch."""
    role = Reporter()
    assert role.tools_allowed == ["done"]


def test_reporter_system_prompt_mentions_report_generator():
    """Prompt must reference the existing ReportGenerator output format."""
    assert "Reporter" in REPORTER_SYSTEM_PROMPT
    assert "report" in REPORTER_SYSTEM_PROMPT.lower()


@pytest.mark.asyncio
async def test_reporter_placeholder_when_context_missing():
    """Without performer.state.db + session_id + context findings/plan, the
    role returns a placeholder so the Performer loop's `finished` signal is
    still observable (test isolation + smoke runs)."""
    role = Reporter()
    result = await role.run(performer=None, context={})
    assert result.role_name == "reporter"
    assert result.finished is True
    assert "placeholder" in result.messages[0]["content"].lower()


@pytest.mark.asyncio
async def test_reporter_invokes_report_generator_when_context_complete(db):
    """v4.0 gap-fill — Reporter calls ReportGenerator.generate when all
    inputs are present and surfaces report_id + risk_score."""
    import uuid
    from types import SimpleNamespace

    from app.models.project import Project
    from app.models.session import PentestSession
    from app.models.user import Team, User, UserRole

    team = Team(name=f"t-{uuid.uuid4()}")
    db.add(team)
    await db.flush()
    user = User(
        email=f"u-{uuid.uuid4()}@example.com",
        password_hash="x" * 60,
        full_name="Op",
        role=UserRole.MEMBER,
        team_id=team.id,
    )
    db.add(user)
    await db.flush()
    project = Project(
        name="p", client_name="acme", status="active", created_by=user.id
    )
    db.add(project)
    await db.flush()
    session_row = PentestSession(
        project_id=project.id, prompt="x", status="completed"
    )
    db.add(session_row)
    await db.flush()

    fake_performer = SimpleNamespace(
        state=SimpleNamespace(db=db, session_id=session_row.id)
    )

    role = Reporter()
    result = await role.run(
        performer=fake_performer,
        context={
            "findings": [
                {"severity": "high", "title": "Open SSH on 22"},
                {"severity": "medium", "title": "Outdated nginx"},
            ],
            "plan": {"steps": [{"order": 1, "agent": "nmap"}]},
        },
    )
    assert result.role_name == "reporter"
    assert result.finished is True
    text = result.messages[0]["content"]
    assert "Report generated" in text
    assert "risk_score=" in text
    assert "finding_count=2" in text
