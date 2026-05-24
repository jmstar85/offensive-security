"""Reflector wrap retry policy tests (v4.0 P2a).

Reflector wraps every other role's `run()` with try/except + exponential
backoff retries (default: 3 retries × [0.2, 1.0, 5.0]s). On persistent
failure, it surfaces the error as a RoleResult with `error` set rather than
re-raising.
"""
from __future__ import annotations

import pytest

from app.orchestrator.roles.base import RoleResult
from app.orchestrator.roles.reflector import wrap


@pytest.mark.asyncio
async def test_wrap_returns_first_success():
    """No retry needed — callable returns successfully on first attempt."""
    calls = 0

    async def _ok():
        nonlocal calls
        calls += 1
        return RoleResult(role_name="ok", finished=True)

    result = await wrap(_ok)
    assert result.role_name == "ok"
    assert calls == 1


@pytest.mark.asyncio
async def test_wrap_retries_on_transient_error_then_succeeds():
    """Reflector retries up to 3 times; succeeds on the 3rd attempt."""
    calls = 0

    async def _flaky():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError(f"transient {calls}")
        return RoleResult(role_name="flaky", finished=True)

    # Override backoff to 0 for fast test execution.
    result = await wrap(_flaky, backoff=[0, 0, 0])
    assert result.role_name == "flaky"
    assert calls == 3


@pytest.mark.asyncio
async def test_wrap_surfaces_persistent_failure_as_error_result():
    """After exhausting retries, Reflector returns a RoleResult with
    `error` set instead of re-raising."""
    calls = 0

    async def _persistent_fail():
        nonlocal calls
        calls += 1
        raise RuntimeError(f"persistent failure {calls}")

    result = await wrap(_persistent_fail, max_retries=2, backoff=[0, 0])
    assert result.role_name == "reflector"
    assert result.error is not None
    assert "persistent failure" in result.error
    assert calls == 3  # 1 attempt + 2 retries


@pytest.mark.asyncio
async def test_wrap_preserves_args_and_kwargs():
    """Reflector forwards positional + keyword args to the wrapped callable."""
    captured = {}

    async def _capture(a, b, *, c):
        captured.update(a=a, b=b, c=c)
        return RoleResult(role_name="capture", finished=True)

    await wrap(_capture, 1, 2, c=3)
    assert captured == {"a": 1, "b": 2, "c": 3}
