"""Interview turn routes to the SESSION'S provider (bug fix).

Regression guard for the HTTP 500 "Could not resolve authentication method":
when ``osa_flow_ui_enabled`` routed the interview through ``AmbiguityLoop`` it
HARDCODED ``ModelClient()`` (Anthropic), ignoring the session's provider. In an
env with ``osa_llm_provider=ollama`` / no ``ANTHROPIC_API_KEY`` and a
``llm_provider_pref="copilot"`` session that blew up with a raw 500.

These tests pin the fix:
1. A Copilot session (no injected client, multi-provider ON) routes the interview
   through the per-session ``build_client_factory`` → ``LLMRouter.route`` — the
   fake Copilot client is used (NOT ModelClient/Anthropic) and receives the
   provider-coherent interview model (``copilot/...`` from
   ``resolve_interview_model``). The assistant turn persists.
2. When ``route`` raises ``CredentialNotFound`` the send maps to the graceful
   503 credential_required pause + a committed ``interview_paused`` marker.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models.msgchain import MsgChain
from app.models.project import Project
from app.models.session import PentestSession, WorkflowMessage
from app.models.user import Team, User, UserRole
from app.orchestrator.llm.credential_resolver import CredentialNotFound
from app.orchestrator.workflow_service import WorkflowService


async def _seed(db, *, provider: str = "copilot"):
    team = Team(name=f"t-{uuid.uuid4()}")
    db.add(team)
    await db.flush()
    user = User(
        email=f"u-{uuid.uuid4()}@x.com",
        password_hash="x" * 60,
        full_name="Op",
        role=UserRole.MEMBER,
        team_id=team.id,
    )
    db.add(user)
    await db.flush()
    project = Project(name="p", client_name="acme", status="active", created_by=user.id)
    db.add(project)
    await db.flush()
    session = PentestSession(
        project_id=project.id,
        prompt="scan",
        status="draft",
        interview_state="not_started",
        interview_turn_count=0,
        ambiguity_score=Decimal("1.000"),
        team_id=user.team_id,
        llm_provider_pref=provider,
    )
    db.add(session)
    await db.flush()
    return user, session


class _FakeCopilotClient:
    """Stand-in for the LLMClient the router returns for a Copilot session.

    Records the ``model_id`` it was sent so the test can assert the interview
    used the provider-coherent model, and returns a deterministic envelope."""

    def __init__(self) -> None:
        self.sent_model_ids: list[str] = []

    async def send(self, *, model_id, messages, system, **_kwargs):
        self.sent_model_ids.append(model_id)
        envelope = (
            '{"ambiguity": 0.20, "blockers": [], '
            '"reasoning": "Fake copilot envelope.", '
            '"draft_plan": {"steps": []}}'
        )
        return SimpleNamespace(text=envelope, tokens_in=11, tokens_out=13, raw=None)


@pytest.mark.asyncio
async def test_interview_routes_to_session_copilot_provider(db, monkeypatch):
    """Multi-provider ON, no injected client, copilot session → the interview
    uses the fake Copilot client (NOT ModelClient/Anthropic) with a copilot/
    model id, and the assistant turn is persisted."""
    from app.orchestrator import workflow_service as ws_mod
    from app.orchestrator.llm import router as router_mod

    monkeypatch.setattr(ws_mod.settings, "osa_flow_ui_enabled", True)
    monkeypatch.setattr(ws_mod.settings, "osa_multi_provider_llm", True)

    fake = _FakeCopilotClient()

    async def _route(self, db, provider, user_id=None):  # noqa: ANN001
        # The interview must resolve the SESSION'S provider, not Anthropic.
        assert provider == "copilot"
        return fake

    monkeypatch.setattr(router_mod.LLMRouter, "route", _route)

    user, session = await _seed(db, provider="copilot")
    # self._client is None → NOT the injected-client path → per-session factory.
    svc = WorkflowService(db=db, model_client=None)
    result = await svc.send_message(
        session_id=session.id,
        user_message="Recon scanme.nmap.org for open ports",
        user=user,
    )

    # (a) the fake copilot client was used (Anthropic/ModelClient never touched).
    assert len(fake.sent_model_ids) == 1
    # (b) it received the provider-coherent interview model (copilot/*), i.e. the
    #     resolve_interview_model result, not an Anthropic id.
    assert fake.sent_model_ids[0].startswith("copilot/")

    # Assistant turn persisted (user + assistant WorkflowMessage rows).
    msgs = (
        await db.execute(
            select(WorkflowMessage)
            .where(WorkflowMessage.pentest_session_id == session.id)
            .order_by(WorkflowMessage.turn_index, WorkflowMessage.created_at)
        )
    ).scalars().all()
    assert len(msgs) >= 2
    assert msgs[0].role == "user"
    # AmbiguityLoop persists one generator-scoped MsgChain.
    chains = (
        await db.execute(
            select(MsgChain).where(MsgChain.pentest_session_id == session.id)
        )
    ).scalars().all()
    assert len(chains) == 1
    assert chains[0].role_name == "generator"

    assert result.assistant_message.role == "assistant"
    assert result.new_state in {"interviewing", "ready_for_review", "needs_human_review"}


class _FakeSideSession:
    """Captures the paused-marker write + commit the handler performs on its
    SEPARATE short-lived session (stands in for ``async_session()``)."""

    def __init__(self, row: SimpleNamespace) -> None:
        self._row = row
        self.committed = False
        self.added: list = []

    async def __aenter__(self) -> "_FakeSideSession":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def get(self, _model, _pk):
        return self._row

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self.committed = True


@pytest.mark.asyncio
async def test_interview_credential_not_found_pauses_via_factory(db, monkeypatch):
    """Multi-provider ON, copilot session, no stored credential → the factory's
    LLMRouter.route raises CredentialNotFound, which the flag-ON branch maps to a
    graceful 503 credential_required + a committed interview_paused marker."""
    from app.orchestrator import workflow_service as ws_mod
    from app.orchestrator.llm import router as router_mod

    monkeypatch.setattr(ws_mod.settings, "osa_flow_ui_enabled", True)
    monkeypatch.setattr(ws_mod.settings, "osa_multi_provider_llm", True)

    async def _raise_credential(self, db, provider, user_id=None):  # noqa: ANN001
        raise CredentialNotFound("no credential for provider='copilot'")

    monkeypatch.setattr(router_mod.LLMRouter, "route", _raise_credential)

    # Capture the SEPARATE committed side-session write (R21).
    side_row = SimpleNamespace(
        status="draft", interview_state="not_started", resume_token=None
    )
    fake_side = _FakeSideSession(side_row)
    monkeypatch.setattr(ws_mod, "async_session", lambda: fake_side)

    user, session = await _seed(db, provider="copilot")
    svc = WorkflowService(db=db, model_client=None)

    with pytest.raises(HTTPException) as exc_info:
        await svc.send_message(
            session_id=session.id,
            user_message="recon the target",
            user=user,
        )

    # graceful 503 credential_required (never a raw 500).
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["error"] == "credential_required"
    assert "message" in exc_info.value.detail
    assert exc_info.value.detail["resume_token"]

    # the paused marker was written AND committed on the SEPARATE session.
    assert fake_side.committed is True
    assert side_row.status == "interview_paused"
    assert side_row.interview_state == "interview_paused"
    assert side_row.resume_token is not None
    assert len(fake_side.added) == 1
