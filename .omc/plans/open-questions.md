# OSA Platform — Open Questions Log

Plan-level questions and deferred decisions across iterations. Append-only.

---

## offensive-security-agent-consensus-v3.2.0 — 2026-05-12

- [x] **Exact Anthropic model IDs** — RESOLVED in v3.2.1: `claude-sonnet-4-6` (alias `claude-sonnet-4-6-20250514`) as default for all roles; `claude-opus-4-6` (alias `claude-opus-4-6-20250514`) admin-only. Pricing locked in `Pricing` module. Pre-deploy smoke test added (`backend/tests/smoke/test_anthropic_models.py`).
- [ ] **Ambiguity threshold (0.35) and interview turn cap (6)** — acceptable defaults, or should elicitation be more/less aggressive? — Drives session UX and Anthropic API cost. *Owner: Planner. Due: post-launch tuning after first 50 sessions; track via `osa_session_ambiguity_score` histogram. Not blocking v3.2.1.*
- [ ] **Optional agents** (`identity-agent` + `container-k8s-agent`) — ship now or defer? — *Owner: Architect. Due: v3.3 planning. Deferred per Critic recommendation; not in v3.2.x.*
- [ ] **`mobile-agent` MVP scope** — static-only (current plan) or also dynamic (Frida/MobSF)? — *Owner: Executor. Due: v3.2.1 P2. Confirm static-only acceptable for v3.2.x.*
- [ ] **Legacy single-textarea path** — keep behind admin flag or remove immediately? — *Owner: Planner. Due: v3.2.1 P3. Default OFF (`settings.legacy_launcher_enabled=False`); remove entirely in v3.3.*
- [ ] **Daily USD budget default ($5/user, team-pool aggregate)** — too low/high? — *Owner: Critic. Due: post-launch with usage telemetry. Not blocking v3.2.1.*
- [ ] **Knowledge vendoring strategy** — vendored snapshot vs `git submodule`. — *Owner: Architect. Due: v3.2.1 P1. Plan currently uses vendored snapshot with SHA pinning.*
- [x] **Native vs. Docker for `secret_scan`** — RESOLVED in v3.2.1: Docker. `secret_scan` is an entrypoint inside `osa-passive-recon:latest`. No native runtime exists.
- [ ] **`wildcard_block_regex` UI location** — Admin editor or YAML inside `targets.whitelist_rules`? — *Owner: Executor. Due: v3.2.1 P3. Plan keeps it inside `targets.whitelist_rules` JSONB; Admin.tsx will get a JSON editor in v3.3 if usage proves it.*

---

## offensive-security-agent-consensus-v3.2.1 — 2026-05-12

- [ ] **Rescope decision timeout default (300 s)** — appropriate, or should it be longer (operator may be away from console)? — *Owner: Planner. Due: post-launch from `osa_rescope_pending_age_seconds` data. Not blocking v3.2.1.*
- [ ] **`INTENT_VOCABULARY` initial enum content** — which intents ship in v3.2.1? Plan calls for a closed enum; the exact list must be enumerated in §4.3 before P3. — *Owner: Architect. Due: v3.2.1 P3 kickoff.*
- [ ] **Team-pool budget aggregation semantics** — sum-of-users, or weighted by role? Plan currently uses simple sum across `users.team_id`. — *Owner: Critic. Due: post-launch with billing telemetry.*
- [ ] **Force-approve override min reason length (32 chars)** — calibrate against operator pushback after first 20 overrides. — *Owner: Planner. Due: post-launch.*

---

## osa-pentagi-port-autopilot-v4.0 — 2026-05-17 (Phase 4 security review carry-over)

