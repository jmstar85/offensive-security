"""PR7 — Assistant per-session turn mutex + lease + step/depth caps (Principle 4a).

- Two concurrent turns on ONE session → exactly one runs, one is refused (409).
- The ADR-003 per-session lease is held while a turn is in-flight (so it is never
  released early by an overlapping turn).
- The per-turn step cap bounds a runaway loop.
- The sub-role-depth cap bounds nested role launches at the delegate_tool_call
  chokepoint (independent of the lease and the mutex).
"""
from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import app.orchestrator.assistant_service as asvc
from app.agents.base import AgentEvent
from app.core.config import settings
from app.orchestrator.assistant_service import AssistantService, AssistantTurnInProgress
from app.orchestrator.performer import Performer, _active_performers
from app.orchestrator.roles import seed as _seed  # noqa: F401  (populate ROLE_REGISTRY)
from app.orchestrator.runtime_delegator import delegate_tool_call


# ── fakes (self-contained) ────────────────────────────────────────────────────


class _Result:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj

    def scalars(self):
        return self

    def first(self):
        return self._obj


class _FakeDB:
    def __init__(self, session, target):
        self._session, self._target = session, target
        self.added: list = []

    async def execute(self, stmt, *a, **k):  # noqa: ANN001
        t = str(stmt).lower()
        if "pentest_sessions" in t:
            return _Result(self._session)
        if "targets" in t:
            return _Result(self._target)
        return _Result(None)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        pass


def _session():
    sess = SimpleNamespace(
        id=uuid.uuid4(), project_id=uuid.uuid4(), mode="assistant",
        approval_flags={}, model_map={}, llm_provider_pref="ollama",
        model_id="qwen3-14b-96k:latest",
    )
    tgt = SimpleNamespace(ip_ranges=[], domains=[], whitelist_rules={})
    return sess, tgt


def _user():
    return SimpleNamespace(id=uuid.uuid4())


def _fake_adapter(agent_type="passive_recon", *, executed=None):
    class _A:
        async def execute(self, target, config, holder=None):  # noqa: ANN001
            if executed is not None:
                executed.append(agent_type)
            yield AgentEvent("status", agent_type, "x",
                             {"status": "completed", "result": {"findings": []}})
    return _A()


_RECON = '{"tool": "passive_recon", "intent": "passive_dns_recon", "config": {}}'
_DONE = '{"done": true, "summary": "done"}'


# ── concurrent same-session → one 409, lease held for exactly one turn ─────────


@pytest.mark.asyncio
async def test_concurrent_same_session_second_turn_409_and_lease_held():
    session, target = _session()
    session_uuid = session.id
    started = asyncio.Event()
    release = asyncio.Event()

    class _BlockingClient:
        async def send(self, model_id, messages, system, max_tokens=2048):  # noqa: ANN001
            started.set()
            await release.wait()
            return SimpleNamespace(text=_DONE, tokens_in=1, tokens_out=1, raw={})

    with patch.object(asvc, "resolve_session_role_client",
                      AsyncMock(return_value=_BlockingClient())):
        svc1 = AssistantService(_FakeDB(session, target))
        turn1 = asyncio.create_task(svc1.turn(session_uuid, "first", _user()))
        await asyncio.wait_for(started.wait(), timeout=2.0)

        # Turn 1 is in-flight: it holds the per-session lease.
        assert session_uuid in _active_performers

        # A concurrent second turn on the SAME session is refused (409).
        svc2 = AssistantService(_FakeDB(session, target))
        with pytest.raises(AssistantTurnInProgress):
            await svc2.turn(session_uuid, "second", _user())

        # Let turn 1 finish.
        release.set()
        result1 = await asyncio.wait_for(turn1, timeout=2.0)

    assert result1.content.startswith("[done]")
    # Lease released after the single live turn completed.
    assert session_uuid not in _active_performers


@pytest.mark.asyncio
async def test_sequential_turns_on_same_session_both_run():
    """After a turn completes the mutex is released, so a later turn runs."""
    session, target = _session()

    class _DoneClient:
        async def send(self, model_id, messages, system, max_tokens=2048):  # noqa: ANN001
            return SimpleNamespace(text=_DONE, tokens_in=1, tokens_out=1, raw={})

    with patch.object(asvc, "resolve_session_role_client",
                      AsyncMock(return_value=_DoneClient())):
        for _i in range(2):  # two sequential turns on the same session
            res = await AssistantService(_FakeDB(session, target)).turn(
                session.id, "go", _user()
            )
            assert res.content.startswith("[done]")


# ── per-turn step cap ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_per_turn_step_cap_enforced(monkeypatch):
    """A model that never emits done trips the per-turn step cap."""
    monkeypatch.setattr(settings, "assistant_max_steps_per_turn", 2, raising=False)
    session, target = _session()
    executed: list[str] = []

    class _NeverDone:
        async def send(self, model_id, messages, system, max_tokens=2048):  # noqa: ANN001
            return SimpleNamespace(text=_RECON, tokens_in=1, tokens_out=1, raw={})

    with patch.object(asvc, "resolve_session_role_client",
                      AsyncMock(return_value=_NeverDone())), \
         patch("app.orchestrator.safety_exec.get_adapter",
               return_value=_fake_adapter("passive_recon", executed=executed)):
        result = await AssistantService(_FakeDB(session, target)).turn(
            session.id, "loop", _user()
        )
    assert result.content == "[capped] step cap reached"
    assert len(executed) == 2, f"expected exactly the cap of 2 dispatches, got {executed}"


# ── sub-role-depth cap at the delegate_tool_call chokepoint ───────────────────


@pytest.mark.asyncio
async def test_sub_role_depth_cap_bounds_nested_launch():
    """At/over settings.max_sub_role_depth a nested role launch through
    delegate_tool_call (trusted lane) is refused with a depth_capped result,
    independent of the per-session lease."""
    p = Performer(AsyncMock(), uuid.uuid4())
    p.state.sub_role_depth = int(getattr(settings, "max_sub_role_depth", 3))
    out = await delegate_tool_call(p, "memorist", {}, allow_role_invocation=True)
    assert out["kind"] == "depth_capped"
    assert "sub_role_depth_exceeded" in out["result"]["blocked_reason"]


@pytest.mark.asyncio
async def test_depth_counter_restored_after_nested_launch():
    """The depth counter is incremented for the duration of a nested launch and
    restored afterwards (finally), so it does not leak across dispatches."""
    from app.orchestrator.roles import seed as _s  # noqa: F401
    p = Performer(AsyncMock(), uuid.uuid4())
    assert p.state.sub_role_depth == 0
    out = await delegate_tool_call(p, "memorist", {}, allow_role_invocation=True)
    assert out["kind"] == "role"
    assert p.state.sub_role_depth == 0  # restored
