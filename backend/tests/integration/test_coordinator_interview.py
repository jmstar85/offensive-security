"""PR5: Coordinator-owned, Ollama-driven, ambiguity-gated interview that builds the
Understanding from the transcript and never starves the Performer lease.

Uses a fake LLM client (no real Ollama). The interview is turn-based (each
``run_interview_turn`` is one discrete turn), so it runs outside the Performer
concurrency lease.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.orchestrator.coordinator import CoordinatorService, LLMUnderstandingBuilder
from app.models.project import Project
from app.models.session import PentestSession
from app.models.user import Team, User, UserRole


class _FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)

    async def send(self, model_id, messages, system, max_tokens=2048):  # noqa: ANN001
        item = self._responses.pop(0) if self._responses else "{}"
        return SimpleNamespace(text=item, tokens_in=1, tokens_out=1, raw={})


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()

    async def _flush() -> None:
        pass

    db.flush = _flush
    db.execute = AsyncMock()
    return db


async def _seed_session(db) -> PentestSession:
    team = Team(name=f"team-{uuid.uuid4()}")
    db.add(team)
    await db.flush()
    user = User(
        email=f"u-{uuid.uuid4()}@example.com", password_hash="x" * 60,
        full_name="Tester", role=UserRole.MEMBER, team_id=team.id,
    )
    db.add(user)
    await db.flush()
    project = Project(name="p", client_name="acme", status="active", created_by=user.id)
    db.add(project)
    await db.flush()
    session_row = PentestSession(
        project_id=project.id, prompt="scan the cluster", status="pending",
        interview_state="interviewing", interview_turn_count=0,
        ambiguity_score=Decimal("1.000"),
    )
    db.add(session_row)
    await db.flush()
    return session_row


# ── LLM understanding from transcript ────────────────────────────────────────

async def test_llm_understanding_from_transcript():
    client = _FakeClient([
        '{"target_kind":"web_app","detected_stack":["nginx"],'
        '"entry_points":["scanme.nmap.org"],"constraints":["recon-only"]}'
    ])
    transcript = [
        {"role": "user", "content": "test scanme.nmap.org, it runs nginx"},
        {"role": "assistant", "content": "What is the authorized scope?"},
        {"role": "user", "content": "recon only, scanme.nmap.org"},
    ]
    u = await LLMUnderstandingBuilder().build(
        transcript, {"domains": ["scanme.nmap.org"], "ip_ranges": []}, client
    )
    assert u is not None
    assert u.target_kind == "web_app"
    assert "nginx" in u.detected_stack
    assert u.raw_signals["source"] == "llm_interview"


async def test_build_understanding_falls_back_without_client():
    """No client (default anthropic, no injection) → deterministic builder."""
    coord = CoordinatorService(_mock_db())
    u = await coord.build_understanding(
        prompt="scan example.com running nginx",
        target={"domains": ["example.com"], "ip_ranges": []},
    )
    assert u.target_kind == "web_app"  # deterministic UnderstandingBuilder
    assert u.raw_signals.get("source") != "llm_interview"


async def test_build_understanding_falls_back_on_unparseable_llm():
    """Garbage LLM output → None → deterministic fallback (replay-safe)."""
    coord = CoordinatorService(_mock_db())
    u = await coord.build_understanding(
        prompt="scan example.com",
        target={"domains": ["example.com"], "ip_ranges": []},
        transcript=[{"role": "user", "content": "x"}],
        model_client=_FakeClient(["this is not json"]),
    )
    assert u.raw_signals.get("source") != "llm_interview"


# ── lease non-starvation (the PR5 BLOCKING fix) ──────────────────────────────

async def test_interview_turn_does_not_starve_performer_lease(db):
    from app.orchestrator.performer import _PerformerLease, _active_performers

    session = await _seed_session(db)
    coord = CoordinatorService(db)
    before = set(_active_performers)

    client = _FakeClient([
        '{"ambiguity":0.8,"blockers":["need scope"],"reasoning":"clarify","draft_plan":{"steps":[]}}'
    ])
    await coord.run_interview_turn(
        session=session, user_content="do a pentest", model_client=client
    )

    # The interview turn acquired NO Performer lease.
    assert set(_active_performers) == before
    # And a Performer slot is still freely acquirable (cap not consumed).
    async with _PerformerLease(uuid.uuid4()):
        pass


# ── blocking turn-based interview (inline wait) ──────────────────────────────

async def test_interview_inline_wait_state_machine(db):
    session = await _seed_session(db)
    coord = CoordinatorService(db)

    high = _FakeClient([
        '{"ambiguity":0.8,"blockers":["need target scope"],"reasoning":"clarify","draft_plan":{"steps":[]}}'
    ])
    r1 = await coord.run_interview_turn(
        session=session, user_content="do a pentest", model_client=high
    )
    assert r1.next_state == "interviewing"
    assert session.interview_state == "interviewing"

    low = _FakeClient([
        '{"ambiguity":0.1,"blockers":[],"reasoning":"clear","draft_plan":{"steps":[]}}'
    ])
    r2 = await coord.run_interview_turn(
        session=session, user_content="target scanme.nmap.org, web app, recon only",
        model_client=low,
    )
    assert r2.next_state == "ready_for_review"
    assert session.interview_state == "ready_for_review"
