"""Performer end-to-end smoke cycle (v4.0 P2a).

Exercises the Performer engine running the 6 Minimal v1 roles registered
through `app.orchestrator.roles.seed`. P2a verifies the wire-up: every role
is registered, the Performer can dispatch a structured tool envelope through
the safety chain, and the per-tool Adviser counters update correctly. The
real LLM-driven role chain + AgentExecution persistence land in P4.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

# Importing `seed` is the only thing that populates ROLE_REGISTRY in tests.
from app.orchestrator.roles import seed as _seed  # noqa: F401  (side-effect)
from app.orchestrator.roles.registry import get_role, list_roles
from app.orchestrator.performer import Performer


MINIMAL_6 = {"generator", "pentester", "memorist", "adviser", "reflector", "reporter"}


def test_seed_registers_all_six_roles():
    """`assert_registered` ran on `seed` import; verify each slug resolves."""
    assert MINIMAL_6 <= set(list_roles())
    for slug in MINIMAL_6:
        cls = get_role(slug)
        assert cls is not None


@pytest.mark.asyncio
async def test_full_role_cycle_smoke():
    """Generator → Pentester (1 nmap dispatch) → Reporter cycle.

    Each role's P2a smoke `run()` returns its fixture envelope. The
    Pentester step exercises the dispatcher for `nmap` + `port_scan`.
    """
    db = AsyncMock()
    sid = uuid.uuid4()
    performer = Performer(db=db, session_id=sid)

    # Step 1: Generator
    gen_cls = get_role("generator")
    generator = gen_cls()
    performer.register_role(generator)
    gen_result = await generator.run(performer=performer, context={})
    assert gen_result.role_name == "generator"
    assert "ambiguity" in gen_result.messages[0]["content"]

    # Step 2: Pentester dispatches a structured tool call
    pen_cls = get_role("pentester")
    pentester = pen_cls()
    performer.register_role(pentester)
    pen_result = await pentester.run(performer=performer, context={})
    assert pen_result.role_name == "pentester"

    dispatch = await performer._dispatch_tool(
        "nmap",
        {"intent": "port_scan", "config": {"targets": ["127.0.0.1"]}},
    )
    assert dispatch["approved"] is True
    assert dispatch["tool"] == "nmap"
    assert dispatch["synthetic_step"]["agent"] == "nmap"
    # Per-tool counter incremented exactly once.
    assert performer.state.same_tool_counter["nmap"] == 1
    assert performer.state.total_tool_calls == 1

    # Step 3: Reporter wraps up the cycle
    rep_cls = get_role("reporter")
    reporter = rep_cls()
    performer.register_role(reporter)
    rep_result = await reporter.run(performer=performer, context={})
    assert rep_result.role_name == "reporter"
    assert rep_result.finished is True


@pytest.mark.asyncio
async def test_reflector_wraps_a_role_run():
    """Reflector wrap policy applies cleanly to a role's run() coroutine."""
    from app.orchestrator.roles.reflector import wrap

    rep_cls = get_role("reporter")
    reporter = rep_cls()

    result = await wrap(reporter.run, performer=None, context={})
    assert result.role_name == "reporter"
    assert result.error is None  # smoke run never raises


@pytest.mark.asyncio
async def test_adviser_triggered_after_repeated_dispatch():
    """5+ same-tool dispatches trip the Adviser trigger predicate."""
    db = AsyncMock()
    performer = Performer(db=db, session_id=uuid.uuid4())

    for _ in range(4):
        await performer._dispatch_tool(
            "nmap",
            {"intent": "port_scan", "config": {"targets": ["127.0.0.1"]}},
        )

    fifth = await performer._dispatch_tool(
        "nmap",
        {"intent": "port_scan", "config": {"targets": ["127.0.0.1"]}},
    )
    assert fifth["adviser_should_fire"] is True
    assert "same_tool_called_5_times" in fifth["adviser_reason"]


@pytest.mark.asyncio
async def test_run_session_iterates_topological_order_with_reflector_wrap():
    """v4.0 gap-fill — Performer.run_session walks Generator → Pentester →
    Reporter, wrapping each role.run() in the Reflector retry policy."""
    db = AsyncMock()
    performer = Performer(db=db, session_id=uuid.uuid4())

    performer.register_role(get_role("generator")())
    performer.register_role(get_role("pentester")())
    performer.register_role(get_role("reporter")())

    results = await performer.run_session()

    # Topological order honored: generator first, then pentester, then reporter.
    assert [r.role_name for r in results] == ["generator", "pentester", "reporter"]
    # Reporter signals finished=True; loop terminates normally.
    assert results[-1].finished is True
    # Iteration counter ticked exactly once per role.
    assert performer.state.iteration == 3
    # Shared context carries each role's last assistant message for the next.
    assert "generator_output" in performer.state.context
    assert "pentester_output" in performer.state.context
    assert "reporter_output" in performer.state.context


@pytest.mark.asyncio
async def test_run_session_skips_unregistered_roles():
    """If only a subset of roles is registered (common when AmbiguityLoop
    runs Generator alone), `run_session` walks just the registered ones."""
    db = AsyncMock()
    performer = Performer(db=db, session_id=uuid.uuid4())
    performer.register_role(get_role("generator")())

    results = await performer.run_session()
    assert len(results) == 1
    assert results[0].role_name == "generator"


@pytest.mark.asyncio
async def test_run_session_halts_on_role_error_after_reflector_retries():
    """If a role keeps raising past Reflector retries, the loop halts and
    surfaces the error as the last result."""
    from app.orchestrator.roles.base import Role, RoleResult

    db = AsyncMock()
    performer = Performer(db=db, session_id=uuid.uuid4())

    @dataclass
    class _FailingRole(Role):
        slug: str = "generator"

        async def run(self, performer, context):
            raise RuntimeError("persistent generator failure")

    performer.register_role(
        _FailingRole(
            name="generator",
            system_prompt="x",
            llm_model="claude-sonnet-4-6",
        )
    )

    # Use a fast no-retry policy so the test doesn't sleep.
    import app.orchestrator.roles.reflector as reflector_mod
    from app.core.config import settings

    original = settings.reflector_retry_backoff_seconds
    settings.reflector_retry_backoff_seconds = [0.0, 0.0, 0.0]
    try:
        results = await performer.run_session()
    finally:
        settings.reflector_retry_backoff_seconds = original

    assert len(results) == 1
    assert results[0].role_name == "reflector"
    assert results[0].error is not None
    assert "persistent generator failure" in results[0].error
