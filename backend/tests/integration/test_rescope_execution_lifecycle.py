"""Real service/executor/database rescope lifecycle; only external I/O is fake."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest
import pytest_asyncio
from fastapi import BackgroundTasks, FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request

from app.agents.base import AgentEvent
from app.api.v1.pentest_sessions import RescopeDecisionBody, decide_rescope
from app.core.config import settings
from app.models.project import Project, Target
from app.models.report import Report
from app.models.session import AgentExecution, PentestSession, RescopeApproval
from app.models.user import Team, User
from app.orchestrator import execution_launcher
from app.orchestrator.model_client import Response
from app.orchestrator.performer import Performer
from app.orchestrator.rescope_service import RescopeService


@dataclass(slots=True)
class Runtime:
    """Mutable external adapter trace for one isolated session."""

    db: AsyncSession
    user: User
    session: PentestSession
    calls: list[str] = field(default_factory=list)
    model_roles: list[str] = field(default_factory=list)


@pytest_asyncio.fixture
async def runtime(engine, monkeypatch) -> AsyncIterator[Runtime]:
    # Given a real database session that permits production commits.
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(execution_launcher, "async_session", factory)
    monkeypatch.setattr(settings, "osa_coordinator_enabled", False)
    monkeypatch.setattr(settings, "osa_xbow_autonomous_enabled", True)
    monkeypatch.setattr(settings, "reflector_max_retries", 0)
    async with factory() as db:
        team = Team(name="rescope operators")
        db.add(team)
        await db.flush()
        user = User(
            email=f"{team.id}@example.test", password_hash="unused",
            full_name="Operator", team_id=team.id,
        )
        db.add(user)
        await db.flush()
        project = Project(name="rescope", client_name="test", created_by=user.id)
        db.add(project)
        await db.flush()
        db.add(Target(
            project_id=project.id, domains=["origin.example"], ip_ranges=[],
            whitelist_rules={"domains": ["origin.example"], "active_allowed": ["origin.example"]},
        ))
        session = PentestSession(
            project_id=project.id, prompt="continue scoped recon", status="approved",
            objective="continue scoped recon", team_id=team.id,
            approval_flags={"approved_active_recon": True},
        )
        db.add(session)
        await db.commit()
        state = Runtime(db, user, session)

        class Adapter:
            async def execute(self, target, config, holder) -> AsyncIterator[AgentEvent]:
                host = config["target"]
                state.calls.append(host)
                findings = (
                    [{"new_hosts": [{"host": "next.example", "tier": "active_recon"}]}]
                    if host == "origin.example" else [{"host": host, "type": "port"}]
                )
                yield AgentEvent("status", "nmap", "run", {
                    "status": "completed", "result": {"findings": findings},
                })

        class Client:
            def __init__(self, role: str) -> None:
                self.role = role

            async def send(self, **kwargs) -> Response:
                # Request-driven (no external call-counter oracle): decide ONLY from
                # the supplied conversation, so a resume that fails to restore prior
                # context would re-scan origin and be caught.
                state.model_roles.append(self.role)
                if self.role == "generator":
                    text = '{"draft_plan":{"steps":[]}}'
                else:
                    blob = json.dumps(kwargs.get("messages", []))
                    if "next.example" in blob:
                        text = '{"done":true,"summary":"finished"}'
                    elif "origin.example" in blob:
                        text = json.dumps({"tool": "nmap", "intent": "port_scan",
                                           "config": {"target": "next.example"}})
                    else:
                        text = json.dumps({"tool": "nmap", "intent": "port_scan",
                                           "config": {"target": "origin.example"}})
                return Response(text=text, tokens_in=0, tokens_out=0, raw=None)

        def client_factory(**kwargs):
            async def resolve(role: str) -> Client:
                return Client(role)
            return resolve

        async def plan(self, prompt, target):
            return {"steps": []}

        async def pdf(self, *args):
            return None

        monkeypatch.setattr("app.orchestrator.safety_exec.get_adapter", lambda slug: Adapter())
        monkeypatch.setattr("app.orchestrator.roles.llm_provider.build_client_factory", client_factory)
        monkeypatch.setattr("app.orchestrator.planner.AttackPlanner.create_plan", plan)
        monkeypatch.setattr("app.reports.pdf.PDFGenerator.generate", pdf)
        yield state


@pytest.mark.parametrize("autonomous", [False, True], ids=["deterministic", "autonomous"])
async def test_execution_pauses_before_later_steps(runtime: Runtime, autonomous: bool) -> None:
    # Given a two-step plan (or the real Pentester tool loop).
    if not autonomous:
        runtime.session.plan_json = {
            "steps": [
                {"id": "first", "order": 1, "agent": "nmap",
                 "config": {"target": "origin.example"}},
                {"id": "second", "order": 2, "agent": "nmap",
                 "config": {"target": "next.example"}},
            ],
        }
        await runtime.db.commit()
    # When the real launcher executes a discovery outside the scope.
    await execution_launcher.launch_autonomous_execution(
        runtime.session.id, runtime.session.prompt, runtime.user.id,
    )
    # Then execution is durably paused, not finalized, and later work did not run.
    await runtime.db.refresh(runtime.session)
    assert runtime.session.status == "paused_for_rescope"
    assert runtime.session.ended_at is None
    assert runtime.calls == ["origin.example"]
    rows = (await runtime.db.scalars(select(AgentExecution).where(
        AgentExecution.session_id == runtime.session.id,
    ))).all()
    assert len(rows) == 1
    assert rows[0].status == "completed"
    assert not (await runtime.db.scalars(select(Report).where(
        Report.session_id == runtime.session.id,
    ))).all()


async def test_performer_refuses_late_dispatch_after_pause(runtime: Runtime) -> None:
    # Given a running live Performer with a real session and rescope service.
    runtime.session.status = "running"
    await runtime.db.commit()
    performer = Performer(runtime.db, runtime.session.id)
    performer.bind_live_execution(
        target={"domains": ["origin.example"]}, whitelist_rules={"domains": ["origin.example"]},
        approval_flags={"approved_active_recon": True}, actor_id=str(runtime.user.id),
    )
    await performer._dispatch_tool("nmap", {"config": {"target": "origin.example"}})
    # When a late/nested caller tries another dispatch without approval.
    result = await performer._dispatch_tool("nmap", {"config": {"target": "next.example"}})
    # Then the adapter is never reached again.
    assert result["paused_for_rescope"] is True
    assert result["executed"] is False
    assert runtime.calls == ["origin.example"]

async def test_same_executor_reentry_after_pause_is_fail_closed(runtime: Runtime) -> None:
    # Given a deterministic PlanExecutor that paused on a discovered out-of-scope host.
    from app.orchestrator.executor import PlanExecutor

    runtime.session.status = "running"
    await runtime.db.flush()
    ex = PlanExecutor(runtime.db)
    wl = {"domains": ["origin.example"], "active_allowed": ["origin.example"]}
    await ex.execute(
        session_id=runtime.session.id,
        steps=[{"order": 1, "agent": "nmap", "config": {"target": "origin.example"}}],
        target={"domains": ["origin.example"]}, whitelist_rules=wl,
        actor_id=str(runtime.user.id),
    )
    assert ex.paused_for_rescope is True
    assert runtime.calls == ["origin.example"]
    # When execute() is re-entered on the SAME paused instance with the later step.
    out = await ex.execute(
        session_id=runtime.session.id,
        steps=[{"order": 2, "agent": "nmap", "config": {"target": "next.example"}}],
        target={"domains": ["origin.example"]}, whitelist_rules=wl,
        actor_id=str(runtime.user.id),
    )
    # Then nothing runs and the adapter is never reached again.
    assert out == []
    assert runtime.calls == ["origin.example"]


async def test_duplicate_launch_while_paused_never_completes(runtime: Runtime) -> None:
    # Given an autonomous run parked at paused_for_rescope with a pending approval.
    await execution_launcher.launch_autonomous_execution(
        runtime.session.id, runtime.session.prompt, runtime.user.id,
    )
    await runtime.db.refresh(runtime.session)
    assert runtime.session.status == "paused_for_rescope"
    # When the shared launcher is invoked AGAIN without an operator decision.
    await execution_launcher.launch_autonomous_execution(
        runtime.session.id, runtime.session.prompt, runtime.user.id,
    )
    await runtime.db.refresh(runtime.session)
    # Then the run is refused: still paused, never finalized completed, approval pending.
    assert runtime.session.status == "paused_for_rescope"
    pending = (await runtime.db.scalars(select(RescopeApproval).where(
        RescopeApproval.pentest_session_id == runtime.session.id,
        RescopeApproval.status == "pending",
    ))).all()
    assert len(pending) == 1


async def test_autonomous_paused_pentester_chain_not_marked_failed(runtime: Runtime) -> None:
    from app.models.msgchain import MsgChain

    await execution_launcher.launch_autonomous_execution(
        runtime.session.id, runtime.session.prompt, runtime.user.id,
    )
    await runtime.db.refresh(runtime.session)
    assert runtime.session.status == "paused_for_rescope"
    chains = (await runtime.db.scalars(select(MsgChain).where(
        MsgChain.pentest_session_id == runtime.session.id,
    ))).all()
    by_role = {c.role_name: c.status for c in chains}
    # A rescope pause is NOT a role failure on the user-visible Agents surface.
    assert by_role.get("pentester") == "paused"
    assert by_role.get("pentester") != "failed"


@pytest.mark.parametrize("autonomous", [False, True], ids=["deterministic", "autonomous"])
async def test_approved_rescope_resumes_and_completes(runtime: Runtime, autonomous: bool) -> None:
    from types import SimpleNamespace
    from typing import Any

    if not autonomous:
        runtime.session.plan_json = {"steps": [
            {"id": "first", "order": 1, "agent": "nmap", "config": {"target": "origin.example"}},
            {"id": "second", "order": 2, "agent": "nmap", "config": {"target": "next.example"}},
        ]}
        await runtime.db.commit()
    # Given a run parked for rescope with one pending approval.
    await execution_launcher.launch_autonomous_execution(
        runtime.session.id, runtime.session.prompt, runtime.user.id,
    )
    await runtime.db.refresh(runtime.session)
    assert runtime.session.status == "paused_for_rescope"
    pending = (await runtime.db.scalars(select(RescopeApproval).where(
        RescopeApproval.pentest_session_id == runtime.session.id,
        RescopeApproval.status == "pending",
    ))).all()
    assert len(pending) == 1
    # When the operator approves the discovered host through the real route.
    bg = BackgroundTasks()
    req: Any = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    resp = await decide_rescope(
        session_id=runtime.session.id,
        body=RescopeDecisionBody(rescope_id=pending[0].id, accept=["next.example"], reject=[]),
        request=req, background_tasks=bg, db=runtime.db, current_user=runtime.user,
    )
    assert resp.session_status == "executing"
    assert len(bg.tasks) == 1
    # Then driving the scheduled continuation actually runs the accepted host and completes.
    await bg()
    await runtime.db.refresh(runtime.session)
    # Exact remaining-work trace: resume reaches next WITHOUT re-scanning origin
    # (context restored, not restarted) in BOTH lanes.
    assert runtime.calls == ["origin.example", "next.example"]
    assert runtime.session.status == "completed"
    assert runtime.session.ended_at is not None


async def test_deterministic_resume_with_duplicate_step_order(runtime: Runtime) -> None:
    from types import SimpleNamespace
    from typing import Any

    # Two DISTINCT steps sharing display order 1 (allowed by the plan contract).
    runtime.session.plan_json = {"steps": [
        {"id": "a", "order": 1, "agent": "nmap", "config": {"target": "origin.example"}},
        {"id": "b", "order": 1, "agent": "nmap", "config": {"target": "next.example"}},
    ]}
    await runtime.db.commit()
    await execution_launcher.launch_autonomous_execution(
        runtime.session.id, runtime.session.prompt, runtime.user.id,
    )
    await runtime.db.refresh(runtime.session)
    assert runtime.session.status == "paused_for_rescope"
    pending = (await runtime.db.scalars(select(RescopeApproval).where(
        RescopeApproval.pentest_session_id == runtime.session.id,
        RescopeApproval.status == "pending",
    ))).all()
    assert len(pending) == 1
    bg = BackgroundTasks()
    req: Any = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    resp = await decide_rescope(
        session_id=runtime.session.id,
        body=RescopeDecisionBody(rescope_id=pending[0].id, accept=["next.example"], reject=[]),
        request=req, background_tasks=bg, db=runtime.db, current_user=runtime.user,
    )
    assert resp.session_status == "executing"
    await bg()
    await runtime.db.refresh(runtime.session)
    # The second step (same order, distinct id) is NOT skipped; next runs; completes.
    assert runtime.calls == ["origin.example", "next.example"]
    assert runtime.session.status == "completed"
