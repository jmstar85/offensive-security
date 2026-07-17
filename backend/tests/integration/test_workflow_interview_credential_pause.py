"""Plan A4 / R21 — graceful, PERSISTED credential failure at the first interview turn.

When the interview send path fails closed with ``CredentialNotFound`` (e.g. a
Copilot session whose provider was never connected), ``WorkflowService.send_message``
must:

1. map it to a graceful ``HTTPException(503, {"error": "credential_required", ...})``
   instead of a raw 500, and
2. persist ``status='interview_paused'`` on a SEPARATE committed session so the
   marker survives the ``get_db`` rollback that fires on the raised 503 (R21) —
   the request session's own write would be rolled back and the paused banner
   could never replay.

The side session is faked here so the assertion is independent of the in-memory
SQLite test engine's per-connection semantics; it captures exactly what the
handler committed.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.project import Project
from app.models.session import PentestSession
from app.models.user import Team, User, UserRole
from app.orchestrator.llm.credential_resolver import CredentialNotFound
from app.orchestrator.workflow_service import WorkflowService


async def _seed(db):
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
        llm_provider_pref="copilot",
    )
    db.add(session)
    await db.flush()
    return user, session


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

    async def flush(self) -> None:  # AuditLogger.log flushes the audit row
        pass

    async def commit(self) -> None:
        self.committed = True


@pytest.mark.asyncio
async def test_credential_not_found_pauses_and_persists_on_side_session(db, monkeypatch):
    from app.orchestrator import workflow_service as ws_mod
    from app.orchestrator.llm import router as router_mod

    # Route through the multi-provider branch so route() resolves a credential.
    monkeypatch.setattr(ws_mod.settings, "osa_flow_ui_enabled", False)
    monkeypatch.setattr(ws_mod.settings, "osa_multi_provider_llm", True)

    async def _raise_credential(self, *args, **kwargs):
        raise CredentialNotFound("no credential for provider='copilot'")

    monkeypatch.setattr(router_mod.LLMRouter, "route", _raise_credential)

    # Capture the SEPARATE committed side-session write (R21).
    side_row = SimpleNamespace(status="draft", interview_state="not_started", resume_token=None)
    fake_side = _FakeSideSession(side_row)
    monkeypatch.setattr(ws_mod, "async_session", lambda: fake_side)

    user, session = await _seed(db)
    svc = WorkflowService(db=db, model_client=SimpleNamespace())

    with pytest.raises(HTTPException) as exc_info:
        await svc.send_message(
            session_id=session.id,
            user_message="recon the target",
            user=user,
        )

    # 1) graceful 503 credential_required (never a raw 500).
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["error"] == "credential_required"
    assert "message" in exc_info.value.detail
    assert exc_info.value.detail["resume_token"]

    # 2) the paused marker was written AND committed on the SEPARATE session.
    assert fake_side.committed is True
    assert side_row.status == "interview_paused"
    assert side_row.interview_state == "interview_paused"
    assert side_row.resume_token is not None
    # audit row was written on the same committed side session.
    assert len(fake_side.added) == 1
