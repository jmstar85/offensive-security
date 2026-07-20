"""Regression: interview envelope truncation salvage + draft-plan no-wipe.

Root cause of session 0f9c5646: a 13KB interview turn truncated at the model's
max_tokens ceiling mid-draft_plan; AmbiguityLoop._parse_envelope could not parse
the incomplete JSON and collapsed to ambiguity=1.0, discarding the ambiguity
(0.08) + blockers that were fully present at the START of the JSON, AND wiping
the prior good draft_plan_json with an empty skeleton (which later approved as a
0-step no-op run). These tests lock in the salvage + preservation behaviour.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.models.project import Project
from app.models.session import PentestSession
from app.models.user import Team, User, UserRole
from app.orchestrator.ambiguity_loop import AmbiguityLoop
from app.orchestrator.roles.base import RoleResult

# A realistic truncated turn: the fence + early scalar fields are intact, the
# JSON is cut off mid-draft_plan (exactly the session-0f9c5646 shape).
_TRUNCATED = (
    '```json\n{\n'
    '  "ambiguity": 0.08,\n'
    '  "blockers": ["No operator-supplied flag authorising active_exploit"],\n'
    '  "reasoning": "Target now concretely scoped to 20.196.207.37.",\n'
    '  "draft_plan": {\n'
    '    "steps": [\n'
    '      {"order": 1, "agent": "nmap", "action": "port_'
)

_GOOD_PRIOR_DRAFT = {
    "target_summary": "acme staging",
    "risk_level": "low",
    "steps": [
        {"order": 1, "agent": "nmap", "action": "port_scan", "tier": "active_recon",
         "config": {"target": "10.0.0.5"}},
        {"order": 2, "agent": "httpx", "action": "http_status", "tier": "passive_low_touch",
         "config": {"target": "10.0.0.5"}},
    ],
}


# ── static _parse_envelope unit tests ────────────────────────────────────────


def test_parse_envelope_salvages_truncated_turn():
    parsed = AmbiguityLoop._parse_envelope(_TRUNCATED)
    assert parsed["ambiguity"] == 0.08
    assert "envelope_parse_failed" not in parsed.get("blockers", [])
    assert parsed.get("_salvaged") is True
    # salvage must OMIT draft_plan so run_turn preserves the prior draft
    assert "draft_plan" not in parsed


def test_parse_envelope_total_garbage_still_sentinels():
    parsed = AmbiguityLoop._parse_envelope("not-a-json-or-dict")
    assert parsed["ambiguity"] == 1.0
    assert "envelope_parse_failed" in parsed["blockers"]
    assert "draft_plan" not in parsed  # sentinel now also omits it


def test_parse_envelope_valid_full_json_unchanged():
    full = (
        '{"ambiguity": 0.1, "blockers": [], "reasoning": "ok",'
        ' "draft_plan": {"steps": [{"order": 1, "agent": "nmap"}]}}'
    )
    parsed = AmbiguityLoop._parse_envelope(full)
    assert parsed["ambiguity"] == 0.1
    assert parsed["draft_plan"]["steps"][0]["agent"] == "nmap"
    assert "_salvaged" not in parsed


# ── run_turn draft-preservation integration ──────────────────────────────────


async def _seed(db, *, draft=None) -> PentestSession:
    team = Team(name=f"t-{uuid.uuid4()}")
    db.add(team)
    await db.flush()
    user = User(email=f"u-{uuid.uuid4()}@x.com", password_hash="x" * 60,
                full_name="T", role=UserRole.MEMBER, team_id=team.id)
    db.add(user)
    await db.flush()
    project = Project(name="p", client_name="acme", status="active", created_by=user.id)
    db.add(project)
    await db.flush()
    s = PentestSession(
        project_id=project.id, prompt="scan", status="pending",
        interview_state="interviewing", interview_turn_count=1,
        ambiguity_score=Decimal("0.150"), draft_plan_json=draft,
    )
    db.add(s)
    await db.flush()
    return s


def _patch_generator(monkeypatch, content: str):
    async def _fake_run(self, performer=None, context=None, client_factory=None):
        return RoleResult(
            role_name="generator",
            messages=[{"role": "assistant", "content": content}],
            finished=False,
            tool_calls=0,
        )
    monkeypatch.setattr(
        "app.orchestrator.roles.generator.Generator.run", _fake_run
    )


@pytest.mark.asyncio
async def test_run_turn_preserves_prior_draft_on_truncation(db, monkeypatch):
    """A truncated turn salvages ambiguity 0.08 but keeps the prior 2-step draft
    instead of wiping it to an empty skeleton."""
    _patch_generator(monkeypatch, _TRUNCATED)
    session = await _seed(db, draft=dict(_GOOD_PRIOR_DRAFT))

    result = await AmbiguityLoop(db=db).run_turn(session, user_content="the IP is 20.196.207.37")

    assert result.salvaged is True
    assert float(session.ambiguity_score) == 0.08
    assert "envelope_parse_failed" not in result.blockers
    # prior draft preserved — NOT wiped to {"steps": []}
    assert len(session.draft_plan_json["steps"]) == 2


@pytest.mark.asyncio
async def test_run_turn_honors_clean_intentional_empty_clear(db, monkeypatch):
    """A CLEAN (parseable) high-ambiguity envelope with steps:[] is honored — the
    guard keys on draft_plan KEY PRESENCE, not non-empty steps, so an intentional
    rescope-to-ambiguous clear is not over-preserved."""
    clean_clear = (
        '{"ambiguity": 0.7, "blockers": ["scope unclear again"],'
        ' "reasoning": "rescoped", "draft_plan": {"steps": []}}'
    )
    _patch_generator(monkeypatch, clean_clear)
    session = await _seed(db, draft=dict(_GOOD_PRIOR_DRAFT))

    result = await AmbiguityLoop(db=db).run_turn(session, user_content="actually, unclear")

    assert result.salvaged is False
    assert session.draft_plan_json["steps"] == []  # intentional clear honored