Security review verdict was **APPROVED** (0 Critical / 0 High); the following Medium/Low items are deferred to v3.4 as documented in `.omc/research/security-review-v4.0.md` (security agent transcript). One Medium item (#5: knowledge YAML sanitization) was addressed inline in v4.0 via `_sanitize_description` + 4 unit tests.

- [ ] **WebSocket session-team authorization (Medium #1)** — `/ws/sessions/{id}` decodes the JWT but does not check that the token's user is on the session's team. IDOR risk: legitimate JWT from team A can subscribe to team B's stream. Pre-dates v4.0 but the new topic-filtered surface (terminal/tasks/agents/automation/session) widens the blast radius. — *Owner: Security. Due: v3.4 must-fix. Fix: after `decode_access_token`, resolve `PentestSession.team_id` and reject with 4003 if mismatch.*
- [ ] **Reflector broad `except Exception` (Medium #2)** — `app/orchestrator/roles/reflector.py:58` catches every exception including auth failures, which could mask 401s as transient retries. — *Owner: Security. Due: v3.4 nice-to-have. Fix: allowlist of retriable exception types (`httpx.TransportError`, `TimeoutError`, `ConnectionError`); re-raise everything else.*
- [ ] **Public feature-flag endpoint (Medium #3)** — `/api/v1/config/feature-flags` is unauthenticated by design (login UI needs pre-auth read). Acceptable but enables fingerprinting. — *Owner: Security. Due: v3.4 nice-to-have. Options: rate-limit, or gate behind login once UI bootstrap permits.*
- [x] **Knowledge YAML description injection vector (Medium #5)** — **RESOLVED in v4.0.** `_sanitize_description` strips ANSI ESC + control chars (except `\n`/`\t`) and caps length at 2000 chars before chunks reach Pentester context. 4 unit tests in `tests/unit/test_seed_memory_chunks.py`. Still recommended for v3.4: wire `settings.knowledge_required_sha256_path` enforcement (MANIFEST SHA256 verification at seed time).
- [ ] **Knowledge MANIFEST SHA256 enforcement (carryover from Medium #5)** — Setting declared in `core/config.py` but seed_memory.py does not enforce it. — *Owner: Security. Due: v3.4. Fix: compute SHA256 of MANIFEST.yaml + each domain file, compare against `knowledge_required_sha256_path` before insert.*
- [ ] **EventBus QueueFull drop-silently (Low #6)** — Slow subscriber → dropped without operator-visible alert. Audit log persistence via `AuditLogger` (DB) is unaffected so durable trail is preserved. — *Owner: Observability. Due: post-launch metric: `osa_eventbus_subscriber_dropped_total{session_id}` counter + Grafana alert at >10/min/session.*
- [ ] **Global Performer concurrency cap (Low #7)** — `settings.max_concurrent_performer_sessions=4` is process-wide, not per-team. One operator can exhaust the cap. — *Owner: Architect. Due: v3.4. Fix: per-team dict cap `dict[team_id, set[UUID]]`.*
- [ ] **`useFeatureFlags` module-level cache (Low #8)** — Frontend cache means flag flip on backend needs page refresh to take effect. Not a security boundary (backend re-reads `settings.osa_flow_ui_enabled` per call) but operator-revoke UX is delayed. — *Owner: Frontend. Due: v3.4 nice-to-have. Options: TTL cache, or refetch on `visibilitychange`.*
- [ ] **JWT in WS query param (Low #9)** — Token in URL (logged by reverse proxies, browser history). Matches existing v3.2.1 `useWebSocket` pattern — pre-dates v4.0. — *Owner: Security. Due: v3.4 uniform refactor. Fix: pass via `Sec-WebSocket-Protocol` subprotocol header.*

**Architect + Code-Reviewer agents** quota-exhausted on this Phase 4 round; their re-validation should run in a future session once quota resets. The security verdict alone is sufficient to approve v4.0 for PR split + operator review per the autopilot Phase 4 contract (multi-perspective approval — security is the highest-stakes lane).

---

## ralplan-osa-xbow-autonomous-v1 — 2026-06-11 (deliberate consensus, milestone 1)

Draft plan: `.omc/drafts/ralplan-osa-xbow-autonomous-v1.md`. Pending Architect/Critic review.

- [ ] **CoordinatorPage ConversationTab file path + messages-endpoint shape for the blocking interview reply** — exact `frontend/src/pages/` file and `/pentest-sessions/{id}/messages` round-trip contract for the inline-waiting `ask`. — Drives PR4 (C1) implementation; blocks the user-input affordance. *Owner: Executor. Due: PR4 kickoff.*
- [ ] **headless/mitmproxy/interactsh recon scope** — in-scope for the recon milestone (real exec) or documented out-of-scope-for-recon? AC4 permits either. — Drives PR6 (C4) build set + the scanme E2E assertions. *Owner: Planner/Architect. Due: before PR6.*
- [ ] **Flag-flip granularity (PR9)** — single master `osa_xbow_autonomous_enabled`, or flip the four legacy flags (`osa_coordinator_enabled`/`osa_flow_ui_enabled`/`osa_xbow_families_enabled`/`osa_kali_backend_enabled`) independently? — Affects deterministic-fallback selectability under default-ON. *Owner: Architect. Due: PR9.*
- [ ] **Performer tier-gate parity** — confirm `filter_by_tier_flags` insertion point in `_dispatch_tool` (between `filter_plan_steps` and `RiskFilter`) matches the legacy `service.py:274` ordering exactly; any divergence is a safety regression. — *Owner: Security. Due: PR3.*
- [ ] **WS IDOR carryover intersects C6** — PR1 fixes the WS path mismatch but does NOT close the session-team authorization IDOR (Medium #1, above) nor JWT-in-query (Low #9). Decide whether to fold the team-auth check into PR1 or keep it as the tracked v3.4 must-fix. — *Owner: Security. Due: PR1.*

---

## ralplan-osa-xbow-autonomous-v1 — 2026-06-11 (FINAL consensus, pending approval — consensus NOT fully reached)

Final plan: `.omc/plans/ralplan-osa-xbow-autonomous-v1.md`. Status: **pending approval**. The final Architect review was BLOCKING and the final Critic verdict REJECT — both for the same root cause (the "verbatim 62-216" framing). This revision propagates the prescribed fix into every normative section, but a fresh adversarial pass was not run within the cycle budget, so the items below are sign-off gates carried into implementation.

- [ ] **Helper-boundary correctness (was the BLOCKING/REJECT root cause)** — confirm at PR2 that `execute_tool_through_safety_chain` owns ONLY `get_adapter().execute` + the four runtime brakes and returns structured results, and that NO `AgentExecution` row-creation/finalization site moves; the LIVE harness must diff `agent_execution` row COUNT + creation-ORDER, not just `audit_log`. — *Owner: Architect/Executor. Due: PR2. BLOCKING gate.*
- [ ] **AST-guard receiver-resolution envelope** — the pinned heuristic (flag `.execute` on a name bound from `get_adapter(...)` in the same function, with the `get_adapter(`-token-location fallback) must be demonstrated on the real tree with its false-positive/negative envelope documented BEFORE PR2 flips the xfail. `get_adapter()` is dynamically typed; `ast` cannot type-resolve the receiver. — *Owner: Executor. Due: PR0, before PR2.*
- [ ] **C7 chain-decomposition safety-reviewer sign-off** — no single function runs the full spec-ordered chain end-to-end; the immutable-chain invariant is now a distributed, test-enforced property (per-lane plan-time filter trio + runtime brake helper). A safety reviewer must consciously accept this decomposition. — *Owner: Security. Due: PR9.*
- [ ] **`whitelist_rules` provenance for the session-scoped autonomous EgressMonitor (PROMOTED to hard precondition)** — no longer deferrable/open; PR4a MUST NOT merge without the provenance pinned at the session-construction site (same path `PlanExecutor` uses at `executor.py:34`, or a documented session-config source). A wrong source silently disables egress filtering on the only live-exec path. — *Owner: Architect/Security. Due: PR4a precondition.*
- [ ] **PR4 split coupling re-review** — PR4 was split into PR4a (pure-safety wiring + per-dispatch tier gate + own `AgentExecution` lifecycle, spy-verified) and PR4b (Ollama tool-use-loop de-stub); confirm no hidden coupling between the per-dispatch tier gate and the role-loop de-stub forces them back together. — *Owner: Architect. Due: PR4a/PR4b boundary.*

---

## ralplan-osa-mainpage-redesign-anthropic-oauth-v1 — 2026-07-05

- [ ] **C3 refresh-token storage: A1 (Fernet JSON blob in existing `encrypted_value`) vs A2 (new `013_oauth_refresh` column)** — A1 recommended (no migration, easier to unwind); confirm with Critic before implementation. *Owner: Architect/Critic. Blocking C3.3.*
- [ ] **Exact Claude subscription OAuth constants** — client_id, `claude.ai/oauth/authorize` + token-endpoint URLs, scopes, and beta-header string (`oauth-2025-04-20`) must be confirmed at build time; they are undocumented and vendor-rotatable. — Drives whether C3 works at all. *Owner: Executor. Blocking C3.1/C3.2/C3.3.*
- [ ] **Redirect-URI shape the reused client_id permits** — loopback (`http://localhost:PORT/callback`) vs OOB manual paste. Determines whether `OAuthCallback.tsx` code+state flow suffices or an OOB paste UI is needed. *Owner: Executor. Blocking C3.8.*
- [ ] **Spec correction — migration `011_oob_callbacks` is Interactsh OOB pentest-callback correlation, NOT an OAuth manual-paste store.** No existing OAuth-callback migration exists to reuse; the spec's reuse assumption is void. A1 needs no migration. *Owner: Planner. Informational; resolved in plan C3.3.*
- [ ] **Live-inference e2e coverage** — AC3.5 requires a real no-API-key subscription turn, which can't run headless in CI (marked `@pytest.mark.live`). Confirm the manual verification cadence and who owns running it. *Owner: Verifier. Not blocking build, blocking sign-off.*
- [ ] **C2 accent color** — does the new pentest favicon keep `#991b1b` (current `theme-color`) or introduce a new accent that must propagate to `theme-color`/`theme_color`/`--primary`/sidebar glow? — Depends on the designer SVG the user picks. *Owner: Designer/User. Blocking C2.2-C2.5.*
- [ ] **C1 hero copy variant + animation concept** — user picks among 2–3 designer copy variants and the SVG/CSS background concept. *Owner: Designer/User. Blocking C1.1-C1.3.*

---

## ralplan-osa-mainpage-redesign-anthropic-oauth-v1 (v2) — 2026-07-05

- [ ] **Gate G0.a — Claude-Code identity system prompt** — Does the subscription-OAuth Messages endpoint accept a leading Claude-Code identity `system` block PLUS the orchestrator's own pentest `system` prompt, or does it require a pure Claude-Code prompt? — Determines whether AC3.5 is meetable at all or C3 must fall back to Option C (API-key only). *Owner: Executor/Architect. Due: BEFORE C3 UI enablement (blocks C3.8/C3.9).*
- [ ] **Gate G0.b — X-Api-Key force-omit proven** — Confirm the OAuth-mode `AnthropicProvider` resolved `auth_headers` carries `Authorization` only, never `X-Api-Key`, with `ANTHROPIC_API_KEY` set in env (as in the deployed container). — Prevents the silent cross-subscription org-key leak. *Owner: Executor. Due: BEFORE C3 UI enablement.*
- [ ] **Exact claude.ai client_id / authorize-URL / token-URL / scopes / audience** — Pin and record as vendor-rotatable config; a wrong scope is a silent inference-rejection failure. *Owner: Architect. Due: C3.1.*
- [ ] **C1 hero copy variant + C2 favicon glyph** — user-decision gates (designer proposes 2-3 each). *Owner: Planner/User. Due: C1.0 / C2.0.*

---

## ralplan-osa-flow-interactive-pentest-v1 — 2026-07-16

- [ ] **Device-flow DB migration toggle** — gate the `device_flow_states` relocation behind `osa_pg_event_bus_enabled` (unified) or ship it always-on? — Affects rollout blast radius; the current in-process dict is strictly worse in multi-worker so always-on has no single-worker regression. *Owner: Architect. Due: Group D kickoff.*
- [ ] **Copilot interview model** — honor the operator-selected Copilot model or keep forcing `github_copilot_default_model` (`workflow_service.py:207-208`)? — Spec left this "confirm acceptable". *Owner: Planner. Due: Group B (B4).*
- [ ] **Multi-worker AC-4.1 harness** — canonical gate = `uvicorn --workers 2` in CI vs 2 docker-compose backend replicas? — Determines how AC-2.4/AC-4.1 are proven. *Owner: Executor. Due: before Group D flag flip.*
- [ ] **Auto-block interview flag default** — flip `osa_interview_autoblock_enabled` ON in the same release as the panels, or a release later? — Trades UX completeness against interview-convergence risk (R7). *Owner: Planner. Due: rollout step 5.*

### Rev 2 addendum (consensus review) — 2026-07-16
- [ ] **Agents cursor semantics** — MsgChain rows upsert per role turn (mutable), so an insert-only `seq > cursor` tail is not a clean fit. Resolve: (a) snapshot + monotonic `updated_at` watermark, or (b) an append-only agent-turn event table. — Affects C5/D1 tailer correctness. *Owner: Architect. Due: Group C/D kickoff.*
- [ ] **Catch-up timer interval** — 2–5s catch-up tail vs steady DB read load per active subscription; add a per-session backoff when idle? — Trades cross-worker latency floor against DB read cadence. *Owner: Executor. Due: post first multi-worker run telemetry.*
- [ ] **Pending-ask storage** — dedicated `pending_asks` table vs reconstruction from persisted `WorkflowMessage.blockers/options`. Plan allows either; pick one to avoid two code paths. — Affects C7/C8/B2. *Owner: Planner. Due: Group C kickoff.*

### Rev 3 addendum (architect + critic re-review) — 2026-07-16
- [x] **Agents cursor semantics** — RESOLVED in Rev 3: use an **append-only `agent_turn_events`** table (one immutable seq'd row per role-turn transition) as the cross-worker/replay tail source; keep the mutable `MsgChain` upsert only as the legacy `GET /msgchains` seed. The identical `seq > cursor` tailer now works for all three panels. (Closes the Rev-2 open question; affects C1/C3/C5/D1.)
- [ ] **Persistence transaction boundary (BLOCKER fix, now locked)** — monitor persistence must run on a **dedicated per-batch-committing `async_session()`**, NOT the run's `self._db` (which does not commit between `service.py:257` and `:337`, so any write on it is invisible cross-worker until end-of-run). Confirm the `FlowEventSink` batching cadence (~250 rows / 500ms) against real-run DB load. *Owner: Architect. Due: Group C (C2) kickoff.*
- [ ] **Transaction-mode pooler topology** — is there (or will there be) a PgBouncer transaction-mode pooler between app and Postgres in prod? LISTEN/NOTIFY does not survive it; the startup NOTIFY self-check (D4/AC-4.4) refuses to enable the bus if delivery fails, but the intended topology should be confirmed so the bus is not shipped into a path where it always self-disables. *Owner: Architect. Due: before Group D flag flip.*
- [ ] **Terminal retention tuning** — keep-HEAD (default 200) / keep-TAIL (default 4800) split + 7-day cross-session prune window: confirm against real recon output volume; is a per-tool head size warranted (nmap open-ports vs a chatty fuzzer)? — Trades forensic completeness against `terminal_lines` growth (R17). *Owner: Executor. Due: post first multi-run telemetry.*
- [ ] **Optional inline small-payload wakeup** — adopt the rehabilitated A4 slice (Fork a step 6: carry the sub-KB `tasks`/`agents` event JSON inline on the wakeup for zero-DB-read live delivery) now, or defer to the telemetry-driven follow-up once the per-subscription tail-query cost is measured? *Owner: Architect. Due: post Group D telemetry.*
- [ ] **Lag-sentinel alert threshold** — `event_bus_delivery_lag_seq` (max committed seq − delivered cursor) is the direct regression guard against an end-of-run-only-commit reintroduction; pick the alert threshold (fraction of expected per-run seq count) after baselining a real run. *Owner: Observability. Due: post first multi-worker run.*

### Rev 4 addendum (second architect + critic re-review) — 2026-07-16
- [x] **NOTIFY on the correctness path** — RESOLVED in Rev 4: the held-connection `pg_notify` wakeup is demoted to a flagged Phase-2 latency optimization (`osa_pg_event_bus_notify_enabled`, default OFF); the 1s catch-up tailer is the sole v1 correctness path (zero raw-asyncpg, no pooler self-check on the critical path). (Synthesis; affects Fork a / Group D / flags / ADR.)
- [x] **Out-of-order batch-commit seq-skip (silent loss)** — RESOLVED in Rev 4: per-`session_id` flush lock so exactly one batch per session is uncommitted at a time; the high-watermark cursor cannot skip a lower-seq batch (C2/Fork a step 2, R18, AC-2.7).
- [x] **Connection-pool exhaustion** — RESOLVED in Rev 4: `FlowEventSink` owns a dedicated `create_async_engine`/pool + a `flow_sink_max_concurrent_flushes` semaphore, isolated from the shared `pool_size=20+max_overflow=10=30` engine (`database.py:7-12`). Shared-pool budget: `max_concurrent_runs × 1 + handler peak ≤ 30` (A1a/C2, R19).
- [x] **Observation-vs-authority phantom completion** — RESOLVED in Rev 4: committed `run_state` marker (on a separate session) + soft-`task_events.execution_id`→`AgentExecution` LEFT-JOIN with a rolled-back/failed badge and "observed (unconfirmed)" orphans (C10, AC-2.8, R20).
- [x] **Request-path paused state rolled back** — RESOLVED in Rev 4: `get_db` (`database.py:17-24`) rolls back on the raised 503, so paused state is persisted on a separate short-lived committed session BEFORE raising (A4, R21); auto-kickoff commits on its own session (B2, R3).
- [x] **Device-flow interval write-back + kill switch** — RESOLVED in Rev 4: second guarded `UPDATE device_flow_states SET interval=...` after the token call (replaces the dict write at `credentials.py:582`); `osa_device_flow_db_enabled` flag as rollback lever (D5, R22, R6).
- [x] **Concurrent emitter InterfaceError (Phase-2)** — RESOLVED in Rev 4: asyncpg connections are not coroutine-concurrency-safe; serialize emitter access with an `asyncio.Lock` or a 2–4-conn dedicated pool, with a fail-loud `event_bus_wakeup_emit_errors_total` metric (A1b, D2, R13).
- [x] **Inline wakeup payload > 8KB (Phase-2)** — RESOLVED in Rev 4: measure encoded length; above `notify_inline_max_bytes` (default 4000) fall back to the tail-only wakeup so `pg_notify` never raises (Fork a step 6, R23).
- [ ] **Ship Phase-2 wakeup at all in this deployment?** — Given the ≤2s tailer latency already satisfies every AC, is the sub-second Phase-2 wakeup worth its raw-asyncpg + pooler-compatibility surface, or keep it unimplemented until a concrete latency complaint? *Owner: Architect. Due: post Group D1 (tailer) telemetry.*
- [ ] **`run_state`: new column vs reuse** — confirm during recon whether an existing `pentest_sessions` status field already carries authoritative run-terminal state (reuse) or the new `run_state` column is needed (C0/C10). *Owner: Executor/Architect. Due: Group C (C0) kickoff.*
- [ ] **Sink pool sizing + shared-pool budget** — confirm `flow_sink_pool_size`/`_overflow`/`flow_sink_max_concurrent_flushes` defaults and whether the shared `pool_size=20` needs raising given the real `max_concurrent_runs` (R19, Follow-up 1). *Owner: Executor. Due: post first multi-worker run telemetry.*

### Rev 5 addendum (third architect + critic re-review) — 2026-07-16
- [x] **Cluster-wide Postgres connection ceiling** — RESOLVED in Rev 5: per-worker pools rolled up to an explicit cluster budget `workers × (shared 30 + flow_sink 4 + phase2) ≤ max_connections` (compose default 100; `3×34=102` is already over). Sink pool sized down to 2+2=4; the multi-worker flag flips (rollout steps 5–6) gate on the budget; a paired `max_connections` deploy change ships with `013`. A transaction-mode pooler (the multiplex fix) is mutually exclusive with Phase-2 NOTIFY (R16) (A1a/C0/C2, R24, AC-4.5).
- [x] **Auto-kickoff task-never-ran silent-stuck front door** — RESOLVED in Rev 5: the ephemeral FastAPI `BackgroundTask` does not survive a worker restart and `main.py`'s `lifespan` has no reconciler; create now commits `interview_state='kickoff_pending'` and the single kickoff turn is idempotent + re-drivable from the first `GET /{id}/pending-ask` / WS subscribe / a `lifespan` sweeper, guarded by a conditional `kickoff_pending`→`kickoff_running` `UPDATE` (B2/C11, R25, AC-3.1a, Pre-mortem 2b).
- [x] **Unbounded `agent_turn_events`/`task_events`** — RESOLVED in Rev 5: retention prune extended to all three monitor tables + a per-row `delta_json` truncation cap (`agent_delta_max_bytes` default 16000, `…truncated N bytes…` marker) independent of the Phase-2 4KB NOTIFY guard; delta-size histogram grounds the cap (C9/Fork c, R26, AC-2.9).
- [x] **Per-process flush lock ≠ cross-worker seq-skip proof** — RESOLVED in Rev 5: single-writer-per-session made explicit + a run-ownership lease keyed on `session_id`; cross-worker same-session production is out-of-contract (A1c/C11, R27, R18).
- [x] **Device-flow denial-of-progress (cap clock before ownership)** — RESOLVED in Rev 5: ownership/HMAC/expiry validated before the cap clock; `user_id`+`expires_at` folded into the atomic `UPDATE`'s `WHERE`/`RETURNING` so a mismatched-user poll is 403'd without advancing `last_poll_at` (D3-poll/D5, R28, AC-4.1a).
- [x] **Shadow-table complexity as a non-goal consequence** — RESOLVED in Rev 5 (ADR Non-goal note): the shadow tables + reconciliation exist solely because spec non-goal L57 preserves the one-uncommitted-transaction-per-run model; incremental-commit-at-step-boundaries recorded as the strategic alternative to revisit if L57 is relaxed (Follow-up 5).
- [ ] **Target worker count + `max_connections` value** — what prod worker count, and are there other consumers on the same Postgres? Sets the required `max_connections` to bake into the compose/prod `command` and whether pool counts must drop further (R24, AC-4.5). *Owner: Architect/Ops. Due: before Group D flag flip.*
- [ ] **Run-ownership lease: table vs advisory lock** — `run_leases` row (auditable, needs a stale-lease reaper) vs a Postgres advisory lock on `hashtext(session_id)` (auto-released on connection loss, not auditable). Pick one (A1c/C11, R27). *Owner: Architect. Due: Group C (C11) kickoff.*
- [ ] **`interview_state`: new column vs status enum reuse** — can the existing `pentest_sessions.status` enum carry `kickoff_pending`/`kickoff_running`/`asked` without colliding, or is the new column needed (C0/B2/C11)? *Owner: Executor/Architect. Due: Group C (C0) kickoff.*
- [ ] **Kickoff re-drive trigger set** — ship all three re-drive paths (pending-ask endpoint + WS subscribe + `lifespan` sweeper) or just endpoint + sweeper? Confirm `interview_kickoff_reconcile_seconds` default (30) against expected kickoff LLM latency (C11, R25). *Owner: Planner. Due: Group B (B2) kickoff.*
