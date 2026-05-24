# ADR-001: Streaming Substrate — WebSocket evolved vs GraphQL subscriptions

- **Status: Accepted** (locked 2026-05-16 by P3-spike measured evidence)
- **Source plan:** [`.omc/plans/osa-pentagi-port-autopilot-v4.0.md`](../plans/osa-pentagi-port-autopilot-v4.0.md), ADR-001 §
- **Locked spec:** [`.omc/specs/deep-interview-osa-pentagi-port.md`](../specs/deep-interview-osa-pentagi-port.md) component 2

## Context

PentAGI uses GraphQL subscriptions over `graphql-ws` to multiplex per-panel
event streams (one subscription topic per UI panel). The v4.0 plan options
considered for OSA's port:

- **A. WebSocket evolved** — extend the existing `backend/app/core/events.py`
  `EventBus` with an optional `topic` kwarg and add a `topics` query param to
  `/ws/sessions/{session_id}`. Zero new dependencies.
- **B. GraphQL subscriptions** — adopt Strawberry + `graphql-ws` server-side
  and Apollo Client on the frontend. Adds ~500 LOC of schema work + 2 new
  backend deps + 1 new frontend dep. PentAGI's exact pattern.

Option A was proposed pending measured validation against the three Go/No-Go
thresholds below; if any missed, the plan falls back to Option B.

## Decision

**Adopt Option A (WebSocket evolved).** All three thresholds passed with
substantial headroom (see Measurements). No fall-back to Option B is needed
for v4.0; if a future scale point demands richer schema semantics (v3.4
multi-tenant + 6 right-pane tabs + browser screenshots), ADR-001a may
revisit.

## Decision Drivers

- **Codebase delta** — Option A is one `topic` kwarg in `events.py` + one
  query-param parser in `ws.py` + a 60-LOC frontend hook. Option B requires
  introducing a second-class API surface (GraphQL) alongside the REST/Pydantic
  contract, training operators on graphql-ws, and migrating the existing
  WebSocket flow.
- **Per-session queue model already supports multiplex** by filtering at
  delivery time — the existing `EventBus` design (one queue per subscriber,
  publisher-side fan-out) is a natural fit for topic-based filtering.
- **Backward compatibility** — the v2.1 Monitor page calls `event_bus.publish(session_id, event)` with no topic and `subscribe(session_id)` with no filter. Both default behaviors are preserved verbatim in the new API.

## Go/No-Go Thresholds (declared in v4.0 plan)

The P3-spike PR includes `backend/tests/perf/test_eventbus_topics.py` which
runs **60 events/sec × 3 topics × 10 concurrent sessions** (= 180 publish
ops/sec across 30 subscribers) for 1 second, then measures:

1. **p99 event-to-receive latency ≤ 100ms**
2. **`asyncio.QueueFull` drop rate < 0.1%**
3. **No subscriber-list memory leak** (count returns to 0 after disconnect)

ADR-001 locks to **Accepted** only if all three pass.

## Measurements (P3-spike, 2026-05-16)

Captured via `python -m pytest -q -s tests/perf/test_eventbus_topics.py` on
the developer venv (Python 3.13.12, macOS Darwin 25.4.0, M-series CPU):

```
ADR-001 measurements:
  p99 latency: 0.77ms (threshold 100.0ms)
  drop rate: 0.0000% (threshold 0.1%)
  subscriber leak: 0 (threshold 0)
  total publishes: 600
  total received: 600
```

| Threshold | Target | Measured | Margin |
|-----------|--------|----------|--------|
| p99 latency | ≤ 100ms | 0.77ms | ~130× headroom |
| Drop rate | < 0.1% | 0% | perfect delivery |
| Subscriber leak | = 0 | 0 | clean |

100% of 600 published events were received by their topic-filtered
subscribers. **All three thresholds pass with large margins; the in-memory
asyncio queue substrate is comfortably within budget for v4.0 load
projections.**

## Alternatives Considered

