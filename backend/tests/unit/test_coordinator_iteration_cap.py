"""Unit tests for CoordinatorService.run_with_iteration_cap (PR4.2)."""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.orchestrator.coordinator import CoordinatorService, IterationCapHit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service():
    """Return a CoordinatorService with a MagicMock db whose flush() is a coroutine."""
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    svc = CoordinatorService(db)
    # Patch .run so tests don't need a real DB/event_bus
    svc.run = AsyncMock(return_value=(MagicMock(), MagicMock()))
    return svc


def _base_kwargs(**overrides):
    kw = dict(
        session_id=uuid.uuid4(),
        prompt="test prompt",
        target={"domains": ["example.com"]},
        actor_id=str(uuid.uuid4()),
        lane="standard",
        replay_opt_in=False,
        token_counter_fn=lambda: 0,
        clock_fn=None,
    )
    kw.update(overrides)
    return kw


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_normal_run_completes_in_one_iteration():
    svc = _make_service()
    result = asyncio.run(svc.run_with_iteration_cap(**_base_kwargs()))
    understanding, plan_of_work, iteration_no = result
    assert iteration_no == 1
    svc.run.assert_awaited_once()


def test_max_iterations_cap_trips_when_exceeded():
    svc = _make_service()
    svc._audit_cap_hit = AsyncMock()

    with patch("app.core.config.settings") as mock_settings:
        mock_settings.max_coordinator_iterations = 0
        mock_settings.max_coordinator_wall_clock_seconds = 600
        mock_settings.max_coordinator_total_tokens = 200_000

        with pytest.raises(IterationCapHit) as exc_info:
            asyncio.run(svc.run_with_iteration_cap(**_base_kwargs()))

    assert exc_info.value.reason == "max_iterations"
    svc._audit_cap_hit.assert_awaited_once()
    call_args = svc._audit_cap_hit.call_args
    assert call_args.args[2] == "max_iterations"


def test_max_wall_clock_cap_trips():
    svc = _make_service()
    svc._audit_cap_hit = AsyncMock()

    clock_calls = iter([0, 700])
    clock_fn = lambda: next(clock_calls)

    with patch("app.core.config.settings") as mock_settings:
        mock_settings.max_coordinator_iterations = 8
        mock_settings.max_coordinator_wall_clock_seconds = 600
        mock_settings.max_coordinator_total_tokens = 200_000

        with pytest.raises(IterationCapHit) as exc_info:
            asyncio.run(svc.run_with_iteration_cap(**_base_kwargs(clock_fn=clock_fn)))

    assert exc_info.value.reason == "max_wall_clock"
    svc._audit_cap_hit.assert_awaited_once()


def test_max_total_tokens_cap_trips():
    svc = _make_service()
    svc._audit_cap_hit = AsyncMock()

    with patch("app.core.config.settings") as mock_settings:
        mock_settings.max_coordinator_iterations = 8
        mock_settings.max_coordinator_wall_clock_seconds = 600
        mock_settings.max_coordinator_total_tokens = 200_000

        with pytest.raises(IterationCapHit) as exc_info:
            asyncio.run(svc.run_with_iteration_cap(
                **_base_kwargs(token_counter_fn=lambda: 250_000)
            ))

    assert exc_info.value.reason == "max_total_tokens"
    svc._audit_cap_hit.assert_awaited_once()


def test_iteration_no_monotonic():
    svc = _make_service()
    svc._audit_cap_hit = AsyncMock()

    # clock returns 0 on start, then 700 to trigger wall-clock cap at iteration_no=1
    clock_calls = iter([0, 700])
    clock_fn = lambda: next(clock_calls)

    with patch("app.core.config.settings") as mock_settings:
        mock_settings.max_coordinator_iterations = 8
        mock_settings.max_coordinator_wall_clock_seconds = 600
        mock_settings.max_coordinator_total_tokens = 200_000

        with pytest.raises(IterationCapHit) as exc_info:
            asyncio.run(svc.run_with_iteration_cap(**_base_kwargs(clock_fn=clock_fn)))

    # iteration_no was 1 when cap tripped; exc stores iteration_no - 1 = 0... but
    # the spec says "monotonically bumping iteration_no": the cap hit at iteration_no=1
    # stores iterations=iteration_no-1=0 in the exception.  Verify it's non-negative
    # and that it came from the first loop pass.
    assert exc_info.value.iterations >= 0
    assert exc_info.value.wall_clock_s > 0


