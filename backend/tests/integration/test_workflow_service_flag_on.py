"""WorkflowService flag-ON path tests (v4.0 P4 wiring).

When `osa_flow_ui_enabled=True`, `WorkflowService.send_message` routes the
chat turn through `AmbiguityLoop.run_turn` (Generator role smoke envelope
in P4; live Anthropic call replaces in v3.4). OFF path remains the v3.2.1
ModelClient flow — verified by the 223 baseline tests.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, cast
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.msgchain import MsgChain
from app.models.project import Project
from app.models.session import PentestSession, WorkflowMessage
from app.models.user import Team, User, UserRole
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
    )
    db.add(session)
    await db.flush()
    return user, session


@pytest.mark.asyncio
async def test_flag_on_routes_through_ambiguity_loop(db, monkeypatch):
    """With flag ON, send_message calls AmbiguityLoop and persists a MsgChain.

    Generator inside AmbiguityLoop now makes a live Anthropic call when a
    ModelClient is injected (gap-fill 2/3). Inject a stub client returning
    a deterministic envelope so persistence + state transitions can be
    asserted without a real API call.
    """
    from app.core import config as cfg
    from app.orchestrator import workflow_service as ws_mod

    monkeypatch.setattr(cfg.settings, "osa_flow_ui_enabled", True)
    monkeypatch.setattr(ws_mod.settings, "osa_flow_ui_enabled", True)

    class _StubClient:
        async def send(self, *, model_id, messages, system, max_tokens=2048):
            envelope = (
                '{"ambiguity": 0.20, "blockers": [], '
                '"reasoning": "Stub generator envelope.", '
                '"draft_plan": {"steps": []}}'
            )
            return SimpleNamespace(
                text=envelope, tokens_in=12, tokens_out=14, raw=None
            )

    user, session = await _seed(db)
    svc = WorkflowService(db=db, model_client=cast(Any, _StubClient()))
    result = await svc.send_message(
        session_id=session.id,
        user_message="Recon 10.0.0.0/24 for known CVEs",
        user=user,
    )

    # Two WorkflowMessage rows: user turn + assistant turn (latter persisted by AmbiguityLoop).
    msgs = (
        await db.execute(
            select(WorkflowMessage)
            .where(WorkflowMessage.pentest_session_id == session.id)
            .order_by(WorkflowMessage.turn_index, WorkflowMessage.created_at)
        )
    ).scalars().all()
    assert len(msgs) >= 2
    assert msgs[0].role == "user"

    # AmbiguityLoop persists one MsgChain scoped to the generator role.
    chains = (
        await db.execute(
            select(MsgChain).where(MsgChain.pentest_session_id == session.id)
        )
    ).scalars().all()
    assert len(chains) == 1
    assert chains[0].role_name == "generator"

    # MessageResult shape preserved (matches v3.2.1 contract).
    assert result.user_message.role == "user"
    assert result.assistant_message.role == "assistant"
    assert result.new_state in {"interviewing", "ready_for_review", "needs_human_review"}


@pytest.mark.asyncio
async def test_flag_off_unchanged_path_does_not_create_msgchain(db, monkeypatch):
    """Flag OFF (default) — AmbiguityLoop is NOT invoked, no MsgChain row is
    created. This guards the 223 baseline behavior."""
    from app.core import config as cfg
    from app.orchestrator import workflow_service as ws_mod

    monkeypatch.setattr(cfg.settings, "osa_flow_ui_enabled", False)
    monkeypatch.setattr(ws_mod.settings, "osa_flow_ui_enabled", False)
    # Also pin the multi-provider flag OFF so this legacy-path test exercises the
    # injected ModelClient (`_StubClient`) rather than routing through
    # LLMRouter.route() → the per-user credential vault (which fails closed with
    # CredentialNotFound → a persisted interview_paused pause). This matches the
    # sibling `_legacy_chat_path` fixture in test_workflow_chat_flow.py.
    monkeypatch.setattr(cfg.settings, "osa_multi_provider_llm", False)
    monkeypatch.setattr(ws_mod.settings, "osa_multi_provider_llm", False)

    # Mock the legacy ModelClient call so we don't make a real Anthropic
    # request. WorkflowService instantiates ModelClient lazily when None.
    class _StubClient:
        async def send(self, *, model_id, messages, system):
            return SimpleNamespace(
                text='{"ambiguity": 0.2, "blockers": [], "reasoning": "ok", "draft_plan": {"steps": []}}',
                stop_reason="end_turn",
                usage=SimpleNamespace(input_tokens=10, output_tokens=10),
            )

    user, session = await _seed(db)
    svc = WorkflowService(db=db, model_client=cast(Any, _StubClient()))
    try:
        await svc.send_message(
            session_id=session.id,
            user_message="recon",
            user=user,
        )
    except Exception:
        # The OFF path may raise on missing dependencies in unit-test mode
        # (e.g. budget guard, missing prompts). That's not what this test
        # verifies — we only care that MsgChain rows are NOT created via
        # AmbiguityLoop on the OFF path.
        pass

    chains = (
        await db.execute(
            select(MsgChain).where(MsgChain.pentest_session_id == session.id)
        )
    ).scalars().all()
    assert chains == []  # No msgchain → AmbiguityLoop did not fire.


@pytest.mark.parametrize(
    "autoblock,autoblock_target,legacy_target,ambiguity,expected_state,expected_target",
    [
        (True, 0.20, 0.35, 0.19, "ready_for_review", 0.20),
        (True, 0.20, 0.35, 0.20, "ready_for_review", 0.20),
        (True, 0.20, 0.35, 0.21, "interviewing", 0.20),
        (True, 0.20, 0.35, 0.30, "interviewing", 0.20),
        (True, 0.12, 0.40, 0.13, "interviewing", 0.12),
        (False, 0.20, 0.35, 0.34, "ready_for_review", 0.35),
        (False, 0.20, 0.35, 0.35, "ready_for_review", 0.35),
        (False, 0.20, 0.35, 0.36, "interviewing", 0.35),
    ],
)
async def test_flow_turn_uses_the_advertised_interview_target(
    db, monkeypatch: pytest.MonkeyPatch, autoblock: bool, autoblock_target: float,
    legacy_target: float, ambiguity: float, expected_state: str, expected_target: float,
) -> None:
    from app.api.v1.pentest_sessions import _serialize
    from app.core.config import settings

    monkeypatch.setattr(settings, "osa_flow_ui_enabled", True)
    monkeypatch.setattr(settings, "osa_interview_autoblock_enabled", autoblock)
    monkeypatch.setattr(settings, "osa_interview_autoblock_threshold", autoblock_target)
    monkeypatch.setattr(settings, "workflow_ambiguity_threshold", legacy_target)

    class StubClient:
        async def send(self, *, model_id, messages, system, max_tokens=2048):
            return SimpleNamespace(
                text=json.dumps({
                    "ambiguity": ambiguity,
                    "blockers": [],
                    "reasoning": "",
                    "draft_plan": {
                        "target_summary": "acme staging",
                        "risk_level": "low",
                        "steps": [{
                            "agent": "nmap", "action": "port_scan", "tier": "active_recon",
                        }],
                    },
                }),
                tokens_in=1, tokens_out=1, raw=None,
            )

    user, session = await _seed(db)
    result = await WorkflowService(db=db, model_client=cast(Any, StubClient())).send_message(
        session_id=session.id, user_message="Confirm the staging scope.", user=user,
    )

    assert result.new_state == expected_state
    assert session.interview_state == expected_state
    assert _serialize(session).interview_ambiguity_target == expected_target


@pytest.mark.parametrize("flow_on", [True, False], ids=["flow", "legacy"])
async def test_conversation_masked_at_storage_both_modes(
    db, monkeypatch: pytest.MonkeyPatch, flow_on: bool,
) -> None:
    from app.core.config import settings
    from app.models.msgchain import MsgChain

    monkeypatch.setattr(settings, "osa_flow_ui_enabled", flow_on)
    if not flow_on:
        monkeypatch.setattr(settings, "osa_multi_provider_llm", False)
    secret = "sk-abc123def456ghi789jkl"

    class Leaky:
        async def send(self, *, model_id, messages, system, max_tokens=2048):
            return SimpleNamespace(
                text=json.dumps({
                    "ambiguity": 0.2, "blockers": [secret], "reasoning": secret,
                    "draft_plan": {"steps": []},
                }),
                tokens_in=1, tokens_out=1, raw=None,
            )

    client: Any = Leaky()
    user, session = await _seed(db)
    try:
        await WorkflowService(db=db, model_client=client).send_message(
            session_id=session.id, user_message=f"scan {secret}", user=user,
        )
    except Exception:  # noqa: BLE001 — legacy path may raise on missing deps; storage still checked
        pass
    # Every stored WorkflowMessage (user AND assistant) + its metadata is masked.
    rows = (await db.execute(
        select(WorkflowMessage).where(WorkflowMessage.pentest_session_id == session.id)
    )).scalars().all()
    assert rows
    blob = " ".join(
        [r.content or "" for r in rows] + [json.dumps(r.blockers_json) for r in rows]
    )
    assert secret not in blob
    chains = (await db.execute(
        select(MsgChain).where(MsgChain.pentest_session_id == session.id)
    )).scalars().all()
    assert secret not in json.dumps([c.messages_json for c in chains])
