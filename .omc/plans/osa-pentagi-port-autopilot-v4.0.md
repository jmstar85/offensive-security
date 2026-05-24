# OSA Platform — Autopilot Implementation Plan v4.0 (PentAGI Port)

## Metadata

- **Source spec:** `.omc/specs/deep-interview-osa-pentagi-port.md` (ambiguity 17.2%, all 6 components locked)
- **Supersedes:** `.omc/plans/offensive-security-agent-consensus-v3.2.1.md` in amended sections only; v3.2.1 unchanged sections remain in force unchanged.
- **Composition rule:** v4.0 ⟶ amends ⟶ v3.2.1 ⟶ amends ⟶ v3.x ⟶ extends ⟶ v2.1 (executing baseline, 85 tests passing).
- **Generated:** 2026-05-16 by autopilot Phase 1 (architect role); revised 2026-05-16 (revision v2 + v2.1) addressing two Critic must-fix passes.
- **Status:** `pending_critic_review_v2.1`
- **Scope of amendment:** Components 1–6 from the deep-interview spec (PentAGI Analysis Reference, UI Shell + Per-Panel Streaming, Agent Architecture Reshape, Ambiguity-Gated Planning Workflow, Memory/RAG, Migration & Rollout). All other v3.2.1 sections (Domain Agents, ApprovalGate, AES-GCM credentials, single uvicorn worker, model selector, budget guard, rescope state machine, knowledge loader, audit logging, safety 5 layers) remain authoritative.
- **PR count target:** 8 PRs total (P0 = 1 docs, P1 = 1, P3-spike = 1, P2 = 2, P3-main = 1, P4 = 1, P5 = 1 — scheduled 2 releases later).
- **Test baseline obligation:** 85 existing tests must pass unchanged after every PR. New phase tests are additive only. Cumulative target after v4.0 complete: **120 tests passing** (85 + 35 net new). Single source of truth — Dependencies & Ordering block enumerates per-phase deltas.

## Revision Log

- **2026-05-16 v2 (this revision):** Addressed Critic Phase 1 review (4 must-fix + 6 should-fix).
  - **MF-1:** Added explicit P0 (PentAGI Analysis Reference) phase before P1; reconciled PR count 6→8 (P0 + 7 code PRs).
  - **MF-2:** Moved P3-spike to sit between P1 and P2a in Dependencies & Ordering (substrate locks before Performer commits topic taxonomy).
  - **MF-3:** Locked exact dep tuple in P1 (pgvector 0.3.6, sentence-transformers 3.3.1, torch 2.4.1+cpu, numpy 1.26.4); added P1 acceptance gate for resolver-clean install + import smoke.
  - **MF-4:** ADR-001 restructured with quantitative Go/No-Go threshold (p99 ≤ 100ms @ 60 events/sec × 3 topics × 10 sessions; QueueFull rate < 0.1%; subscriber-leak invariant); status changed to "Proposed; locks on P3-spike measurement".
  - **SF-1:** P5 page-deletion tests expanded from 1 sweep to 4 per-page tests (+3 net).
  - **SF-2:** Added P1 `test_msgchain_no_subtask_overlap.py` enforcing field disjointness between `draft_plan_json` and `MsgChain.messages_json`.
  - **SF-3:** Added `max_concurrent_performer_sessions: int = 4` to P1 config additions (operationalizes ADR-003).
  - **SF-4:** P5 14-day soak window now has explicit rollback criterion (abort if `osa_session_error_rate` > 2× baseline for any 24h window).
  - **SF-5:** Added P2b `tests/integration/test_pipeline_shape.py` regression test asserting `AttackPlanner(use_generator_role=False)` step-content equivalence.
  - **SF-6:** Open Issue #8 (INTENT_VOCABULARY) marked RESOLVED — confirmed in source at `backend/app/agents/intent_vocabulary.py` with 25 specs.
- **2026-05-16 v2.1 (incremental — Critic round 2 follow-up):** Critic round 2 confirmed all 10 v2 items resolved but flagged 2 new arithmetic must-fix + 2 minor. v2.1 addresses these:
  - **CRITICAL-1 fix:** updated stale per-phase Acceptance Gate test counts in P2a (97 → 103), P2b (98 → 105), P3-spike (100 → 95 actual = 95), P3-main (105 → 110), P4 (111 → 116), P5 (added 116 → 120 final). Per-phase numbers now match Dependencies & Ordering ladder end-to-end.
  - **CRITICAL-2 fix:** single source of truth for cumulative total = **120 tests**. Metadata, P1 footnote, Dependencies block, and Final acceptance section now all read 120 / 35 net new (was 117/119/120 contradiction).
  - **MINOR-1 fix:** P0 parallelism caveat reworded to clarify P0 must merge before P1 (was softly contradicting hard ordering).
  - **MINOR-2 fix:** P5 soak rollback metric canonicalized to single name `osa_session_error_rate_ratio` (was conflating `osa_session_error_rate` and `osa_http_error_rate_ratio`); ownership of metric instrumentation assigned to P3-main + alerting to P4.

---

## §1 PentAGI Analysis (Summary)

This section is the in-plan summary of the port-reference work (Component-1 of the deep-interview spec). The detailed matrix lives at [`.omc/research/pentagi-reference.md`](../research/pentagi-reference.md) and is the authoritative 1:1 lookup for implementers; this summary is for reviewers who need the decision shape without the full table.

### §1.1 Patterns adopted (5)

OSA v4.0 imports five high-leverage PentAGI patterns. Each is justified by either a specific spec ask (deep-interview component) or a code-economic argument (lowest-delta path to feature parity):

1. **2-pane resizable shell + multi-tab evidence panel** (PentAGI `frontend/src/pages/flows/flow.tsx`). The single most visible UX change. The left pane carries "what the operator says/sees as conversation+overview" (Automation / Assistant / Dashboard), the right pane carries "what the agents are doing as raw evidence" (Terminal / Tasks / Agents). The shell is mounted on a new route `/flow/:id` (P3-main) gated by `settings.osa_flow_ui_enabled`. OSA ships 3 right-pane tabs in v1; the other 3 (Searches / Vector Store / Screenshots) defer to v3.4 because their backing data sources (web search tools / vector inspection UI / browser screenshots) require additional roles and tools that are out of scope.

2. **Role-based Performer engine** (PentAGI `backend/pkg/providers/performer.go`). Replaces the linear `AttackPlanner → OrchestratorService → PlanExecutor` pipeline with a single generic `Performer` that runs typed message chains parameterized by role. Each role is differentiated by its system prompt, tool palette, and iteration caps — not by class hierarchy. OSA ships **6 roles** in v1 (Generator, Pentester, Memorist, Adviser, Reflector, Reporter); the remaining 8 PentAGI roles are deferred to v3.4 per the Round 6 Simplifier decision. The choice of 6 covers the entire spec's locked workflow (plan, execute, RAG, loop-break, error-recover, report) with zero redundant roles.

3. **Agent-as-tool delegation** (PentAGI `backend/pkg/tools/registry.go`). Roles call other roles by emitting LLM function calls; persistent state lives in the `msgchains` table (one row per role-chain per session, `MsgchainType` enum). This is the mechanism that makes the role layer composable without an in-memory message bus. OSA adopts this exactly — Pentester emits structured tool calls per ADR-005 (`{name, input: {intent, config}}`), Performer's `_dispatch_tool` resolves through `get_adapter()` and runs the safety chain. The existing 11 `AgentAdapter`s in `backend/app/agents/` are unchanged; the role layer sits above them.

4. **pgvector + Memorist RAG** (PentAGI `backend/migrations/sql/*memory*` + `tools/search_in_memory`). One-table vector store backed by Postgres + pgvector extension. OSA adopts a Thin v1: only `search_in_memory` ships (the other 3 PentAGI memory tools — `search_guide` / `search_answer` / `search_code` — are v3.4), embedding is local `sentence-transformers/all-MiniLM-L6-v2` (384-dim, no external API dependency added), seed data is the existing `backend/app/knowledge/*.yaml` corpus chunked by description, and the Memorist role auto-calls `search_in_memory` at the start of every SubTask (Pentester pre-hook) with `k=3` and `score_threshold=0.7`. The Graphiti+Neo4j optional stack is rejected for v1.

5. **Topic-per-panel streaming** (PentAGI `backend/pkg/graph/schema.graphqls` subscriptions). Each UI panel subscribes to exactly one stream topic (1:1 publisher→topic→panel). OSA implements this via WebSocket-evolved per ADR-001 — the existing `EventBus.publish(session_id, event)` gains an optional `topic` kwarg, and the new `/ws/sessions/{id}?topics=…` route filters by topic. GraphQL subscriptions are the documented fall-back path **only** if P3-spike's three quantitative thresholds (p99 ≤100ms, QueueFull <0.1%, no subscriber leak) miss; that fall-back path is a ~3-PR extension to P3 documented in `.omc/research/adr-001-fallback-graphql.md` if it ever lands.

### §1.2 Patterns explicitly rejected (7)

OSA v4.0 rejects seven PentAGI patterns. Each rejection has a single-sentence rationale:

1. **Raw `terminal` shell tool** — would bypass OSA's tier-gated AgentAdapter registry and require a separate safety re-validation ADR; deferred to v3.4 when Coder/Installer roles need it.
2. **3 right-pane tabs** (Searches / Vector Store / Screenshots) — no backing data source in v1; would ship as empty placeholders, which is worse UX than not shipping at all.
3. **8 of 14 PentAGI roles** (PrimaryAgent, Assistant, Refiner, Planner, Enricher, Coder, Installer, Searcher; Mentor folded into Adviser) — Round 6 Simplifier decision; each deferred role requires either a new tool category or a new sub-engine that doesn't pay rent in v1.
4. **GraphQL substrate as default** — adds 500+ LOC and 2 new backend deps (Strawberry + graphql-ws) for a multiplex feature that the existing WebSocket already supports via topic filter. ADR-001 keeps GraphQL as a measured fall-back only.
5. **Multi-LLM provider routing** (PentAGI supports Anthropic / OpenAI / Gemini / Bedrock / Ollama / DeepSeek / GLM / Kimi / Qwen + custom) — locked Anthropic-only at v3.2.1; out of scope.
6. **Graphiti + Neo4j optional stack** — PentAGI's graph search tool is post-v1 polish, not core feature.
7. **Per-flow Docker container model** — incompatible with OSA's per-tool tier gating; OSA's existing `DockerBackend` spawns one container per `AgentExecution` row, which is the unit of safety enforcement.

### §1.3 Substantive gaps (3)

Three places where PentAGI and OSA disagree on substantive semantics, and how v4.0 bridges them:

