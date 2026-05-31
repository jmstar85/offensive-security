"""Tests for contextvars-based credential context propagation across asyncio tasks."""
from __future__ import annotations

import asyncio
import uuid
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


def test_n20_gather_unique_uuids_no_leakage() -> None:
    """N=20 tasks each with a distinct UUID see only their own UUID via copy_context()."""
    N = 20
    user_ids = [uuid.uuid4() for _ in range(N)]

    async def _run() -> list[uuid.UUID | None]:
        seen: list[uuid.UUID | None] = [None] * N

        async def task(index: int, uid: uuid.UUID) -> None:
            seen[index] = CURRENT_USER_ID.get()  # type: ignore[assignment]

        tasks = []
        for i, uid in enumerate(user_ids):
            ctx = copy_context()
            ctx.run(CURRENT_USER_ID.set, uid)
            tasks.append(asyncio.get_event_loop().create_task(task(i, uid), context=ctx))

        await asyncio.gather(*tasks)
        return seen

    results = asyncio.run(_run())

    assert len(results) == N
    for i, (expected, actual) in enumerate(zip(user_ids, results)):
        assert actual == expected, (
            f"task {i}: expected {expected} but got {actual} — context leaked"
        )

    # All values must be distinct (no cross-task contamination)
    assert len(set(results)) == N, "Duplicate UUIDs across tasks — context leaked"
