"""ADR-001 Go/No-Go perf benchmark for EventBus topic filtering (v4.0 P3-spike).

This benchmark is the gate that flips ADR-001 status from `Proposed` to
`Accepted` or `Rejected`. It measures three quantitative metrics under a
synthetic load of **60 events/sec × 3 topics × 10 concurrent sessions**
(= 180 publish ops/sec total across 30 subscribers) for 1 second:

1. **p99 event-to-receive latency ≤ 100ms** — wall-clock from
   `event_bus.publish` call to the subscriber's `queue.get()` completion.
2. **QueueFull drop rate < 0.1%** — measured as (dropped subscribers /
   total publish ops). EventBus drops a subscriber's queue is full
   (v2.1 semantic, preserved in v4.0).
3. **No subscriber-list memory leak** — after all clients call `unsubscribe`,
   `EventBus._subscribers` returns to empty.

If all three thresholds pass, this test prints the measured numbers and
exits 0; the ADR doc at `.omc/research/adr-001-streaming-substrate.md` is
updated to `Accepted`. If any miss, the test fails and the ADR flips to
`Rejected` (fall back to GraphQL subscriptions per the v4.0 plan).

The test runs in <2s in CI; a longer soak test is left to operator
verification on real hardware.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from app.core.events import EventBus

# Load parameters from the ADR-001 spec.
NUM_SESSIONS = 10
TOPICS_PER_SESSION = ["terminal", "tasks", "agents"]
EVENTS_PER_SECOND_PER_TOPIC = 20  # × 3 topics = 60 events/sec/session
SOAK_DURATION_SECONDS = 1.0  # CI-friendly; the real spike PR may extend.

# Go/No-Go thresholds.
P99_LATENCY_MAX_MS = 100.0
QUEUEFULL_DROP_RATE_MAX = 0.001  # < 0.1%


@pytest.mark.asyncio
async def test_eventbus_topics_adr001_go_no_go():
    """Run the synthetic load + assert all 3 thresholds pass."""
    bus = EventBus()

    # Spin up one subscriber per (session, topic) pair.
    subscribers: list[tuple[str, str, asyncio.Queue]] = []
    for s in range(NUM_SESSIONS):
        sid = f"session-{s}"
        for topic in TOPICS_PER_SESSION:
            q = bus.subscribe(sid, topics={topic})
            subscribers.append((sid, topic, q))

    pre_subscriber_count = sum(
        bus._subscriber_count(f"session-{s}") for s in range(NUM_SESSIONS)
    )
    assert pre_subscriber_count == NUM_SESSIONS * len(TOPICS_PER_SESSION)

    latencies_ms: list[float] = []
    publish_total = 0
    publish_dropped = 0

    publisher_done = asyncio.Event()

    async def _consumer(sid: str, topic: str, q: asyncio.Queue) -> None:
        """Drain the queue; record latency from `publish_ts` field on each event."""
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=0.1)
            except asyncio.TimeoutError:
                if publisher_done.is_set() and q.empty():
                    return
                continue
            now_ns = time.perf_counter_ns()
            latency_ms = (now_ns - event["publish_ts"]) / 1_000_000
            latencies_ms.append(latency_ms)

    async def _publisher() -> None:
        """Publish 60 events/sec/session × NUM_SESSIONS for SOAK_DURATION_SECONDS."""
        nonlocal publish_total, publish_dropped
        end_time = time.monotonic() + SOAK_DURATION_SECONDS
        interval = 1.0 / EVENTS_PER_SECOND_PER_TOPIC  # 50ms per topic-event

        while time.monotonic() < end_time:
            for s in range(NUM_SESSIONS):
                sid = f"session-{s}"
                for topic in TOPICS_PER_SESSION:
                    pre_count = bus._subscriber_count(sid)
                    await bus.publish(
                        sid,
                        {"publish_ts": time.perf_counter_ns(), "topic": topic},
                        topic=topic,
                    )
                    post_count = bus._subscriber_count(sid)
                    publish_total += 1
                    if post_count < pre_count:
                        publish_dropped += pre_count - post_count
            await asyncio.sleep(interval)
        publisher_done.set()

    # Run publisher + consumers concurrently.
    consumer_tasks = [
        asyncio.create_task(_consumer(sid, topic, q)) for sid, topic, q in subscribers
    ]
    publisher_task = asyncio.create_task(_publisher())

    await publisher_task
    # Give consumers a brief grace window to drain remaining events.
    await asyncio.gather(*consumer_tasks, return_exceptions=True)

    # --- Metric 1: p99 latency ---
    assert latencies_ms, "No latencies recorded — publisher/consumer wiring broken"
    latencies_ms.sort()
    p99_idx = int(len(latencies_ms) * 0.99)
    p99_latency_ms = latencies_ms[p99_idx]

    # --- Metric 2: QueueFull drop rate ---
    drop_rate = publish_dropped / publish_total if publish_total else 0.0

    # --- Metric 3: subscriber leak ---
    for sid, _topic, q in subscribers:
        bus.unsubscribe(sid, q)
    leaked_subscribers = sum(
        bus._subscriber_count(f"session-{s}") for s in range(NUM_SESSIONS)
    )

    # Print measured numbers so the ADR can be updated from CI output.
    print(
        f"\nADR-001 measurements:"
        f"\n  p99 latency: {p99_latency_ms:.2f}ms (threshold {P99_LATENCY_MAX_MS}ms)"
        f"\n  drop rate: {drop_rate*100:.4f}% (threshold {QUEUEFULL_DROP_RATE_MAX*100}%)"
        f"\n  subscriber leak: {leaked_subscribers} (threshold 0)"
        f"\n  total publishes: {publish_total}"
        f"\n  total received: {len(latencies_ms)}"
    )

    # --- Gate ---
    assert (
        p99_latency_ms <= P99_LATENCY_MAX_MS
    ), f"ADR-001 latency threshold missed: {p99_latency_ms:.2f}ms > {P99_LATENCY_MAX_MS}ms"
    assert drop_rate < QUEUEFULL_DROP_RATE_MAX, (
        f"ADR-001 drop-rate threshold missed: "
        f"{drop_rate*100:.4f}% >= {QUEUEFULL_DROP_RATE_MAX*100}%"
    )
    assert leaked_subscribers == 0, (
        f"ADR-001 subscriber-leak threshold missed: "
        f"{leaked_subscribers} subscribers remain after unsubscribe"
    )