### Option B — GraphQL subscriptions (rejected for v4.0)

Adopting Strawberry + `graphql-ws` would have given typed subscription
schemas and built-in multiplex. The trade-offs that made it lose:

- Adds backend deps (`strawberry-graphql`, `graphql-core`) and a frontend
  dep (`@apollo/client` or `urql`), each with their own version policy.
- Introduces a second-class API surface alongside the REST/Pydantic contract;
  operators would have to learn two schemas.
- The multiplex benefit only matters if the per-session queue model can't
  scale, which Option A's measurements disprove.

If v3.4 demands multi-tenant + 6 right-pane tabs + browser screenshots, the
substrate decision should be revisited — but that is post-v4.0 work and gets
its own ADR.

### Option C — Server-Sent Events (not considered)

Not considered because SSE is unidirectional and the existing v2.1
`/ws/sessions/{id}` already does bidirectional WebSocket. A switch to SSE
would break operator chat ack flow.

## Consequences

**Positive:**

- Zero new backend dependencies.
- One new tiny frontend hook (`useTopicWebSocket.ts`, ≤60 LOC) that coexists
  with the legacy `useWebSocket` until P5 deletes the old one.
- 1:1 topic → UI panel mapping enumerated in
  [`.omc/research/pentagi-reference.md §4`](pentagi-reference.md).
- Tests added: `test_event_bus_topic_filter.py` (7 unit), `test_ws_topic_subscription.py` (7 unit-style integration), `test_eventbus_topics.py` (1 perf gate). Cumulative test count: P1 92 → P3-spike 95 (3 new test files; 15 new test cases).

**Negative:**

- The per-session queue model carries a fixed `maxsize=500` queue. If a
  subscriber falls behind by more than 500 events, we still drop the
  subscriber (v2.1 semantics). For v4.0 expected event rates (a handful per
  second per session, with bursts during exploit phases), 500 is plenty.
  ADR-001a may parameterize `maxsize` per topic if v3.4 surfaces hot streams.
- No typed schema on the wire. Frontend consumers JSON.parse manually. If
  schema drift becomes painful, ADR-001b can layer a typed validator without
  swapping substrate.

## Follow-up Items

- **`backend/tests/perf/test_eventbus_topics.py` runs in CI by default** so
  any P2a / P3-main / P4 regression that pushes p99 latency over 10ms (10×
  headroom from current) trips the gate. Future plan revisions may tighten
  the assertion further if measurements remain stable.
- **`useTopicWebSocket.ts` lands behind `osa_flow_ui_enabled` only** — no UI
  consumes it yet in P3-spike. P3-main mounts it in the 3 right-pane tabs
  (Terminal, Tasks, Agents).
- **The P2a `test_p2a_no_topic_prefix.py` invariant** can be removed once
  P3-spike merges and ADR-001 is Accepted (this happened now). The plan v4.0
  Dependencies & Ordering block already notes the cleanup.

## Spike PR scope (delivered)

Implemented in this commit:

- `backend/app/core/events.py` — added `topic` kwarg to `publish`; added
  `topics` filter to `subscribe`; new `_Subscriber` record; cleaned up
  empty-session-bucket leak path; added `_subscriber_count` test helper.
- `backend/app/api/v1/ws.py` — added `_parse_topics` query-param parser;
  passes the parsed filter into `event_bus.subscribe`.
- `frontend/src/hooks/useTopicWebSocket.ts` — new typed hook (≤60 LOC).
- `backend/tests/unit/test_event_bus_topic_filter.py` — 7 unit tests.
- `backend/tests/integration/test_ws_topic_subscription.py` — 7 parse tests.
- `backend/tests/perf/test_eventbus_topics.py` — Go/No-Go gate (this ADR's evidence).
- `.omc/research/adr-001-streaming-substrate.md` — this file.

**Verification:** `pytest -q backend/tests/` → 270 passed, 19 warnings,
2.07s. Includes 255 P0+P1 baseline + 15 P3-spike new tests.