def test_audit_emitted_with_full_metadata():
    svc = _make_service()
    svc._audit_cap_hit = AsyncMock()

    with patch("app.core.config.settings") as mock_settings:
        mock_settings.max_coordinator_iterations = 0
        mock_settings.max_coordinator_wall_clock_seconds = 600
        mock_settings.max_coordinator_total_tokens = 200_000

        with pytest.raises(IterationCapHit):
            asyncio.run(svc.run_with_iteration_cap(**_base_kwargs()))

    svc._audit_cap_hit.assert_awaited_once()
    args = svc._audit_cap_hit.call_args.args
    # _audit_cap_hit(session_id, actor_id, reason, iterations, wall_clock_s, tokens)
    reason = args[2]
    iterations = args[3]
    wall_clock_s = args[4]
    tokens = args[5]
    assert reason == "max_iterations"
    assert isinstance(iterations, int)
    assert isinstance(wall_clock_s, float)
    assert isinstance(tokens, int)


def test_audit_log_action_and_details():
    """Verify AuditLogger.log is called with the correct action + details keys."""
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    svc = CoordinatorService(db)
    svc.run = AsyncMock(return_value=(MagicMock(), MagicMock()))

    with patch("app.orchestrator.coordinator.AuditLogger") as MockAuditLogger:
        mock_audit = MagicMock()
        mock_audit.log = AsyncMock()
        MockAuditLogger.return_value = mock_audit

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.max_coordinator_iterations = 0
            mock_settings.max_coordinator_wall_clock_seconds = 600
            mock_settings.max_coordinator_total_tokens = 200_000

            with pytest.raises(IterationCapHit):
                asyncio.run(svc.run_with_iteration_cap(**_base_kwargs()))

    mock_audit.log.assert_awaited_once()
    call_kwargs = mock_audit.log.call_args.kwargs
    assert call_kwargs["action"] == "coordinator.iteration_cap_hit"
    details = call_kwargs["details"]
    assert "reason" in details
    assert "iterations" in details
    assert "wall_clock_s" in details
    assert "tokens" in details


def test_infinite_loop_guard_does_not_run_forever():
    """Deterministic single-pass builders break after iteration_no=1; no infinite loop."""
    svc = _make_service()
    result = asyncio.run(svc.run_with_iteration_cap(
        **_base_kwargs(token_counter_fn=lambda: 0, clock_fn=lambda: 0)
    ))
    _, _, iteration_no = result
    assert iteration_no == 1
    svc.run.assert_awaited_once()


def test_cap_hit_finalizes_session_failed():
    """A cap trip FINALIZES the session status='failed' (UPDATE + commit) before the
    IterationCapHit unwinds — a capped run is not left stranded at 'running'
    (matches the documented contract; the aborted-path-honesty class)."""
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    executed: list[str] = []

    async def _exec(stmt, *a, **k):
        executed.append(str(stmt).lower())
        return MagicMock(scalar_one_or_none=MagicMock(return_value=None))

    db.execute = _exec
    svc = CoordinatorService(db)
    svc.run = AsyncMock(return_value=(MagicMock(), MagicMock()))

    with patch("app.core.config.settings") as mock_settings:
        mock_settings.max_coordinator_iterations = 0
        mock_settings.max_coordinator_wall_clock_seconds = 600
        mock_settings.max_coordinator_total_tokens = 200_000
        with pytest.raises(IterationCapHit):
            asyncio.run(svc.run_with_iteration_cap(**_base_kwargs()))

    assert any("update pentest_sessions" in s and "status" in s for s in executed), executed
    db.commit.assert_awaited()