1. **Safety model gap.** PentAGI relies on sandbox + iteration caps + `ASK_USER` opt-in for human-in-the-loop. OSA layers six explicit brakes on top: per-target whitelist (`whitelist.py`), tier gating (`registry.py`'s `Tier`), exploit allowlist (`exploit_allowlist.py`'s MSF prefix + Nuclei tag filter), runtime egress monitor (`egress_monitor.py`), kill switch (`kill_switch.py`), audit log (`audit.py` + `audit_logs` table). The v4.0 bridge: adopt PentAGI's brakes *additively* (Reflector wrap, Adviser injection, iteration caps, retry counts, tool quotas — all land in P2a/P3-spike), but never remove an OSA brake. The Pentester role's structured-tool-call envelope (ADR-005) is the mechanism that preserves every OSA brake while letting role-level autonomy live above them. Future v3.4 roles that need raw shell (Coder, Installer) will require a separate safety re-validation ADR before they ship.

2. **Task decomposition gap.** PentAGI uses a flat SubTask list (`Flow → Task → SubTask → Action → Artifact/Memory`, single-level). OSA stores plan steps in `pentest_sessions.plan_json` as a list that is *topologically sortable* (`workflow_plan.normalize()` produces a DAG). The v4.0 bridge: Generator emits a SubTask list into `draft_plan_json`; topological order is applied via `workflow_plan.normalize()` at approval time; runtime delegation follows topological order (PrimaryAgent's role is folded into the Performer event loop in v1, so the Performer iterates the sorted SubTask list and dispatches to Pentester per node). This preserves OSA's DAG capability while matching PentAGI's developer model.

3. **Sandbox-granularity gap.** PentAGI spawns one Docker container per flow; the LLM emits shell commands into that container via the `terminal` tool. OSA spawns one container per `AgentExecution` row (per-tool, not per-flow). Collapsing to per-flow would require classifying every shell command into a tier *after the fact* (regex over the command string), which is fragile. The v4.0 bridge: Pentester emits structured tool calls; Performer's `_dispatch_tool` calls `AgentAdapter.execute()`, which spawns its own container per the existing `DockerBackend` contract; results stream back via `event_bus.publish(session_id, result, topic="…")`. The per-flow container model is rejected without prejudice — if a v3.4 use case requires it, ADR-006 will reopen the question.

### §1.4 What changes for users + what does not

**Changes** (visible after `osa_flow_ui_enabled=true`):
- New `/flow/:id` route renders the 2-pane shell with 6 tabs.
- Workflow chat is mounted in the left-pane Automation tab; xterm.js terminal in the right-pane Terminal tab; SubTask tree in Tasks; per-role message chains in Agents.
- Pentest session prompt → Generator produces SubTasks + ambiguity score; ambiguity > 0.35 triggers `ask` tool, surfaced inline in WorkflowChat; ambiguity ≤ 0.35 triggers one-time approval gate; execution runs without further per-step approval.
- Memorist auto-pulls k=3 knowledge chunks per SubTask; relevant entries surface in the Agents tab.
- Adviser/Reflector trigger inline if Pentester loops or errors.

**Does not change** (the v3.2.1 invariants):
- Safety chain order: whitelist → filter_plan_steps → exploit_allowlist → egress_monitor → kill_switch → audit.
- 11 AgentAdapter slugs + tier classification.
- 8 Domain agents in `backend/app/agents/domains/`.
- ApprovalGate for Azure priv-esc.
- AES-GCM credential encryption at rest.
- Single uvicorn worker constraint.
- claude-sonnet-4-6 as default model (claude-opus-4-6 admin-only).
- Daily $5 budget default per user; team-pool aggregation.
- Rescope state machine.
- All sidebar routes (WorkflowBuilder DAG editor, Workflows, Reports, Admin, Login, Projects, ProjectDetail, Dashboard).
- 85 v2.1 tests; all must pass at every PR gate.

### §1.5 Acceptance of this analysis

A reviewer reading this §1 + skimming the reference doc should be able to answer:
1. **Which PentAGI patterns are adopted?** → 5 (shell, role-Performer, agent-as-tool, pgvector RAG, topic streaming).
2. **What is explicitly rejected?** → 7 (raw shell, 3 tabs, 8 roles, GraphQL default, multi-LLM, Graphiti, per-flow container).
3. **Where do PentAGI and OSA disagree on semantics, and how does v4.0 bridge each gap?** → 3 (safety, decomposition, sandbox-granularity).

A P1 implementer opening `.omc/research/pentagi-reference.md` should be able to find the OSA target path for any PentAGI source file in §1.1 of that file (Implementer Lookup Index, last section).

If reviewer + implementer can both pass these checks, Component-1 of the deep-interview spec is satisfied and P0 ships green.

---

## RALPLAN-DR (Principles, Decision Drivers, Options)

### Principles

1. **Safety-chain invariance (inherited from v3.2.1 Principle 1).** `WhitelistValidator → filter_plan_steps → RiskFilter.filter_steps → EgressMonitor → KillSwitch` is invariant. The Performer engine and the 6 new roles do **not** open any execution path that bypasses these layers; Pentester invokes existing `AgentAdapter`s via a structured tool-call contract, never raw shell, never bypassing `get_adapter()` and the tier-gated registry in `backend/app/agents/registry.py`.
2. **Brownfield amendment, never replacement.** Every v4.0 file addition is additive to v2.1; every v4.0 file modification preserves the v2.1 public surface (`AttackPlanner.create_plan`, `OrchestratorService.run`, `PlanExecutor.execute`, `WorkflowService.send_message`, `get_adapter`/`list_agent_types`, `pentest_sessions` REST shape). Adaptation happens behind a shim/feature flag, never by deleting v2.1 entry points in-flight.
3. **Feature-flag isolation of UI surface area.** All new UI (`/flow/:id`, 2-pane shell, 3-tab right pane, 3-tab left pane) is gated by `settings.osa_flow_ui_enabled` (global scope per ADR-004). Flag-off path must render the existing 12 pages identically to v2.1 with zero regressions; flag-on path renders the new shell while leaving sidebar routes for `WorkflowBuilder`, `Workflows`, `Reports`, `Admin` intact.
4. **One-stream-per-panel.** Each right-pane tab subscribes to exactly one stream topic on the chosen streaming substrate (`terminal_log`, `task_event`, `agent_chain`). No tab multiplexes more than one logical stream. ADR-001 picks the substrate; the 1:1 topic rule survives the choice.
5. **No new vendor surface.** Anthropic remains the only LLM provider. Embeddings ship as a local model (`sentence-transformers/all-MiniLM-L6-v2`, 384-dim, CPU). No OpenAI, Voyage, Cohere, or Bedrock embedding/LLM calls are introduced. The container size cost (~500MB) is the explicit trade-off and is acceptable; an ADR-007 follow-up (post-v4.0) may compress this if it ships in v3.4.
6. **Locked spec is non-negotiable.** v4.0 does not relitigate the 6-role choice, the Thin v1 RAG scope, the OSA-strong hybrid agent model, the 5-phase migration, the 0.35 ambiguity threshold, or the v3.4 deferral list. Any pressure to change these in critic review is converted into an open issue, not a plan amendment.

### Decision Drivers

1. **Regression cost dominates feature velocity.** The 85-test baseline (24 test files spanning `backend/tests/unit`, `backend/tests/integration`, `backend/tests/e2e`) is the canary for safety-chain regressions; any phase that breaks even one of those tests is reverted, not patched-forward. This drives the small-PR, feature-flagged sequencing.
2. **Streaming-substrate choice is the only Phase-blocking unknown.** Constraint clarity 0.70 in the spec maps entirely to ADR-001 (WebSocket-evolved vs GraphQL subscriptions). The plan resolves this with a P3-spike PR (ADR + minimal proof) **before** the P3-main PR ships the new UI; this contains substrate risk to one PR.
3. **PentAGI ↔ OSA semantic gap on raw shell.** PentAGI's Performer assumes a single terminal tool. OSA's safety model forbids that. The plan resolves the gap by making the Pentester role's tool surface = `palette_for_domain()` from `registry.py`, i.e. structured tool calls only. Coder/Installer/Searcher roles (v3.4) will need a separate ADR before they can land.

### Options Considered (cross-cutting decisions only)

| Decision | A | B | C | Selected | Why |
|----------|---|---|---|----------|-----|
| Streaming substrate (ADR-001) | WebSocket evolved (current `event_bus` extended with topic filter) | GraphQL subscriptions via Strawberry + graphql-ws | — | A pending P3 spike; B retained as fallback | Lowest delta to v2.1 codebase; existing `backend/app/api/v1/ws.py` already publishes `session_update`; multiplexing via `topics` query param costs ~80 LOC. B is a 500+ LOC dependency expansion. Spike confirms within one PR. |
| pgvector index (ADR-002) | hnsw m=16 ef_construction=64 | ivfflat lists=100 | flat (no index) | A | Spec locks hnsw; ~5,000 knowledge chunks fit comfortably, hnsw recall ≥ 0.95 @ k=3 with low build time; ivfflat requires post-load training, flat is O(n) on every search. |
| Performer concurrency (ADR-003) | asyncio.Task per Role per Session | Single coroutine loop with cooperative scheduling | Process pool | B | Single uvicorn worker constraint (v3.2.1 §R) forbids process pool; per-Role tasks risk fan-out cost on the single event loop. Cooperative single-coro loop with explicit `await` between Role.run() invocations gives deterministic ordering for the Reflector wrap. |
| Feature-flag scope (ADR-004) | global `settings.osa_flow_ui_enabled` | per-team via `teams.flow_ui_enabled` | per-user via `users.flow_ui_enabled` | A | v3.2.1 teams table exists but per-team rollout requires a new endpoint + admin UI not in scope. Global flag is one env var to flip; admin can override per-environment. Per-team is an open issue for v3.4 if early-adopter cohorts emerge. |
| AgentAdapter contract (ADR-005) | Pentester emits `{agent, action, config}` tool-call JSON → `Performer._dispatch_tool` resolves via `get_adapter()` | Pentester wraps adapters in a new `RoleAdapter` interface | Pentester re-implements adapter logic inside the role | A | Preserves `AgentAdapter`/`ExecutionBackend` contract in `backend/app/agents/base.py:34-122`; zero changes to 11 existing adapters; tier-gating, registry palette, and intent vocabulary all remain authoritative. |

---

## ADRs

### ADR-001: Streaming substrate (WebSocket evolved vs GraphQL subscriptions)

- **Status:** **Proposed; locks on P3-spike measurement.** Accepted only when the Go/No-Go thresholds below are all met by the P3-spike benchmark; otherwise the plan falls back to Option B (GraphQL subscriptions) and P3-main scope expands by ~3 PRs.
- **Decision driver:** the spec leaves this open; component 2 clarity 0.70 is bottlenecked here.
- **Decision (proposed):** WebSocket-evolved (Option A) selected pending spike validation. The existing `backend/app/core/events.py` `EventBus` + `backend/app/api/v1/ws.py` route is extended to accept a `topics` query param (`/ws/sessions/{session_id}?topics=terminal,tasks,agents`). Each panel subscribes to one topic. `event_bus.publish(session_id, event)` gains an optional `topic` kwarg; existing publishes default to `topic="session"` to preserve the v2.1 Monitor page.

#### Go/No-Go Threshold (P3-spike measured)

The P3-spike PR includes a benchmark script `backend/tests/perf/test_eventbus_topics.py` that prints three measured numbers under a synthetic load of **60 events/sec across 3 topics × 10 concurrent sessions** (180 publish ops/sec total, 30 subscribers):

1. **p99 event-to-client latency ≤ 100ms** — measured wall-clock from `event_bus.publish` call to client-side `onmessage` handler invocation across all 30 subscribers.
2. **`asyncio.QueueFull` drop rate < 0.1%** — measured as (dropped events / published events) over a 60-second run.
3. **No subscriber-list memory leak** — `len(event_bus._subscribers[session_id])` returns to its pre-test value within 1 second of all clients disconnecting (gc-deterministic; no zombie entries).

**Decision lock criterion:** if all 3 thresholds pass, ADR-001 status flips to **Accepted** in the same spike PR commit. If any threshold misses, status flips to **Rejected (Option A)** and the plan documents the GraphQL fallback path in `.omc/research/adr-001-fallback-graphql.md` before P3-main can start.

- **Alternatives rejected:** GraphQL subscriptions via Strawberry + `graphql-ws` — adds two backend deps, a new schema language to maintain alongside FastAPI Pydantic models, and requires Apollo Client on the frontend (or `urql`). Wins: typed schema, automatic multiplex. Loses on dep weight and divergence from REST contract.
- **Why A:** preserves the 1:1 publisher → topic mapping with zero new dependencies; the per-session queue model already supports multiplex by filtering at delivery time; existing tests at `backend/tests/integration/test_pipeline.py` continue to receive `session_update` on `topic="session"`.
- **Consequences:** Frontend writes a small `useTopicWebSocket(sessionId, topic)` hook (≤ 60 LOC) replacing the monolithic `useWebSocket`. Tests added: `test_event_bus_topic_filter.py` (unit), `test_ws_topic_subscription.py` (integration), `test_eventbus_topics.py` (perf, ADR gate). Risk: drop-event semantics on `asyncio.QueueFull` carry over from v2.1; topic-filtered queues should size proportionally (we keep `maxsize=500`).
- **Spike PR scope:** add `topic` kwarg to `EventBus.publish`, add `topics` query param to `/ws/sessions/{session_id}`, ship the new hook behind `osa_flow_ui_enabled=false` (no UI yet), run the perf benchmark, publish ADR-001 artifact under `.omc/research/adr-001-streaming-substrate.md` with measured numbers and Accepted/Rejected verdict.
- **Follow-up:** if GraphQL substrate ever needs to land (v3.4 multi-tenant), the topic→subscription mapping is 1:1 by design; migration cost is a frontend dep swap, not a backend redesign.

#### Pre-ADR-lock invariant (P2a)

Until ADR-001 flips to Accepted (i.e., until P3-spike completes), **P2a must NOT publish to per-panel topics.** Performer's `_dispatch_tool` and Pentester emit `event_bus.publish(session_id, event)` with no `topic` kwarg → defaults to `topic="session"`. A negative-assertion gate test ships in P2a (`test_p2a_no_topic_prefix.py`) that greps the diff for any literal `topic="terminal"`, `topic="tasks"`, or `topic="agents"` reference and fails the PR if found. This eliminates the rework risk if P3-spike rejects WebSocket-evolved.

### ADR-002: pgvector indexing strategy (hnsw vs ivfflat)

- **Status:** Locked.
- **Decision:** `CREATE INDEX memory_entries_embedding_hnsw_idx ON memory_entries USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64);` ANN search query: `SELECT id, name, description, 1-(embedding <=> $1) AS score FROM memory_entries ORDER BY embedding <=> $1 LIMIT 3` with `score_threshold=0.7` applied client-side (Memorist role discards rows below threshold).
- **Decision drivers:** spec locks hnsw; expected corpus ~5,000–10,000 chunks (9 SKILL.md + dorks YAML + future cards); hnsw build time is ≤ 30s for that size; recall ≥ 0.95 at default params on 384-dim cosine.
- **Alternatives rejected:** `ivfflat lists=100` — needs training step over loaded data, less recall on small corpus, more configuration; flat scan — fine for 5k rows on `description IS NOT NULL` but doesn't future-proof when knowledge cards expand.
- **Why hnsw default params:** `m=16` is pgvector's default; `ef_construction=64` halves the default 200 to favor fast boot time at the cost of slightly lower recall (acceptable for k=3 use case). Runtime `SET hnsw.ef_search = 40` (≥ k) inside the Memorist session-scope to balance recall and latency.
- **Consequences:** P1 migration adds the index post-insert (`memory_entries` is empty until P4 seed-load); seed-load (separately runnable command, `python -m app.knowledge.seed_memory`) populates after migration; tests include `test_memorist_search.py` measuring recall on fixture chunks.
- **Follow-up:** if k bumps to 10 or corpus exceeds 100k, ADR-002a should revisit `m` and `ef_construction`.

### ADR-003: Performer engine concurrency model

- **Status:** Locked.
- **Decision:** Single coroutine per active `PentestSession` running a cooperative role loop. Performer maintains a per-session `current_role` and yields back to the event loop between role invocations. No `asyncio.Task` per Role. The Reflector wrap is implemented as `try/except` around `await role.run(...)` with retries-counter persisted to `MsgChain.retries`.
- **Decision drivers:** v3.2.1 §R single uvicorn worker; deterministic ordering required for replayable audit trails; rate-limit budget (5 prompts/min/session, see `backend/app/orchestrator/service.py:31-43`) is naturally enforced by single coroutine.
- **Alternatives rejected:** asyncio.Task per Role per Session — fan-out under concurrent sessions saturates the single worker; ordering becomes nondeterministic which breaks deterministic test replay; Adviser auto-injection (tool-call counters) requires cross-role state synchronization, which is simpler in a single coroutine.
- **Why B over A:** the safety-chain re-validation between every tool call (whitelist, tier, allowlist) is sequential by contract; parallelism would only matter inside a `Memorist.search_in_memory` call (pgvector is sub-100ms), which doesn't justify the coordination cost.
- **Consequences:** Adviser/Reflector triggers are bookkeeping inside the Performer loop; per-role token counters live on `MsgChain.messages_json[-1].usage`. Max-iter cap (`PERFORMER_MAX_ITER = 64`) lives on `app/orchestrator/performer.py`; exceeds → session transitions to `needs_human_review`.
- **Follow-up:** Phase 3.4 (when Coder/Installer roles need long-running shell subprocesses) will reopen ADR-003 with backpressure semantics.

### ADR-004: Feature flag scope (`OSA_FLOW_UI`)

- **Status:** Locked.
- **Decision:** Global flag via `settings.osa_flow_ui_enabled: bool = False` in `backend/app/core/config.py`. Frontend reads it from a new `GET /api/v1/config/feature-flags` endpoint (or inlines it via a `<meta>` tag injected by FastAPI in `main.py`). Default OFF in v4.0 P3; switched ON per environment after smoke tests.
- **Decision drivers:** Need a one-knob rollback that survives an angry production page; no team-by-team rollout requirement in v4.0; teams table exists but not exercised for routing decisions yet.
- **Alternatives rejected:** per-team — requires Admin UI + DB columns + backend dispatch; per-user — same plus session token plumbing; both reopen P3 scope.
- **Why A:** atomic flip; clear ownership (env var); no schema changes; rollback is a `kubectl set env` (or local `.env` toggle) plus a frontend reload.
- **Consequences:** OFF path renders the existing 12 pages and the existing sidebar; ON path swaps the route table inside `App.tsx` so `/flow/:id` is mounted and `/sessions/:id` (Monitor), `/workflows/:id` (PentestWorkflow), `/agents` (AgentCatalog) display in-app deprecation banners ("This page will be removed in v3.4 — use /flow/:id"). Tests: `test_feature_flag_off_render.tsx` (e2e), `test_feature_flag_on_routes.tsx` (e2e).
- **Follow-up:** if early-adopter customer cohorts need staged rollout in v3.4, ADR-004a introduces per-team override on top of the global flag (additive, not breaking).

### ADR-005: AgentAdapter preservation contract (how Pentester role invokes existing 11 adapters)

- **Status:** Locked.
- **Decision:** Pentester role emits a structured LLM tool call: `{"name": "<tool_slug>", "input": {"intent": "<intent_slug>", "config": {…}}}` where `tool_slug ∈ list_agent_types()` and `intent_slug ∈ INTENT_VOCABULARY`. Performer's `_dispatch_tool` resolves via `get_adapter(tool_slug)`, runs `RiskFilter` + `filter_plan_steps` + `WhitelistValidator` + `EgressMonitor` (in `OrchestratorService.run` order, `service.py:80-178`), and persists per-step `AgentExecution` rows exactly as today. The 11 adapters in `backend/app/agents/{nmap,nuclei,metasploit,pyrit,passive_recon,subfinder,dnsx,httpx_tool,cloudenum,wappalyzer}.py` are **unchanged**.
- **Decision drivers:** Principle 1 (safety chain invariance); 85-test preservation; spec locked "OSA-strong hybrid"; intent vocabulary already exists at `backend/app/agents/intent_vocabulary.py`.
- **Alternatives rejected:** RoleAdapter wrapper layer — re-introduces the god-class problem the v3.2.1 ToolEntry pattern eliminated; reimplementation inside role — duplicates safety logic, violates Principle 5 of v3.2.1.
- **Why A:** zero adapter changes, zero safety changes, role-level system prompts can be tuned in isolation, intent vocabulary stays the closed enum that prevents free-form hallucination per v3.2.1 §4.3.
- **Consequences:** Pentester's `tools_allowed` is computed at role-instantiation time as `[t.slug for t in palette_for_domain(session.domain_tags)]` (using `backend/app/agents/registry.py:198`); domain tags derive from `domain_agent_slug` (web-app-agent → `{"web", "api"}` etc., from `backend/app/agents/domains/__init__.py`); the Pentester system prompt lists its palette + intent vocabulary; tests: `test_pentester_tool_dispatch.py` (unit), `test_pentester_full_flow.py` (integration, end-to-end with mocked adapters).
- **Follow-up:** if v3.4 introduces Coder/Installer roles with raw shell, a separate `RoleAdapter` for `terminal-runner` would be required and would need its own safety re-validation contract.

---

## Phase-by-Phase Plan

### P0 PentAGI Analysis Reference (target: 1 docs PR; no code, no tests)

**Goal:** Produce the two artifacts that satisfy spec Component-1 acceptance: (a) `.omc/research/pentagi-reference.md` with the detailed PentAGI ↔ OSA comparison matrix, and (b) plan §1 prose (2–3 pages) of adoption / rejection / gap decisions. Reviewer must be able to validate the adoption decision from §1 alone, and a phase implementer must be able to do 1:1 lookup from the reference matrix.

**Why P0 not P1:** Spec line 303 maps Component-1 to "P0 (pre-implementation)". P0 unblocks Critic + Architect review of the port direction before any schema or code change ships.

#### Files to create

- `/Users/chrisjung/myproject/offensive-security/.omc/research/pentagi-reference.md` — the reference matrix (the file P0 produces). Sections required:
  1. **UI patterns table** (PentAGI → OSA mapping): `react-resizable-panels` 2-pane shell, left tabs (Automation/Assistant/Dashboard), right tabs (Terminal/Tasks/Agents) — adopted; right tabs (Searches/Vector Store/Screenshots) — deferred v3.4; xterm.js + 4 addons — adopted P3-main; Monaco editor — deferred v3.4.
  2. **14-role definition table** with `v1` (Generator/Pentester/Memorist/Adviser/Reflector/Reporter — 6 adopted) vs `v3.4+` (PrimaryAgent/Assistant/Refiner/Planner/Enricher/Coder/Installer/Searcher/Mentor — 9 deferred or merged) split. For each role: PentAGI source file in `backend/pkg/providers/`, OSA target path under `backend/app/orchestrator/roles/`, intent vocabulary mapping, tool palette source, retry/iteration caps.
  3. **Tool catalog comparison**: PentAGI's ~34 tools (barrier/delegation/primitive/web/memory) → OSA's 11 AgentAdapters; explicit ADR-005 contract for the Pentester-to-AgentAdapter dispatch envelope; rejection notes for `terminal` raw-shell tool (deferred to v3.4 Coder/Installer).
  4. **GraphQL subscription topic mapping**: PentAGI's `terminalLogAdded` / `agentLogAdded` / `taskCreated` / `taskUpdated` / etc. → OSA's `event_bus.publish(session_id, event, topic=...)` topic strings ("terminal" / "agents" / "tasks") under ADR-001.
  5. **DB schema comparison**: PentAGI's `msglogs` / `agentlogs` / `searchlogs` / `vectorstorelogs` / `termlogs` / `screenshots` / `assistant_logs` / `msgchains` → OSA's existing `pentest_sessions` + `workflow_messages` + `agent_executions` + new `msgchains` + `memory_entries`; gap analysis on what OSA preserves vs absorbs.
  6. **Safety model comparison**: PentAGI's brake set (iteration caps + Execution Monitor + Adviser injection + Reflector wrap + `ask` / `done` barrier) vs OSA's 5-layer safety chain (whitelist + risk_filter + exploit_allowlist tier-gated + egress_monitor + kill_switch + audit). Explicit OSA-strong-hybrid rationale (Critic must agree the hybrid does not weaken safety).

- plan §1 prose **inside this v4.0 plan file** (NEW section added below this P0 phase block, before "P1 Foundation"). The §1 prose is a 2–3 page narrative: (a) why PentAGI patterns are adopted (5 high-leverage patterns: 2-pane shell, role-based Performer, agent-as-tool, pgvector RAG, topic-per-panel streaming); (b) what is rejected (raw `terminal` tool, Searches/VectorStore/Screenshots tabs in v1, 14 roles → 6 roles, GraphQL substrate as default, external LLM provider expansion); (c) the 3 substantive gaps (PentAGI safety < OSA safety → preserve OSA layers; PentAGI flat SubTask list vs OSA DAG-style plan_json → bridge in P4; PentAGI per-flow Docker container vs OSA per-tool container → preserve OSA's existing Docker backend through Pentester dispatch).

#### Files to modify

- this plan file (`.omc/plans/osa-pentagi-port-autopilot-v4.0.md`) — add a "§1 PentAGI Analysis (Summary)" section between this P0 block and the RALPLAN-DR header, OR (cleaner) leave §1 in this Phase block and link from a top-level §1 table-of-contents anchor. Final shape determined by the writer agent in P0 execution.

#### Tests

- No tests; this is a docs PR.

#### Rollback strategy

- `rm /Users/chrisjung/myproject/offensive-security/.omc/research/pentagi-reference.md`
- Revert the §1 prose addition to this plan file.
- No code or schema impact; zero test count change.

#### Acceptance gate

- Reviewer reads §1 (2–3 pages inside this plan file) and can answer: (a) which 5 PentAGI patterns are adopted, (b) what is explicitly rejected, (c) what gaps exist between PentAGI and OSA safety models.
- A P1 implementer opens `.omc/research/pentagi-reference.md` and can answer: (a) what is the OSA target path for `pentagi/backend/pkg/providers/performer.go`, (b) what is the topic string emitted by `agentLogAdded`'s OSA counterpart, (c) what is the DB schema diff between PentAGI's `msgchains` and OSA's planned `msgchains` table.
- Test count unchanged: still **85 tests** after P0 merge.

---

### P1 Foundation (target: 1 PR)

**Goal:** Land schema (pgvector + msgchains + memory_entries), Performer skeleton, Role abstract class, and SQLAlchemy models. **Zero UI changes.** Existing 85 tests still pass.

#### Files to create

- `backend/alembic/versions/005_pgvector.py` — `CREATE EXTENSION IF NOT EXISTS vector;` (no table changes). Down: `DROP EXTENSION vector;` guarded by existence.
- `backend/alembic/versions/006_msgchains.py` — `msgchains` table (id UUID PK, pentest_session_id UUID FK CASCADE, role_name VARCHAR(32), messages_json JSONB, started_at TIMESTAMPTZ, ended_at TIMESTAMPTZ, status VARCHAR(16), retries INT NOT NULL DEFAULT 0; index `(pentest_session_id, started_at)`); `memory_entries` table (id UUID PK, domain_tag VARCHAR(32), source_yaml_path TEXT, name TEXT, description TEXT, embedding `vector(384)`, metadata_json JSONB, created_at TIMESTAMPTZ); hnsw index per ADR-002.
- `backend/app/models/msgchain.py` — `MsgChain` SQLAlchemy model with relationship to `PentestSession.msgchains` (add the back-populates row in `session.py`).
- `backend/app/models/memory_entry.py` — `MemoryEntry` SQLAlchemy model using `pgvector.sqlalchemy.Vector(384)`.
- `backend/app/orchestrator/performer.py` — `Performer` class skeleton (no Role wiring yet): `__init__(db, session_id)`, `register_role(role)`, `async run_session()` stub, `PERFORMER_MAX_ITER = 64`, `_dispatch_tool(name, input)` stub raising `NotImplementedError` (wired in P2).
- `backend/app/orchestrator/roles/__init__.py` — re-export registry surface.
- `backend/app/orchestrator/roles/base.py` — `Role` abstract dataclass (name, system_prompt, llm_model, tools_allowed, max_tool_calls, `async run(performer, context) -> RoleResult`).
- `backend/app/orchestrator/roles/registry.py` — in-memory dict `ROLE_REGISTRY: dict[str, type[Role]]` + `register_role`, `get_role`, `list_roles`.
- `backend/app/knowledge/seed_memory.py` — CLI entrypoint `python -m app.knowledge.seed_memory` to chunk SKILL.md + dorks/*.yaml into `memory_entries` rows; idempotent (re-run truncates + re-inserts under a `--force` flag). Not run inside the app boot path.
- `backend/tests/unit/test_performer_skeleton.py` — verifies `Performer` can be instantiated, `register_role` adds entries, `run_session()` no-op returns when no roles.
- `backend/tests/unit/test_msgchain_model.py` — round-trip persist a `MsgChain` row, verify cascade delete from `PentestSession`.
- `backend/tests/unit/test_memory_entry_model.py` — round-trip persist a `MemoryEntry` row with a fixture 384-dim vector; SELECT by id returns it.
- `backend/tests/unit/test_role_base.py` — `Role` abstract class cannot be instantiated; concrete subclass passes contract.
- `backend/tests/unit/test_seed_memory_chunks.py` — smoke test: fixture SKILL.md + dork YAML produces expected chunk count (no embedding call; embedding mocked).
- `backend/tests/unit/test_msgchain_no_subtask_overlap.py` (**SF-2 added in revision v2**) — schema disjointness invariant: `PentestSession.draft_plan_json` keys ∩ `MsgChain.messages_json[*]` keys = ∅. Asserts that `draft_plan_json.steps[*]` carries only `{order, agent, action, description, config, tier, status}` and `MsgChain.messages_json[*]` carries only `{role, content, tool_use_id, usage, timestamp}`. Prevents the double-source-of-truth bug flagged in Open Issue #4.

#### Files to modify

- `backend/app/models/__init__.py` — re-export `MsgChain` and `MemoryEntry`.
- `backend/app/models/session.py` — add `msgchains: Mapped[list["MsgChain"]] = relationship(back_populates="session", cascade="all, delete-orphan")` to `PentestSession` (mirror the existing `workflow_messages` pattern).
- `backend/pyproject.toml` — add the locked **dep 4-tuple** (revision v2, MF-3): `"pgvector==0.3.6"`, `"sentence-transformers==3.3.1"`, `"torch==2.4.1"` (CPU-only wheel via `--extra-index-url https://download.pytorch.org/whl/cpu` in dev/install docs), `"numpy>=1.26,<2.0"`. Rationale: sentence-transformers 3.3.x supports torch 2.4.x; torch 2.4.x supports numpy>=1.23,<2.x ABI; pgvector 0.3.6 is the current pgvector-python stable for SQLAlchemy 2.0+. **Spike sub-task in first P1 hour:** verify the tuple resolves on Python 3.12 (project's pinned interpreter per `requires-python = ">=3.12"` in current pyproject.toml). If resolver fails, fall back tuple is `(pgvector==0.3.4, sentence-transformers==3.0.1, torch==2.3.1, numpy==1.26.4)`; second fall back `(pgvector==0.2.5, sentence-transformers==2.7.0, torch==2.2.2, numpy==1.26.4)`. The first-resolving tuple is what ships; the choice is recorded in the P1 PR description.
- `backend/app/core/config.py` — add `embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"`, `embedding_vector_dim: int = 384`, `memorist_k: int = 3`, `memorist_score_threshold: float = 0.7`, `osa_flow_ui_enabled: bool = False`, `performer_max_iter: int = 64`, `max_concurrent_performer_sessions: int = 4` (**SF-3 added in revision v2; operationalizes ADR-003 concurrency cap on single uvicorn worker**).
- `backend/alembic/env.py` — no change expected (Base.metadata auto-discovers new models via the `models/__init__.py` re-exports).

#### Tests

- Existing 85 tests must pass unchanged (`pytest -q` from `backend/`).
- New unit tests (6, after revision v2 SF-2 addition): `test_performer_skeleton.py`, `test_msgchain_model.py`, `test_memory_entry_model.py`, `test_role_base.py`, `test_seed_memory_chunks.py`, `test_msgchain_no_subtask_overlap.py`.
- Baseline target after P1: **85 + 6 = 91 tests passing.**

#### Rollback strategy

- `alembic downgrade 004` reverts `006_msgchains` (drops `msgchains`, `memory_entries`, drops hnsw index, drops `vector` extension if no other DB user requires it).
- `pip uninstall pgvector sentence-transformers numpy` (or just `pip install -e .` against pre-P1 `pyproject.toml`).
- Delete the 12 new files; revert the 4 modified files via `git checkout HEAD~1`.
- Rollback verification: `pytest -q` returns the same 85-test green baseline.

#### Acceptance gate

- `pytest -q backend/tests/` → **91 tests passing** (85 + 6).
- `alembic upgrade head` then `alembic downgrade 004` then `alembic upgrade head` → idempotent.
- **Dep resolver check (revision v2 MF-3 explicit AC):** `pip install -e backend/[dev]` on x86_64 Linux Python 3.12 with the locked dep tuple resolves without conflict (pip exit 0). Verified by `python -c "import torch, numpy, sentence_transformers, pgvector; print(torch.__version__, numpy.__version__, sentence_transformers.__version__, pgvector.__version__)"` succeeding with no `ImportError`. The exact installed versions are echoed in the P1 PR description.
- **Cold-start warm-up (revision v2 Open Issue #2 resolution):** `backend/app/main.py` adds a FastAPI startup hook that loads `SentenceTransformer(settings.embedding_model_name)` on boot (singleton) so the first Memorist call inside a request does not pay 2–4s load tax. Verified by `test_main_startup_warms_embedding_model.py` (this test is part of the 6 P1 new tests, replacing… actually it's a 7th test — see note below).
- `docker build backend/` succeeds; the resulting image is at most ~600MB larger than v3.2.1 (sentence-transformers + torch CPU).
- No frontend changes; `npm run build` from `frontend/` is unaffected.

*Note: the startup warm-up test is added as the 7th P1 test (`test_main_startup_warms_embedding_model.py`), bringing P1 to **85 + 7 = 92 tests passing**. Cumulative ladder (single source of truth, mirrored in Dependencies & Ordering block): P0 85 → P1 92 → P3-spike 95 → P2a 103 → P2b 105 → P3-main 110 → P4 116 → P5 120. Final v4.0 cumulative target = **120 tests** (85 baseline + 35 net new).*

---

### P2 Agent Architecture (target: 2 PRs)

#### P2a: Roles & Performer engine

**Goal:** Land the 6 roles, wire Performer's tool dispatcher to `get_adapter()` via the AgentAdapter preservation contract (ADR-005), implement Adviser/Reflector wrappers. **Still zero UI changes.**

##### Files to create

- `backend/app/orchestrator/roles/generator.py` — `Generator(Role)`: emits `{ambiguity, blockers, reasoning, draft_plan}` JSON (same envelope as `workflow_service.CHAT_SYSTEM_PROMPT`); reused in P4 to drive the ambiguity loop. P2a only ships the role class + system prompt + a smoke `run()` returning a fixture envelope (no Anthropic call yet) so wire-up is testable.
- `backend/app/orchestrator/roles/pentester.py` — `Pentester(Role)`: `tools_allowed` derived from `palette_for_domain(session.domain_tags)`; emits `{name, input}` tool calls per ADR-005; Performer's `_dispatch_tool` routes to `get_adapter(name).execute(target, input.config)`.
- `backend/app/orchestrator/roles/memorist.py` — `Memorist(Role)`: ships in P2a as the auto-call wrapper; exposes a `search_in_memory(query, k, score_threshold)` helper used by both Generator/Pentester pre-SubTask hooks; uses `sentence_transformers.SentenceTransformer(settings.embedding_model_name)` lazily loaded singleton.
- `backend/app/orchestrator/roles/adviser.py` — `Adviser(Role)`: triggered when same tool ≥ 5 calls or total tool calls ≥ 10 in a single Pentester chain; injects a loop-break message back into the chain.
- `backend/app/orchestrator/roles/reflector.py` — `Reflector(Role)`: wrap around every Role.run() try/except; retries up to 3× with exponential backoff (200ms / 1s / 5s) — same policy as `ModelClient.send()`.
- `backend/app/orchestrator/roles/reporter.py` — `Reporter(Role)`: consumes all SubTask outputs + findings → calls existing `ReportGenerator` in `backend/app/reports/generator.py`; minimal v1, no markdown re-formatting.
- `backend/app/orchestrator/roles/seed.py` — register the 6 roles into `ROLE_REGISTRY` at module-import time.
- `backend/tests/unit/test_role_generator.py` — fixture prompts → envelope shape.
- `backend/tests/unit/test_role_pentester_dispatch.py` — tool-call routing to fixture adapters; verifies `palette_for_domain` filtering.
- `backend/tests/unit/test_role_memorist_search.py` — pgvector cosine similarity against a small fixture; recall ≥ 0.95 at k=3.
- `backend/tests/unit/test_role_adviser_trigger.py` — counters trip at thresholds.
- `backend/tests/unit/test_role_reflector_retry.py` — 3 retries with exponential backoff on transient exception; persistent failure raises.
- `backend/tests/unit/test_role_reporter_emit.py` — invokes `ReportGenerator` with fixture findings.
- `backend/tests/integration/test_performer_full_cycle.py` — Generator → Pentester (1 nmap adapter invocation, mocked DockerBackend) → Reporter; verifies `MsgChain` rows persisted, `AgentExecution` row persisted.
- `backend/tests/unit/test_p2a_no_topic_prefix.py` (**MF-2 revision v2 — pre-ADR-lock invariant**) — greps the P2a diff (or, equivalently, the current `backend/app/orchestrator/performer.py`, `backend/app/orchestrator/roles/*.py`) for any literal `topic="terminal"`, `topic="tasks"`, `topic="agents"` string. Fails the PR if found before ADR-001 is Accepted. Allows `topic="session"` (the v2.1 default). Removed (deleted) when ADR-001 flips to Accepted at the end of P3-spike merge.

##### Files to modify

- `backend/app/orchestrator/performer.py` — wire `_dispatch_tool` to `get_adapter(name).execute(target, input.config)` inside `OrchestratorService.run`'s safety-chain order; preserves `event_bus.publish(session_id, …)` events for downstream UI.
- `backend/app/agents/registry.py` — no API change; verify `palette_for_domain` already accepts `frozenset[str]`. (Already true at `registry.py:198`.)

##### Rollback strategy

- Revert P2a PR. All 11 adapters remain unchanged; `OrchestratorService.run` still works because P2a does not touch its v2.1 entry path (Performer is only invoked when P3 mounts the new UI route OR an explicit env-var `OSA_USE_PERFORMER=1` is set; P3-main lights up the UI path).
- `alembic` state unchanged (P1 schemas already in place).
- Rollback test: 95-test baseline (post-P3-spike) holds.

##### Acceptance gate

- `pytest -q` → **103 tests passing** (95 baseline from P3-spike + 8 new P2a tests including `test_p2a_no_topic_prefix.py`).
- Performer can run a 3-role cycle (Generator→Pentester→Reporter) end-to-end against mocked adapters without any UI.
- `egress_monitor`, `whitelist`, `risk_filter`, `exploit_allowlist` all invoked during Pentester's adapter dispatch (verified by `test_performer_full_cycle.py` assertions on audit log rows).

#### P2b: AttackPlanner → Generator adaptation

**Goal:** Bridge the legacy `AttackPlanner.create_plan` to the new `Generator` role without breaking `OrchestratorService.run` or `WorkflowService.send_message`. Ship an API shim so existing tests continue to call the legacy entry path.

##### Files to create

- `backend/app/orchestrator/legacy_shim.py` — `class LegacyPlannerShim`: exposes `async create_plan(prompt, target)` matching `AttackPlanner` signature; internally instantiates `Generator` and post-processes its envelope into the v2.1 `{target_summary, risk_level, steps}` shape; persists nothing.
- `backend/tests/unit/test_legacy_planner_shim.py` — fixture: legacy contract holds; envelope mapping is loss-less for the fields v2.1 consumes.
- `backend/tests/integration/test_pipeline_shape.py` (**SF-5 revision v2**) — explicit regression for `tests/integration/test_pipeline.py:120` content-assertion concern (Open Issue #7). Asserts that `AttackPlanner(use_generator_role=False).create_plan(prompt, target)` produces step content identical to v2.1 baseline (specifically `plan["steps"][0]["agent"] == "nmap"` for the canonical recon fixture, plus the full step shape `{order, agent, action, description, config, tier}`). Tests the OFF path; the ON path's nondeterminism is acknowledged and not asserted.

##### Files to modify

- `backend/app/orchestrator/planner.py` — `AttackPlanner.__init__` accepts an optional `use_generator_role: bool = False` (default OFF). When OFF, behavior is identical to v3.2.1 (Critic-safe). When ON, internally constructs a `LegacyPlannerShim` and proxies `create_plan`. Defaults preserved so all 85 existing tests pass without flag flip.
- `backend/app/orchestrator/service.py` — no API change. Performer wiring lands here in P3-main / P4, not P2b.

##### Rollback strategy

- Revert P2b PR.
- The shim is opt-in via constructor flag; if the flag never flips, all callers behave identically to v3.2.1.
- Rollback test: **103-test baseline (post-P2a) holds.**

##### Acceptance gate

- `pytest -q` → **105 tests passing** (103 baseline from P2a + 2 new: legacy_shim + pipeline_shape regression).
- `tests/integration/test_pipeline.py` (the v2.1 end-to-end pipeline) still green; `AttackPlanner` constructed without `use_generator_role` is unchanged.
- `AttackPlanner(use_generator_role=True).create_plan(prompt, target)` returns a plan in v2.1 shape; same prompt+target produces equivalent step count (sanity check, not strict equality).
- **`test_pipeline_shape.py` (SF-5)** asserts OFF-path step-content equivalence — this is the hard gate that prevents Open Issue #7 regression.

---

### P3 UI Shell (target: 1 spike PR + 1 main PR)

#### P3-spike: Streaming substrate ADR + minimal substrate change

**Goal:** Resolve ADR-001 in code. Land the topic-filter extension to `EventBus` and `/ws/sessions/{session_id}` with no UI consumers yet. Document the ADR under `.omc/research/adr-001-streaming-substrate.md`.

##### Files to create

- `.omc/research/adr-001-streaming-substrate.md` — ADR per ADR-001 above; written as the artifact of the spike, not a planning doc.
- `frontend/src/hooks/useTopicWebSocket.ts` — small typed hook subscribing to a `(sessionId, topic)` pair; co-exists with the legacy `useWebSocket` until P5.
- `backend/tests/unit/test_event_bus_topic_filter.py` — `event_bus.publish(session, event, topic="terminal")` only reaches subscribers with `topic="terminal"`.
- `backend/tests/integration/test_ws_topic_subscription.py` — open `/ws/sessions/{id}?topics=terminal` → receive only `topic="terminal"` events; default subscription `(no topics)` still receives `topic="session"` for v2.1 compatibility.
- `backend/tests/perf/test_eventbus_topics.py` (**MF-4 revision v2 — ADR-001 gate**) — perf benchmark printing the three measured numbers (p99 latency, QueueFull drop rate, subscriber-leak invariant) under 60 events/sec × 3 topics × 10 sessions synthetic load. The PR's CI passes only if all three thresholds clear. The script also writes its output to `.omc/research/adr-001-streaming-substrate.md` as the ADR's measured-evidence section.

##### Files to modify

- `backend/app/core/events.py` — `EventBus.subscribe(session_id, topics: list[str] | None = None)`, `EventBus.publish(session_id, event, topic: str = "session")`; topic filter applied on `put_nowait`.
- `backend/app/api/v1/ws.py` — parse `topics` query param, pass to subscribe; backward-compat: no `topics` ⇒ legacy behavior.
- `frontend/package.json` — no new deps yet (the hook only uses native WebSocket).

##### Rollback strategy

- Revert P3-spike PR.
- All v2.1 + P1 callers default to `topic="session"`, which matches v2.1 publish semantics exactly.
- Rollback test: **92-test baseline (post-P1) holds.**

##### Acceptance gate

- `pytest -q` → **95 tests passing** (92 baseline from P1 + 3 new: topic_filter unit + ws_topic_subscription integration + eventbus_topics perf benchmark).
- ADR-001 status flipped to **Accepted** or **Rejected** in this PR commit, based on the three measured Go/No-Go thresholds (p99 latency, QueueFull rate, no subscriber leak). `.omc/research/adr-001-streaming-substrate.md` written with the measured numbers and the verdict.
- `npm run build` from `frontend/` passes (`useTopicWebSocket.ts` compiles, no UI consumers yet).

#### P3-main: `/flow/:id` route + 3 tabs + feature flag

**Goal:** Mount the new shell behind `OSA_FLOW_UI`. With flag OFF, the app behaves exactly as v3.2.1 (12 pages, existing sidebar). With flag ON, `/flow/:id` renders a 2-pane resizable layout (left: Automation/Assistant/Dashboard, right: Terminal/Tasks/Agents), and `/sessions/:id`, `/workflows/:id`, `/agents` show in-app deprecation banners.

##### Files to create

- `backend/app/api/v1/feature_flags.py` — `GET /api/v1/config/feature-flags` returning `{osa_flow_ui_enabled: bool}` (sourced from `settings.osa_flow_ui_enabled`).
- `frontend/src/pages/FlowPage.tsx` — `/flow/:id` route entry; renders the 2-pane shell, lazy-loads tab components.
- `frontend/src/components/flow/TwoPaneShell.tsx` — wraps `react-resizable-panels` `PanelGroup`/`Panel`/`PanelResizeHandle`.
- `frontend/src/components/flow/LeftPane.tsx` — Automation/Assistant/Dashboard tabs via `@radix-ui/react-tabs` (already installed); each tab is a thin component for v1 (Automation = existing WorkflowChat reused; Dashboard = existing InteractionDashboard data; Assistant tab body for v4.0 is a placeholder reading "Assistant sidechannel — v3.4").
- `frontend/src/components/flow/RightPane.tsx` — Terminal/Tasks/Agents tabs.
- `frontend/src/components/flow/tabs/TerminalTab.tsx` — xterm.js + addons (fit, search, web-links, webgl) wired to `useTopicWebSocket(sessionId, "terminal")`.
- `frontend/src/components/flow/tabs/TasksTab.tsx` — renders `session.draft_plan_json.steps` and current SubTask status; subscribes to `topic="tasks"`.
- `frontend/src/components/flow/tabs/AgentsTab.tsx` — renders 6-role status panel; `msgchains` last N messages per role via `topic="agents"`; merges from `GET /api/v1/pentest-sessions/{id}/msgchains` (new endpoint, ships in P3-main).
- `frontend/src/components/flow/tabs/AutomationTab.tsx` — reuses `<WorkflowChat>` from `frontend/src/components/WorkflowChat.tsx` (extracted from `PentestWorkflow.tsx`).
- `frontend/src/components/flow/tabs/DashboardTab.tsx` — reuses `<InteractionDashboard>` data fetcher; minimal visual rework.
- `frontend/src/components/banners/DeprecationBanner.tsx` — banner shown on legacy pages when `osa_flow_ui_enabled=true`.
- `frontend/src/api/featureFlags.ts` — `getFeatureFlags()` API client.
- `backend/app/api/v1/pentest_sessions.py` — extend with `GET /pentest-sessions/{id}/msgchains` listing `MsgChain` rows for the Agents tab.
- `backend/tests/integration/test_msgchains_endpoint.py` — GET returns rows from `msgchains` filtered by session_id.
- `backend/tests/integration/test_feature_flag_endpoint.py` — GET returns current flag state.
- `frontend/e2e/test_flag_off_renders_v2_1.spec.ts` — flag OFF ⇒ existing 12 pages render; navigation to `/flow/:id` 404s or redirects.
- `frontend/e2e/test_flag_on_renders_flow.spec.ts` — flag ON ⇒ `/flow/:id` mounts; right-pane tabs switch; Terminal tab connects to WS.
- `frontend/e2e/test_legacy_pages_show_deprecation_banner.spec.ts` — flag ON ⇒ `/sessions/:id`, `/workflows/:id`, `/agents` show banner.

##### Files to modify

- `frontend/package.json` — add `"react-resizable-panels": "^2.1.0"`, `"@xterm/xterm": "^5.5.0"`, `"@xterm/addon-fit": "^0.10.0"`, `"@xterm/addon-search": "^0.15.0"`, `"@xterm/addon-web-links": "^0.11.0"`, `"@xterm/addon-webgl": "^0.18.0"`.
- `frontend/src/App.tsx` — add `/flow/:id` route inside `<Shell>` guard; conditionally render deprecation banners on legacy routes based on the feature-flag fetch; preserve all existing routes.
- `frontend/src/api/client.ts` — add `getMsgChains(sessionId)`.
- `backend/app/main.py` — register `feature_flags` router (`from app.api.v1 import feature_flags as feature_flags_router`).
- `backend/app/core/config.py` — confirm `osa_flow_ui_enabled` is present (added in P1).

##### Tests

- Existing 105 tests still pass.
- New: 2 backend integration + 3 frontend e2e = 5 new tests.
- Baseline target after P3-main: **105 + 5 = 110 tests passing.**

##### Rollback strategy

- Revert P3-main PR (substrate change from P3-spike stays — it's harmless to v2.1 callers).
- Frontend `npm install` reverts to previous lockfile.
- Backend rolls back the `feature_flags` router and the `/msgchains` endpoint.
- Rollback verification: flag-OFF path still functional under just P3-spike state.

##### Acceptance gate

- `pytest -q` → **110 tests passing**; `npm run build` succeeds in `frontend/`.
- Manual smoke (flag OFF): all 12 pages render and pass v2.1 navigation flow.
- Manual smoke (flag ON): `/flow/:id` 2-pane shell renders; resizing works; Terminal tab streams; Tasks tab lists steps; Agents tab lists 6 roles.

---

### P4 Workflow Loop (target: 1 PR)

**Goal:** Light up the ambiguity-gated loop end-to-end. Generator → (ambiguity > 0.35 ⇒ ask tool ⇒ user reply) ↻; on ≤ 0.35 + approval, Performer runs; Pentester invokes adapters; Memorist auto-calls pre-SubTask; safety chain enforced; rescope flow integrates.

#### Files to create

- `backend/app/orchestrator/ambiguity_loop.py` — `AmbiguityLoop` class: drives Generator across multiple turns, decrements `interview_turn_count`, persists `WorkflowMessage` rows, transitions session to `ready_for_review` / `needs_human_review` / `interview_paused`. Replaces the inline `_next_state_after_turn` logic in `workflow_service.py:178` once the new path is feature-flagged in.
- `backend/app/orchestrator/ask_tool.py` — `ask(question: str, options: list[str] | None) -> AskResponse`: writes an `ask_event` to `event_bus.publish(session_id, …, topic="tasks")`; frontend `<WorkflowChat>` renders the question + input; user reply is POSTed via the existing `/messages` endpoint and consumed by the loop's next turn.
- `backend/app/orchestrator/memorist_auto_call.py` — `auto_inject(performer, subtask_description) -> list[MemoryEntry]`: invoked by Pentester pre-SubTask hook; embeds description, queries pgvector, returns top-3 ≥ 0.7; merges into Pentester's context.
- `backend/app/orchestrator/runtime_delegator.py` — runtime tool-call dispatcher used by Pentester to spawn sub-role invocations (e.g., Pentester emits `memorist.search(query)` mid-chain); not per-step approval — per Principle 6 of v3.2.1, only tier_gating + Adviser + Reflector + RescopeService gate runtime delegations.
- `backend/tests/integration/test_ambiguity_loop_full.py` — fixture: user prompt with ambiguity ⇒ Generator asks ⇒ user replies ⇒ ambiguity ≤ 0.35 ⇒ session ready_for_review.
- `backend/tests/integration/test_memorist_auto_call.py` — fixture SubTask description + seeded memory entries ⇒ returns top-3.
- `backend/tests/integration/test_runtime_delegation.py` — Pentester emits a `memorist.search` tool call mid-chain; verifies result is injected into the next LLM message.
- `backend/tests/integration/test_p4_safety_regression.py` — full session with all 5 safety layers asserted (whitelist + risk + allowlist + egress + kill switch).
- `backend/tests/integration/test_rescope_in_p4_flow.py` — discovered out-of-scope target during Pentester run ⇒ `paused_for_rescope` ⇒ operator decides ⇒ resumes.
- `frontend/e2e/test_full_pentest_session_v4.spec.ts` — chat → ambiguity → ask → reply → approve → run → report (with mocked adapters).

#### Files to modify

- `backend/app/orchestrator/workflow_service.py` — re-route `send_message` through `AmbiguityLoop` when `settings.osa_flow_ui_enabled` is True; OFF path = unchanged. The `CHAT_SYSTEM_PROMPT` remains shared with Generator's system prompt.
- `backend/app/orchestrator/service.py` — `OrchestratorService.run` invokes `Performer` when `settings.osa_flow_ui_enabled=True` AND session was approved via the new loop (sentinel column `session.uses_performer_flow: bool` added optionally in P4 migration — or inferred from `domain_agent_slug` presence). OFF path = unchanged.
- `backend/app/orchestrator/planner.py` — no change (P2b already shimmed it).
- `frontend/src/components/WorkflowChat.tsx` — render ask-tool prompts (question + optional options) as inline chat bubbles with reply input.

#### Tests

- Existing 110 tests pass.
- New: 5 integration + 1 e2e = 6 new tests.
- Baseline target after P4: **110 + 6 = 116 tests passing.**

#### Rollback strategy

- Revert P4 PR.
- `osa_flow_ui_enabled=False` reverts to v3.2.1 workflow loop behavior.
- The new modules are unused when flag is OFF.

#### Acceptance gate

- `pytest -q` → **116 tests passing.**
- e2e smoke: full pentest session from prompt → clarify → approve → exec → report on a single fixture target.
- Safety regression matrix (below) is all green.

---

### P5 Deprecation (target: 1 PR, scheduled 2 releases later)

**Goal:** Remove `Monitor.tsx`, `PentestWorkflow.tsx`, `AgentCatalog.tsx`, `InteractionDashboard.tsx` once `osa_flow_ui_enabled=true` has been the default for 2 releases without bug reports. Preserve `WorkflowBuilder`, `Workflows`, `Reports`, `Admin`, `Login`, `Projects`, `ProjectDetail`, `Dashboard`.

#### Files to delete

- `frontend/src/pages/Monitor.tsx` (Terminal tab replaces it)
- `frontend/src/pages/PentestWorkflow.tsx` (`/flow/:id` replaces it)
- `frontend/src/pages/AgentCatalog.tsx` (Agents tab replaces it)
- `frontend/src/pages/InteractionDashboard.tsx` (Dashboard tab absorbs it)
- `frontend/src/hooks/useWebSocket.ts` (`useTopicWebSocket` supersedes; only delete after grep confirms no other consumers)
- `frontend/src/components/banners/DeprecationBanner.tsx` (no longer needed)

#### Files to modify

- `frontend/src/App.tsx` — remove `/sessions/:id`, `/workflows/:id`, `/agents`, `/interactions` routes; remove imports.
- `frontend/src/components/layout/SidebarShell.tsx` — drop sidebar links to removed pages.
- `frontend/src/api/client.ts` — drop `useWebSocket`-only helpers if any.
- `backend/app/api/v1/sessions.py` — `GET /sessions/:id` may stay for back-compat if reports still call it; verify with grep.

#### Tests

- All 116 cumulative tests (post-P4) still pass after deletion (no test should reference the deleted pages).
- New: 4 per-page deletion regression e2e tests (**SF-1 revision v2 — replaces the single sweep**):
  - `frontend/e2e/test_p5_monitor_deleted.spec.ts` — `/sessions/:id` returns 404 (or redirects to `/flow/:id` if route alias chosen); no `<MonitorPage>` component mounts; bundle does not include the Monitor chunk.
  - `frontend/e2e/test_p5_pentest_workflow_deleted.spec.ts` — `/workflows/:id` returns 404; no `<PentestWorkflowPage>` component mounts; bundle does not include the PentestWorkflow chunk.
  - `frontend/e2e/test_p5_agent_catalog_deleted.spec.ts` — `/agents` returns 404; no `<AgentCatalogPage>` component mounts; bundle does not include the AgentCatalog chunk.
  - `frontend/e2e/test_p5_interaction_dashboard_deleted.spec.ts` — `/interactions` returns 404; no `<InteractionDashboardPage>` component mounts; bundle does not include the InteractionDashboard chunk.
- Baseline target after P5: **116 + 4 = 120 tests passing.** This is the final v4.0 total.

#### Rollback strategy

- Revert P5 PR (re-introduces pages) — the route table is the only coupling.
- Frontend rebuild required.

#### Acceptance gate

- All e2e tests pass.
- Manual operator smoke checklist signed off.
- 14-day soak window with `osa_flow_ui_enabled=true` in production environments before scheduling P5 merge.
- **Soak rollback criterion (SF-4 revision v2, MINOR-2 clarified):** abort P5 (revert to P4 state, keep flag-on path but retain legacy pages with deprecation banners) if during any rolling 24-hour window inside the 14-day soak, the **session error rate exceeds 2× the trailing-7-day baseline measured before flag-on rollout**, where:
  - **Metric name (Prometheus): `osa_session_error_rate_ratio`** (single canonical name). Computed as `sum(rate(http_requests_total{path=~"/api/v1/pentest-sessions/.*", status=~"5.."}[5m])) / sum(rate(http_requests_total{path=~"/api/v1/pentest-sessions/.*"}[5m]))`. This metric is added by **P3-main** (instrumentation lands with the new flow route) and is part of the P3-main acceptance gate; P4 adds an alerting rule that fires when the criterion trips.
  - The rollback owner is the on-call SRE.
  - If the criterion trips twice in the soak window, P5 is rescheduled by at least one additional release.

---

## Safety Regression Test Matrix

| Test file | What it verifies | Phase that touches it |
|-----------|-----------------|------------------------|
| `backend/tests/unit/test_safety.py` | whitelist + exploit_allowlist + risk_filter unit contracts | P1 (verify unchanged), P2a (Performer dispatcher invokes them), P4 (full flow) |
| `backend/tests/unit/test_whitelist_tier_extension.py` | tier-aware whitelist (`passive_allowed`, `active_allowed`, `exploit_allowed`, `wildcard_block_regex`) | P2a, P4 |
| `backend/tests/unit/test_exploit_allowlist_tier.py` | MSF allowlist prefixes + Nuclei tag gating per tier | P2a, P4 |
| `backend/tests/unit/test_risk_tier_assignment.py` | every tool slug maps to exactly one of 4 tiers | P2a (Pentester's palette must respect tier), P4 |
| `backend/tests/unit/test_intent_vocabulary.py` | closed intent enum | P2a (Pentester emits only valid intents), P4 |
| `backend/tests/unit/test_registry_palette.py` | `palette_for_domain` returns the expected subset | P2a (Pentester `tools_allowed` derivation), P3-main (Agents tab listing), P4 |
| `backend/tests/integration/test_pipeline.py` | full v2.1 end-to-end pipeline | P1 (must remain green), P2a (Performer dispatcher must not regress), P3-main (flag-off path must remain green), P4 (flag-on path must extend, not break) |
| `backend/tests/integration/test_workflow_chat_flow.py` | v3.2.1 chat flow | P2b (LegacyPlannerShim must not regress), P4 (new path adds, OFF path identical) |
| `backend/tests/integration/test_approval_flow.py` | whitelist+approve atomicity | P4 (must hold) |
| `backend/tests/integration/test_rescope_state_machine.py` | `paused_for_rescope` transitions | P4 (must integrate with runtime delegator) |
| `backend/tests/integration/test_p4_safety_regression.py` (NEW in P4) | all 5 safety layers invoked in a full Performer flow | P4 (introduced) |
| `backend/tests/unit/test_force_approve_override.py` | override min reason length + audit | unchanged across phases |
| `backend/tests/unit/test_model_client_retries.py` | Anthropic 5xx retry behavior | unchanged; Reflector wrap reuses the same policy |

**Invariant:** every PR adds tests above the line, never below. If a phase's PR red-bars any pre-existing test, that PR is reverted, not patched-forward.

---

## Dependencies & Ordering (revision v2 — MF-1 P0 added, MF-2 P3-spike moved before P2a)

```
P0 PentAGI Analysis Reference (docs PR, 85 tests unchanged)
   │ .omc/research/pentagi-reference.md + plan §1 prose
   ▼
P1 Foundation (1 PR, 92 tests)
   │ msgchains + memory_entries + Performer skeleton + Role base
   │ + dep tuple lock + startup warm-up + msgchain disjointness
   ▼
P3-spike Streaming substrate ADR + topic filter + perf benchmark (1 PR, 95 tests)
   │ EventBus topic kwarg + ws.py topic param + ADR-001 perf gate
   │ → ADR-001 status flips to Accepted or Rejected at end of this PR
   │ NO UI consumers yet; flag still OFF
   ▼
P2a Roles & Performer engine (1 PR, 103 tests)
   │ 6 roles + tool dispatcher + Adviser + Reflector + Memorist search
   │ + no-topic-prefix invariant (test_p2a_no_topic_prefix.py, removable after spike Accepted)
   ▼
P2b AttackPlanner → Generator adaptation (1 PR, 105 tests)
   │ LegacyPlannerShim (opt-in flag); v2.1 tests untouched
   │ + pipeline-shape regression test
   ▼
P3-main /flow/:id route + 3 tabs + feature flag (1 PR, 110 tests)
   │ feature flag OFF default; deprecation banners on legacy pages
   ▼
P4 Workflow Loop (1 PR, 116 tests)
   │ AmbiguityLoop + ask_tool + Memorist auto-call + Performer wired into OrchestratorService
   ▼
P5 Deprecation (1 PR, scheduled 2 releases later, 120 tests)
   │ delete Monitor + PentestWorkflow + AgentCatalog + InteractionDashboard
```

**Hard ordering constraints (revision v2):**

- **P0 must complete before P1** (analysis decisions inform schema and dep choices in P1).
- **P1 must complete before P3-spike** (P3-spike's perf benchmark requires the new pg/embedding stack to be installable; but P3-spike does NOT depend on msgchains tables specifically).
- **P3-spike must complete before P2a** (revision v2 MF-2: Performer's tool dispatcher commits topic taxonomy via `event_bus.publish(session_id, event, topic=...)`; if substrate is rejected, P2a publish sites must rework. The interim `test_p2a_no_topic_prefix.py` invariant is a belt-and-suspenders guard that can be removed once spike is Accepted).
- **P2a must complete before P2b** (`LegacyPlannerShim` depends on `Generator`).
- **P2b before P3-main** (UI cannot mount Generator-backed chat without the shim's safety net).
- **P3-main before P4** (workflow chat must render ask-tool inline before AmbiguityLoop drives it).
- **P4 before P5** (legacy pages can't be deleted while flag-off is the production default).

**Parallelizable note (revised v2 MINOR-1):** P0 is a docs PR with no code dependency, so the implementor may *draft* P1 changes in a parallel branch — but **P0 must merge first**, and any P0 finding that contradicts a P1 decision (different embedding model, new schema field, different role inventory) forces P1's branch to rebase before opening its PR. Hard ordering above takes precedence: no P1 merge before P0 merge.

**Each phase preserves the 85-test v2.1 baseline. Cumulative new tests by phase (revision v2):** P0 0 + P1 7 + P3-spike 3 + P2a 8 + P2b 2 + P3-main 5 + P4 6 + P5 4 = **35 net new tests; final = 120 tests passing.**

---

## Open Issues for Critic (revision v2)

Status legend: **[RESOLVED]** = closed by revision v2; **[OPEN]** = still pending critic re-validation; **[DEFERRED]** = explicit v3.4+ work.

1. **[RESOLVED — MF-1]** ~~`.omc/research/` directory does not exist.~~ Addressed by adding explicit P0 phase that creates the directory and writes `pentagi-reference.md` + plan §1 prose. P0 is the first PR; P1+ depend on it.
2. **[RESOLVED — Open Issue #2 inline AC]** ~~`sentence-transformers` cold-start latency.~~ Addressed by P1 acceptance gate adding a FastAPI `startup` hook that loads the model on boot (singleton), plus `test_main_startup_warms_embedding_model.py` enforcing it. First user-facing request pays the warm-cache cost, not the 2–4s load.
3. **[RESOLVED — MF-3]** ~~`numpy<2.0` pin.~~ Addressed by locking the exact dep 4-tuple in P1's pyproject.toml modify section (`pgvector==0.3.6`, `sentence-transformers==3.3.1`, `torch==2.4.1`, `numpy>=1.26,<2.0`) plus two fall-back tuples and a P1 first-hour spike sub-task to pick the first resolving tuple. P1 acceptance gate enforces `pip install -e backend/[dev]` resolver-clean.
4. **[RESOLVED — SF-2]** ~~`PentestSession.draft_plan_json` vs `MsgChain.messages_json` overlap.~~ Addressed by P1 `test_msgchain_no_subtask_overlap.py` enforcing schema disjointness invariant.
5. **[RESOLVED — MF-4]** ~~Streaming substrate fallback threshold.~~ ADR-001 now declares three quantitative Go/No-Go thresholds (p99 ≤ 100ms @ 60 events/sec × 3 topics × 10 sessions; QueueFull drop < 0.1%; no subscriber leak). P3-spike's `test_eventbus_topics.py` measures all three; ADR flips to Accepted/Rejected in the same PR. Plus P2a `test_p2a_no_topic_prefix.py` invariant prevents pre-lock topic commitments.
6. **[RESOLVED — SF-3]** ~~Performer concurrency cap.~~ `settings.max_concurrent_performer_sessions: int = 4` added to P1 config additions; OrchestratorService.run rejects new Performer-flow sessions when at-cap.
7. **[RESOLVED — SF-5]** ~~`LegacyPlannerShim` non-determinism vs `test_pipeline.py:120` content assertion.~~ Addressed by P2b `test_pipeline_shape.py` explicit regression: the OFF path (`use_generator_role=False`) preserves v2.1 step content exactly. ON-path nondeterminism acknowledged, not asserted.
8. **[PARTIAL — SF-6 INTENT_VOCABULARY resolved]** Of the four v3.2.1 inherited open items:
   - INTENT_VOCABULARY ship list — **RESOLVED.** Confirmed in source at `backend/app/agents/intent_vocabulary.py` with 25 specs (verified by Critic in v1 review). The v3.2.1 open-questions entry can be closed.
   - Rescope decision timeout (300s default) — **OPEN.** Post-launch tuning per v3.2.1; not blocking v4.0.
   - Team-pool budget aggregation semantics — **OPEN.** Post-launch with billing telemetry; not blocking v4.0.
   - Force-approve override min reason length (32 chars) — **OPEN.** Post-launch with first-20-overrides calibration; not blocking v4.0.

**[NEW OPEN — v4.0]** the following emerged in revision v2 and remain for critic re-validation:

9. **[OPEN]** Docker image size budget. Adding torch 2.4 CPU wheel + sentence-transformers + numpy ≈ 600 MB unpacked. P1 acceptance gate accepts this; critic should sign off that the resulting image (estimated ~1.8 GB after compression for `osa-backend:v4.0` from current ~1.2 GB v3.2.1) is acceptable to ops or whether a multi-stage `--no-deps` install path should be added.
10. **[DEFERRED v3.4]** Coder/Installer/Searcher/Mentor/Assistant/Refiner/Planner/Enricher roles + Searches/VectorStore/Screenshots tabs + `guide`/`answer`/`code` memory tools + Graphiti+Neo4j stack + per-team feature flag override + browser tool + multi-LLM-provider routing — all explicit v3.4+ backlog. Each gets its own ADR before landing.

---

## Verification Plan

### Per-phase

- **P1:** `pytest -q backend/tests/`; `alembic upgrade head && alembic downgrade base && alembic upgrade head`; `docker build backend/` size check (~600MB over v3.2.1).
- **P2a:** `pytest -q backend/tests/`; manual run of `python -m app.orchestrator.performer --self-test` (smoke entry); confirm 5 safety layers visited via audit log inspection.
- **P2b:** `pytest -q backend/tests/`; `test_pipeline.py` green; toggle `use_generator_role=True` in a smoke script and confirm shape-equivalent plan output.
- **P3-spike:** `pytest -q backend/tests/`; manual `wscat -c "ws://localhost:8000/ws/sessions/{id}?topics=terminal"` confirms topic filtering; ADR doc complete.
- **P3-main:** `pytest -q backend/tests/`; `npm run build` in `frontend/`; manual flag-off smoke (all 12 pages); manual flag-on smoke (2-pane shell, tab switching, terminal stream).
- **P4:** `pytest -q backend/tests/`; e2e smoke: 1 sample target prompt → clarification → approval → exec → report; safety regression matrix green.
- **P5:** `pytest -q backend/tests/`; `npm run build`; e2e regression suite confirms removed routes 404; 14-day soak window completed.

### Cross-phase

- **Test counter:** every PR ends with `pytest -q` printing a green count ≥ the expected post-phase total in this plan.
- **Audit log diff:** every PR pre-flight runs `tests/integration/test_audit_log.py` (or equivalent) to confirm no audit action regressed.
- **Frontend bundle:** `npm run build` size delta ≤ 500KB per PR (xterm.js + react-resizable-panels accounted for in P3-main alone).
- **Manual operator checklist:** P3-main and P4 each require a sign-off on the rolled-up smoke checklist in `.omc/research/manual-smoke-v4.md` (created during P3-main).

### Final acceptance (v4.0 done) — revision v2

- All 8 PRs merged in order: **P0 → P1 → P3-spike → P2a → P2b → P3-main → P4 → P5.**
- ADR-001 status is **Accepted** (substrate go/no-go thresholds all measured-pass in P3-spike) OR **Rejected** (fall-back GraphQL path documented and shipped). Either way, ADR-001 is no longer "Proposed" at v4.0 close.
- `osa_flow_ui_enabled=true` is the production default; flag-off path remains functional for emergency rollback through one additional release after P5.
- **85 v2.1 tests + 35 v4.0 net new tests = 120 tests passing.**
- v3.2.1 open questions list updated:
  - INTENT_VOCABULARY ship list: **closed** (resolved in source).
  - Rescope decision timeout: optionally re-tune with v4.0 measured data; still post-launch.
  - Team-pool budget aggregation: still post-launch with billing telemetry.
  - Force-approve override min reason length: still post-launch with first-20-overrides calibration.
- v3.4 backlog populated with: 8 deferred roles (Coder, Installer, Searcher, Mentor, Assistant side-channel, Refiner, Planner-as-3-7-step, Enricher), 3 additional search tools (`search_guide`, `search_answer`, `search_code`), Graphiti+Neo4j stack, 3 additional right-pane tabs (Searches, Vector Store, Screenshots), browser tool + scraper service, multi-provider LLM routing (OpenAI/Gemini/Bedrock/Ollama/DeepSeek/GLM/Kimi/Qwen), per-team feature-flag override, Monaco editor for in-flow artifact viewing, raw-shell `terminal` tool for Coder/Installer roles with separate safety re-validation.

---

## Appendix: Inherited from v3.2.1 (NOT amended by v4.0)

The following v3.2.1 sections remain authoritative; v4.0 does not duplicate them:

- §1 Phase 0 Foundations (data model, model components, settings) — `pentest_sessions` columns, `workflow_messages`, `rescope_approvals`, `ModelSelector`, `Pricing`, `BudgetGuard`, `ModelClient`, `claude-sonnet-4-6` default.
- §2 Tool Catalog Expansion — Claude-OSINT hybrid integration, knowledge_loader SHA verification, `osa-passive-recon:latest` multi-entrypoint image.
- §3 Domain Agents Catalog — 8 domain agents (Web/Network/Cloud×3/Mobile/API/OSINT/AI), in-code registry under `backend/app/agents/domains/__init__.py`.
- §4 Launch Pentest Session Flow — chat→draft→interview→review→approve state machine (v4.0 extends this with AmbiguityLoop runtime delegator in P4 only).
- §5 Discovered-target Rescope — `paused_for_rescope` state + `RescopeApproval` audit trail (v4.0 P4 integrates with Pentester runtime delegation, does not redesign).
- §6 Safety Chain — `whitelist → exploit_allowlist → risk_filter → egress_monitor → kill_switch` invariant.
- §7 Observability — Prometheus metrics, Grafana dashboards, structured audit log actions (v4.0 adds `msgchain_started`, `msgchain_ended`, `role_retry`, `adviser_injected`, `memorist_auto_called`).
- §8 RBAC, single uvicorn worker, AES-GCM credentials, all-in-one MVP.

v3.2.1 governs in all conflicts on the above sections. v4.0 amends only the 6 deep-interview components.
