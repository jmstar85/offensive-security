"""Plan v3.2.1 §4.2 — chat flow round-trip with mocked ModelClient."""
from __future__ import annotations

import json
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.user import UserRole
from app.orchestrator.model_client import Response
from app.orchestrator.workflow_service import WorkflowService


@pytest.fixture(autouse=True)
def _legacy_chat_path(monkeypatch):
    """These tests exercise the legacy v3.2.1 chat path with a mocked ModelClient.
    Two default flips would reroute them off that path, so pin both OFF here:
    - PR10 flipped osa_flow_ui_enabled default ON (routes through AmbiguityLoop);
    - PR9 flipped osa_multi_provider_llm default ON (the interview/chat turn then
      routes through LLMRouter.route(user_id=...) → the per-user credential vault,
      bypassing the injected model_client and failing closed with
      CredentialNotFound). Pinning it OFF keeps the legacy single-provider path
      these tests were written for."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "osa_flow_ui_enabled", False)
    monkeypatch.setattr(settings, "osa_multi_provider_llm", False)


def _user(role=UserRole.MEMBER):
    return SimpleNamespace(
        id=uuid.uuid4(),
        email="op@example.com",
        full_name="Op",
        role=role,
        is_active=True,
        team_id=uuid.uuid4(),
    )


async def _seed_project(db):
    from app.models.project import Project, Target
    p = Project(
        name="acme-staging",
        client_name="ACME",
        created_by=uuid.uuid4(),
        status="active",
    )
    db.add(p)
    await db.flush()
    t = Target(
        project_id=p.id,
        ip_ranges=["10.0.0.0/24"],
        domains=["acme.com"],
        whitelist_rules={"ip_ranges": ["10.0.0.0/24"], "domains": ["acme.com"]},
    )
    db.add(t)
    await db.flush()
    return p


def _mock_client_returning(payload: dict, tokens_in=80, tokens_out=120):
    client = AsyncMock()
    client.send = AsyncMock(
        return_value=Response(
            text=json.dumps(payload),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            raw=None,
        )
    )
    return client


@pytest.mark.asyncio
async def test_create_draft_then_first_message_transitions_to_interviewing(db):
    project = await _seed_project(db)
    user = _user()
    mock = _mock_client_returning({
        "ambiguity": 0.75,
        "blockers": ["specify which subnet"],
        "reasoning": "scope still broad",
        "draft_plan": {
            "target_summary": "acme staging",
            "risk_level": "low",
            "steps": [{"order": 1, "agent": "passive_recon", "action": "passive_dns_recon", "tier": "passive_no_target_contact"}],
        },
    })
    svc = WorkflowService(db, model_client=mock)

    session = await svc.create_draft(
        project_id=project.id, initial_prompt="scan acme.com", user=user,
    )
    assert session.status == "draft"
    assert session.interview_turn_count == 0

    result = await svc.send_message(
        session_id=session.id, user_message="please draft a passive recon plan", user=user,
    )

    assert result.new_state == "interviewing"
    assert result.interview_turn_count == 1
    assert result.ambiguity_score == Decimal("0.750")
    mock.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_low_ambiguity_complete_plan_transitions_to_ready_for_review(db):
    project = await _seed_project(db)
    user = _user()
    mock = _mock_client_returning({
        "ambiguity": 0.2,
        "blockers": [],
        "reasoning": "plan is concrete",
        "draft_plan": {
            "target_summary": "acme staging — passive only",
            "risk_level": "low",
            "steps": [
                {"order": 1, "agent": "passive_recon", "action": "passive_dns_recon", "tier": "passive_no_target_contact"},
                {"order": 2, "agent": "wappalyzer", "action": "tech_stack_inventory", "tier": "passive_low_touch"},
            ],
        },
    })
    svc = WorkflowService(db, model_client=mock)

    session = await svc.create_draft(
        project_id=project.id, initial_prompt="x", user=user,
    )
    result = await svc.send_message(session_id=session.id, user_message="passive only", user=user)

    assert result.new_state == "ready_for_review"
    assert result.ambiguity_score == Decimal("0.200")


@pytest.mark.asyncio
async def test_sanity_guard_keeps_interviewing_when_steps_missing(db):
    project = await _seed_project(db)
    user = _user()
    mock = _mock_client_returning({
        "ambiguity": 0.1,  # model claims certainty
        "blockers": [],
        "reasoning": "",
        "draft_plan": {"target_summary": "", "risk_level": "low", "steps": []},  # but incomplete
    })
    svc = WorkflowService(db, model_client=mock)
    session = await svc.create_draft(
        project_id=project.id, initial_prompt="x", user=user,
    )
    result = await svc.send_message(session_id=session.id, user_message="hi", user=user)
    # Sanity guard overrides — should NOT transition to ready_for_review
    assert result.new_state == "interviewing"


@pytest.mark.asyncio
async def test_turn_cap_advances_to_needs_human_review(db, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "workflow_max_interview_turns", 2)
    project = await _seed_project(db)
    user = _user()
    mock = _mock_client_returning({
        "ambiguity": 0.9,
        "blockers": ["still vague"],
        "reasoning": "operator keeps under-specifying",
        "draft_plan": {"target_summary": "x", "risk_level": "low", "steps": [
            {"order": 1, "agent": "passive_recon", "action": "passive_dns_recon", "tier": "passive_no_target_contact"}
        ]},
    })
    svc = WorkflowService(db, model_client=mock)
    session = await svc.create_draft(project_id=project.id, initial_prompt="x", user=user)
    await svc.send_message(session_id=session.id, user_message="m1", user=user)
    result = await svc.send_message(session_id=session.id, user_message="m2", user=user)
    assert result.new_state == "needs_human_review"


@pytest.mark.asyncio
async def test_turn_cap_blocks_send_message_with_409(db, monkeypatch):
    from app.core.config import settings
    from fastapi import HTTPException
    monkeypatch.setattr(settings, "workflow_max_interview_turns", 1)
    project = await _seed_project(db)
    user = _user()
    mock = _mock_client_returning({
        "ambiguity": 0.9, "blockers": [], "reasoning": "",
        "draft_plan": {"target_summary": "x", "risk_level": "low", "steps": [
            {"order": 1, "agent": "passive_recon", "action": "passive_dns_recon", "tier": "passive_no_target_contact"}
        ]},
    })
    svc = WorkflowService(db, model_client=mock)
    session = await svc.create_draft(project_id=project.id, initial_prompt="x", user=user)
    await svc.send_message(session_id=session.id, user_message="m1", user=user)
    with pytest.raises(HTTPException) as ei:
        await svc.send_message(session_id=session.id, user_message="m2", user=user)
    assert ei.value.status_code == 409


@pytest.mark.asyncio
async def test_send_message_persists_workflow_messages(db):
    from app.models.session import WorkflowMessage
    from sqlalchemy import select
    project = await _seed_project(db)
    user = _user()
    mock = _mock_client_returning({
        "ambiguity": 0.5,
        "blockers": ["clarify scope"],
        "reasoning": "narrowing",
        "draft_plan": {"target_summary": "x", "risk_level": "low", "steps": [
            {"order": 1, "agent": "passive_recon", "action": "passive_dns_recon", "tier": "passive_no_target_contact"}
        ]},
    })
    svc = WorkflowService(db, model_client=mock)
    session = await svc.create_draft(project_id=project.id, initial_prompt="x", user=user)
    await svc.send_message(session_id=session.id, user_message="probe acme", user=user)

    rows = (await db.execute(
        select(WorkflowMessage).where(WorkflowMessage.pentest_session_id == session.id)
    )).scalars().all()
    roles = [r.role for r in rows]
    assert roles.count("user") == 1
    assert roles.count("assistant") == 1
    assistant_row = next(r for r in rows if r.role == "assistant")
    assert assistant_row.ambiguity_after == Decimal("0.500")
    assert assistant_row.tokens_in == 80
    assert assistant_row.tokens_out == 120


@pytest.mark.asyncio
async def test_duplicate_first_turn_returns_409_not_500(db):
    """A reload / double-submit during the slow first turn re-inserts (session, 0,
    user) and hits uq_workflow_messages_session_turn_role — must surface a clean
    409, not an unhandled 500 (session 09484046)."""
    from fastapi import HTTPException

    from app.models.session import WorkflowMessage

    project = await _seed_project(db)
    user = _user()
    mock = _mock_client_returning(
        {"ambiguity": 0.5, "blockers": [], "reasoning": "", "draft_plan": {"steps": []}}
    )
    svc = WorkflowService(db, model_client=mock)
    session = await svc.create_draft(
        project_id=project.id, initial_prompt="scan acme.com", user=user,
    )
    # An in-flight first user turn already persisted (turn_index still 0).
    db.add(WorkflowMessage(
        pentest_session_id=session.id, role="user", content="scan acme.com", turn_index=0,
    ))
    await db.flush()

    with pytest.raises(HTTPException) as ei:
        await svc.send_message(session_id=session.id, user_message="scan acme.com", user=user)
    assert ei.value.status_code == 409
    assert ei.value.detail["error"] == "turn_in_progress"
