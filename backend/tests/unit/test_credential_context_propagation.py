"""Tests for contextvars-based credential context propagation across asyncio tasks."""
from __future__ import annotations

import asyncio
from contextvars import copy_context

import pytest

from app.orchestrator.performer import CURRENT_USER_ID, _spawn_with_context


def test_context_propagates_through_gather() -> None:
    """CURRENT_USER_ID set before gather is visible in both child tasks."""

    async def _run() -> tuple[str | None, str | None]:
        CURRENT_USER_ID.set("user-abc")

        async def task_a() -> str | None:
            return CURRENT_USER_ID.get()

        async def task_b() -> str | None:
            return CURRENT_USER_ID.get()

        results = await asyncio.gather(
            _spawn_with_context(task_a()),
            _spawn_with_context(task_b()),
        )
        return results[0], results[1]

    result_a, result_b = asyncio.run(_run())
    assert result_a == "user-abc"
    assert result_b == "user-abc"


def test_context_isolated_between_users() -> None:
    """Two gather batches with different CURRENT_USER_ID values do not cross-contaminate."""

    async def _batch(user_id: str) -> list[str | None]:
        async def read_id() -> str | None:
            return CURRENT_USER_ID.get()

        CURRENT_USER_ID.set(user_id)
        return list(
            await asyncio.gather(
                _spawn_with_context(read_id()),
                _spawn_with_context(read_id()),
            )
        )

    async def _run() -> tuple[list[str | None], list[str | None]]:
        batch_alice: list[str | None] = []
        batch_bob: list[str | None] = []

        def run_alice() -> None:
            nonlocal batch_alice
            batch_alice = asyncio.get_event_loop().run_until_complete(_batch("alice"))

        def run_bob() -> None:
            nonlocal batch_bob
            batch_bob = asyncio.get_event_loop().run_until_complete(_batch("bob"))

        # Run each batch in its own copy_context so the ContextVar mutations
        # do not leak across the two batches.
        ctx_alice = copy_context()
        ctx_bob = copy_context()
        batch_alice = ctx_alice.run(asyncio.run, _batch("alice"))
        batch_bob = ctx_bob.run(asyncio.run, _batch("bob"))
        return batch_alice, batch_bob

    # Drive via copy_context().run so the two batches are fully isolated.
    results_alice: list[str | None] = []
    results_bob: list[str | None] = []

    ctx_a = copy_context()
    ctx_b = copy_context()
    results_alice = ctx_a.run(asyncio.run, _batch("alice"))
    results_bob = ctx_b.run(asyncio.run, _batch("bob"))

    assert all(v == "alice" for v in results_alice), f"alice batch leaked: {results_alice}"
    assert all(v == "bob" for v in results_bob), f"bob batch leaked: {results_bob}"
    assert results_alice != results_bob
