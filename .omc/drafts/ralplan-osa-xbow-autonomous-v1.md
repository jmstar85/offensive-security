# RALPLAN-DR: OSA → XBOW Autonomous Pentest — Milestone 1 (single-safe-target E2E)

- **Status:** pending approval (revised after Architect + Critic consensus round 2 — all BLOCKING/REJECT items addressed via the two-seam synthesis)
- **Branch:** `feat/kali-coexistence-v1` (cut PR branches `feat/xbow-autonomous-*` off this)
- **Mode:** DELIBERATE consensus (RALPLAN-DR) — high-risk: live autonomous tool execution against a real network target.
- **Source spec:** `.omc/specs/deep-interview-osa-xbow-autonomous-pentest.md` (ambiguity 14%, PASSED)
- **Milestone target:** a single safe target — `scanme.nmap.org` — runs an end-to-end autonomous loop with REAL Docker recon-tool execution, Ollama-driven agent reasoning, recon-autonomous / exploit-human-gated, additive over the preserved deterministic/no-LLM fallback lane.

> **Revision note (consensus round 2 — adopts the two-seam synthesis).** The prior draft asserted a single monolithic `execute_tool_through_safety_chain` helper that ran BOTH the plan-time filter trio (`filter_plan_steps → filter_by_tier_flags → RiskFilter`) AND the runtime brakes per step. The Architect and Critic both proved this is **incompatible with byte-identical replay**: the filter trio runs ONCE PER PLAN in `OrchestratorService.run` (`service.py:268` filter_plan_steps, `:274` filter_by_tier_flags, `:291` RiskFilter) and emits **plan-level** audit rows before the executor loop (`steps_blocked` summary at `service.py:294-301`; per-slug `persist_kali_blocked_steps` at `service.py:282-288`), whereas `PlanExecutor.execute` (`executor.py:37-225`) loops per-step and runs ONLY the runtime brakes (egress `:77-81`, kill-reg `:68-74`, rescope `:167-206`, shim-audit `:103-133`) and **never calls the filter trio**. Folding the trio into a per-step helper would move filtering from plan-cardinality to step-cardinality, changing which audit rows are emitted, in what order, and how many — a byte-identical violation.
>
> **The fix (now adopted): split the choke point into TWO structurally-distinct seams.**
> 1. **Plan-time filtering stays where it is, at its current cardinality.** `filter_plan_steps → filter_by_tier_flags → RiskFilter` remains in `OrchestratorService.run` (`service.py:268-291`) for the deterministic lane (unchanged ⇒ byte-identical). For the autonomous lane the SAME trio runs per-dispatch in `_dispatch_tool` (`performer.py:295-309` already does `filter_plan_steps` + `RiskFilter`; PR4 ADDS `filter_by_tier_flags(session.approval_flags)` there).
> 2. **Only the RUNTIME-execution envelope becomes the shared helper.** `execute_tool_through_safety_chain` owns `adapter.execute` + per-log egress + container-kill registration + rescope-harvest/`pause_for_rescope` + shim-block audit — i.e. the `executor.py:62-216` body **moved verbatim** (not re-cardinalized). BOTH `PlanExecutor.execute` and `_dispatch_tool` call it for the actual container run.
>
> The structural AST guard therefore scopes its invariant to `adapter.execute` appearing ONLY inside the runtime helper — achievable byte-identically because the runtime brake CODE is moved verbatim. The tier gate is a documented **per-lane** invariant (plan-time in `service.py:274` for deterministic; per-dispatch in `_dispatch_tool` for autonomous), enforced by tests, NOT by physical co-location in the runtime helper. This removes the only mechanism by which the refactor could drift replay while still delivering the real safety goal: no live container exec without the full runtime brake envelope.

---

## 1. RALPLAN-DR Summary

### Principles
1. **Additive over rip-and-replace.** Every new autonomous behavior lands behind a default-OFF flag beside the existing deterministic lane; the deterministic Coordinator + legacy `PlanExecutor` + no-LLM demo lane stay byte-identical-green throughout. The byte-identical guarantee has TWO distinct enforcement surfaces, and the plan does NOT conflate them: (a) the **static fixture comparator** (`tests/_regression/v11_comparator.py`: `compare_audit_log_rows:117`, `compare_agent_execution_rows:170`, `assert_no_coordinator_in_saved_workflow_trace:207`), today exercised only by `tests/regression/test_v11_byte_identical.py`, which loads `golden_*.json` and compares them to themselves/poisoned copies — it **never runs `PlanExecutor.execute` or `OrchestratorService.run`** and therefore **cannot, by itself, catch a `PlanExecutor` refactor drift**; and (b) a NEW **live differential harness** (`tests/regression/test_planexecutor_refactor_byte_identical.py`, built in PR0) that runs the real saved-workflow pipeline and feeds its emitted rows into the same comparator functions. Critically, the agent_execution comparison (`v11_comparator.py:170-204`) is **NOT** covered by `EXCLUDED_AUDIT_PREFIXES` (which only filters `audit_log` actions via `is_excluded_action`); `agent_execution` rows are the real replay-exposure surface and are protected ONLY by flag-gating, asserted by `test_deterministic_lane_unchanged_with_xbow_off.py`. (D5)
2. **The full runtime brake envelope is a hard invariant, enforced structurally through ONE shared runtime helper — NOT the plan-time filters.** No autonomous tool call reaches Docker except through the shared `execute_tool_through_safety_chain` helper, which owns the live runtime brakes that today live ONLY in `PlanExecutor.execute`: `adapter.execute` through shims/IMAGE_REGEX, per-log `EgressMonitor.monitor_log_line` + `KillSwitch`, container-ID kill-switch registration, rescope-on-new-hosts harvest + `RescopeService.pause_for_rescope`, and `SafetyViolation`/`persist_kali_shim_block` audit (`executor.py:62-216`, moved verbatim). The plan-time filter trio (`filter_plan_steps → filter_by_tier_flags → RiskFilter`) is **NOT** inside this helper — it stays at plan-time cardinality per lane (Principle 3). A NEW structural guard (`tests/ast/test_adapter_execute_only_via_safety_helper.py`) asserts `adapter.execute(...)` is invoked only inside the runtime helper. `tests/ast/test_no_direct_backend_calls.py` stays green. (D4, C7)
3. **Tier gate is a per-lane invariant with a single source of truth per lane — NOT inside the runtime helper.** Deterministic lane: the tier gate stays at `service.py:274` (`filter_by_tier_flags`), unchanged. Autonomous lane: the tier gate runs per-dispatch inside `_dispatch_tool` against `session.approval_flags`, added alongside the existing `filter_plan_steps` + `RiskFilter` (`performer.py:295-309`). `PlanExecutor` does **not** gain a redundant second tier-gate pass (which would itself perturb the deterministic audit trace). Recon is autonomous; any active-exploit-tier step blocks on `session.approval_flags`; a new-host discovery on the autonomous lane triggers `RescopeService.pause_for_rescope` (inside the runtime helper) and halts on pending approval, exactly as the legacy lane does. (D4)
4. **Local Ollama only; reuse the client object — the agentic loop is net-new.** All agent reasoning routes through the already-built `OllamaClient` (`ollama_client.py`, `ModelClient.send`-compatible, `format="json"`, strips `<think>`, raises `ModelUnreachable`). Note explicitly: `OllamaClient.send` is a **single-shot `format=json` request/response with no native tool-call structure and no loop**; the envelope-driven tool-use loop (emit JSON tool envelope → `delegate_tool_call` → read result → iterate to done/cap) is **net-new machinery layered on single-shot calls**. No new cloud-LLM dependency. (D3)
5. **Land low-risk and invariant-preserving first.** CI guards, the live differential harness, the WS-path fix (C6), the runtime-envelope spy harness, and the runtime-helper refactor land before any new autonomous behavior, so each subsequent PR is verified against a green, observable baseline with a single audited runtime choke point already in place.

### Decision Drivers (top 3)
1. **Safety regression risk dominates — and the dominant facet is runtime brake-parity, not the plan-time filters.** The platform's only real asset today is the safety control-plane. The worst outcome is **real Docker exec against scanme with the egress monitor, kill-switch registration, and rescope pause silently absent** — four of the five live runtime brakes live ONLY in `PlanExecutor.execute`, none in `_dispatch_tool`. `runtime_delegator.py:16-17` literally advertises `tier_gating + egress_monitor + RescopeService` as the brakes on a path that has none of them. Drives the shared RUNTIME helper + the full-envelope spy harness + the structural AST guard.
2. **The autonomous core is ~85% unbuilt but the scaffolding is real.** `Performer.run_session`, `_dispatch_tool` (partial chain), `OllamaClient`, role classes, and `_materialize_families` all exist with zero/partial live callers. Drives a wiring-and-de-stub plan, not a greenfield build.
3. **"Done" = real Docker exec against scanme, not fixtures.** `_dispatch_tool` step 5–7 (`adapter.execute`) is explicitly deferred (`performer.py:320-323`, "wired in P4"). The real-exec bridge — routed through the shared runtime helper — is the milestone's crux and gates the flag flip.

### Viable Options

**Option A — Wire-and-de-stub the existing scaffolding, with TWO safety seams: per-lane plan-time filters + ONE shared runtime helper (CHOSEN).**
Reuse `Performer.run_session`, `_dispatch_tool`, `runtime_delegator.delegate_tool_call`, `OllamaClient`, the role classes, and `_materialize_families`; inject Ollama into the role loops; **extract a single `execute_tool_through_safety_chain` runtime helper (the `executor.py:62-216` body, moved verbatim) that both `PlanExecutor.execute` and `Performer._dispatch_tool` call**; keep the plan-time filter trio at its current cardinality per lane (`service.py:268-291` for deterministic; `_dispatch_tool` per-dispatch for autonomous); complete the real-adapter exec inside the runtime helper; derive dispatch from the LLM Understanding.

- **Explicit brake inventory for `_dispatch_tool` *today* (so reviewers size the real safety delta):**
  - PRESENT (plan-time filters, per-dispatch): `filter_plan_steps` (`performer.py:295`), `RiskFilter` (`performer.py:302`).
  - ABSENT (plan-time): `filter_by_tier_flags` (tier gate) — added per-dispatch in PR4.
  - ABSENT (runtime): `adapter.execute` itself (step 5–7 deferred at `performer.py:320-323`), `EgressMonitor.monitor_log_line` + `KillSwitch`, container-ID kill-switch registration, rescope harvest + `RescopeService.pause_for_rescope`, `SafetyViolation`/`persist_kali_shim_block` audit — all delivered via the shared runtime helper in PR2/PR4. `runtime_delegator.py:16-17` literally names `tier_gating + egress_monitor + RescopeService` as the brakes — all absent from the path it invokes today.
- Pros: smallest diff per PR; preserves byte-identical replay because (i) the deterministic lane's plan-time filter rows do NOT move and (ii) the runtime brake CODE is moved verbatim into the helper; the shared runtime helper makes runtime brake-parity a **structural** invariant enforced by a guard, not manual vigilance; matches the "additive" constraint exactly; one audited runtime choke point instead of two divergent ones.
- Cons: the runtime-helper refactor touches `PlanExecutor.execute`, so it must be gated by the LIVE differential harness on every PR (mitigated: PR0 builds that harness; it runs each PR); the net-new Ollama tool-use loop machinery is a real build cost (JSON envelope schema + parse/`ModelUnreachable` handling + caps); the tier gate is a documented per-lane invariant, not physically co-located in the runtime helper (mitigated by `test_autonomous_tier_gate_blocks_unapproved.py`).

**Option B — New parallel autonomous orchestrator service, leave Performer dead.**
Build a fresh `XbowOrchestrator` that calls Ollama + adapters directly, ignore `performer.py`.
- Pros: no entanglement with the PentAGI-port ADR assumptions; clean mental model.
- Cons: duplicates the concurrency leases, scrubber publish, adviser/reflector wiring, and the full runtime envelope; **doubles the safety-audit surface and creates a THIRD divergent execution path** to keep in brake-parity; higher regression risk; violates "reuse what exists." **Rejected** — Option A with the shared runtime helper already delivers B's "single clean runtime choke point" benefit without abandoning the existing scaffolding or its replay guards.

**Option C — Flip the existing flags ON and ship as-is.**
- Pros: zero code.
- Cons: the role loops return fixtures, `_dispatch_tool` never calls the real adapter (step 5–7 deferred), the interview never blocks, the Performer has zero live callers, and the WS path is broken — nothing autonomous would actually run, and the live runtime brakes would be absent if it did. **Rejected (invalidation):** verified — `run_session` zero non-test callers; `_dispatch_tool` step 5–7 deferred (`performer.py:320-323`); `ask()` never invoked by any role; `useWebSocket.ts:18` targets a path the backend does not serve; egress/kill-reg/rescope absent from the dispatch path.

**Surviving option: A.** B and C are invalidated above.

---

## 2. Pre-mortem (4 failure scenarios + named-test mitigations)

**Scenario 1 (DOMINANT) — Real Docker exec ships with the egress monitor, kill-switch registration, and rescope pause silently absent on the autonomous path.**
Root cause risk: the live runtime envelope (`EgressMonitor.monitor_log_line` + kill at `executor.py:77-81`, container-ID kill registration at `executor.py:68-74`, rescope harvest + `pause_for_rescope` at `executor.py:167-206`, `persist_kali_shim_block` at `executor.py:103-133`) lives ONLY in `PlanExecutor.execute`. If the autonomous lane runs `adapter.execute` via the old `_dispatch_tool` ad-hoc block, an autonomous recon step would run a real container against scanme with **no per-log egress monitoring, no container registered for the kill switch, and no rescope human-approval pause** — a safety-control-plane bypass on the one path that executes live tools.
- Mitigation: PR2 extracts `execute_tool_through_safety_chain` as the single RUNTIME execution choke point running the full runtime envelope (moved verbatim from `executor.py:62-216`); PR0's spy harness asserts egress + kill-registration + rescope-harvest fire on **every** autonomous dispatch; a structural/AST guard (walking `ast.Call` nodes for `adapter.execute()` call sites, NOT imports) asserts `adapter.execute` is never called except through the helper.
- Named tests: `tests/safety/test_safety_chain_full_envelope_spy.py`, `tests/safety/test_egress_kill_fires_on_autonomous_path.py`, `tests/safety/test_kill_switch_registration_on_autonomous_path.py`, `tests/safety/test_autonomous_new_host_pauses_for_rescope.py`, `tests/ast/test_adapter_execute_only_via_safety_helper.py`.

**Scenario 2 — A wiring change silently bypasses the tier gate; an active-exploit step runs against scanme without approval.**
Root cause risk: today `_dispatch_tool` runs `filter_plan_steps` + `RiskFilter` but NOT `filter_by_tier_flags` (verified `performer.py:295,302`); the legacy lane runs the tier gate at `service.py:274`. The tier gate is **per-lane** (not inside the runtime helper), so the autonomous lane must add it explicitly.
- Mitigation: PR4 adds `filter_by_tier_flags(session.approval_flags)` per-dispatch in `_dispatch_tool` (alongside the existing filter trio at `performer.py:295-309`); the deterministic lane keeps its gate at `service.py:274` unchanged; an active-tier dispatch without the flag is blocked on the autonomous lane.
- Named tests: `tests/safety/test_autonomous_tier_gate_blocks_unapproved.py`, `tests/safety/test_safety_chain_full_envelope_spy.py`.

**Scenario 3 — Byte-identical replay drifts because the runtime-helper refactor changed `PlanExecutor.execute`'s audit trace, or the new lane mutates shared state — and the existing fixture comparator fails to catch it.**
Root cause risk: PR2 refactors `PlanExecutor.execute` to call the runtime helper; if the emitted audit/agent-execution rows change shape, order, or count, replay drifts. The existing `test_v11_byte_identical.py` is a PURE FIXTURE test (loads `golden_*.json`, compares to itself/poisoned copies, lines 35-107) and **never runs the live pipeline**, so it cannot detect this drift. Separately, `seed_xbow._register_all()` mutates `ROLE_REGISTRY`.
- Mitigation: PR0 BUILDS `tests/regression/test_planexecutor_refactor_byte_identical.py` as a **LIVE differential harness** — it runs the real saved-workflow pipeline before AND after the refactor and feeds BOTH emitted `audit_log` AND `agent_execution` row sets into `compare_audit_log_rows` + `compare_agent_execution_rows`; PR2's refactor is required to keep this green; the plan-time filter rows do NOT move (filters stay at their current cardinality); `seed_xbow` registration stays lazy (`tests/ast/test_seed_xbow_isolation.py`).
- Named tests: `tests/regression/test_planexecutor_refactor_byte_identical.py` (LIVE before/after, every PR), `tests/regression/test_deterministic_lane_unchanged_with_xbow_off.py`, `tests/regression/test_v11_byte_identical.py` (fixture self-check, retained), `tests/ast/test_seed_xbow_isolation.py`.

**Scenario 4 — Ollama is unreachable / emits non-JSON / hangs mid-session; the autonomous session wedges or 500s instead of failing safe.**
Root cause risk: qwen3-14b cold-load can take minutes; the net-new tool-use loop sits on single-shot `OllamaClient.send` and must catch `ModelUnreachable` and parse failures, and must enforce the turn/wall-clock cap (`IterationCapHit`).
- Mitigation: every Ollama call site catches `ModelUnreachable` → audit + `_fail` (or fall back to deterministic lane if configured); the JSON tool-call envelope has a defined parse-failure path; turn cap + wall-clock cap via `IterationCapHit`.
- Named tests: `tests/integration/test_autonomous_ollama_unreachable_fails_safe.py`, `tests/unit/test_ollama_tool_envelope_parse_failure.py`, `tests/unit/test_autonomous_iteration_cap_hit.py`.

---

## 3. Expanded Test Plan

### Unit
- `tests/unit/test_ollama_role_client_routing.py` — Pentester/Adviser/Generator route to `OllamaClient` when `osa_llm_provider="ollama"`, not `anthropic_default_model`.
- `tests/unit/test_pentester_live_tool_loop.py` — Pentester emits a real Ollama tool-call envelope (mocked OllamaClient) and terminates on `done`.
- `tests/unit/test_ollama_tool_envelope_schema.py` — the JSON tool-call envelope schema validates well-formed envelopes and rejects malformed ones (defined parse-failure path).
- `tests/unit/test_ollama_tool_envelope_parse_failure.py` — non-JSON / schema-invalid model output → clean handled failure, not a crash.
- `tests/unit/test_autonomous_iteration_cap_hit.py` — turn cap AND wall-clock cap trip `IterationCapHit` and halt the loop.
- `tests/unit/test_coordinator_interview_blocking.py` — interview loop blocks on operator reply, terminates on ambiguity≤threshold or turn cap.
- `tests/unit/test_understanding_drives_dispatch.py` — `ordered_phases`/`family_recommendations` derived from LLM understanding, not hardcoded `['recon','exploit','extraction']`.
- `tests/unit/test_runtime_helper_runs_full_envelope.py` — `execute_tool_through_safety_chain` invokes (in order) `adapter.execute` through shims/IMAGE_REGEX → per-log egress + kill → kill-registration → rescope harvest/pause → shim-block audit (helper unit-level, RUNTIME stages only — the plan-time filter trio is asserted separately at its call sites).

### Integration
- `tests/integration/test_performer_full_cycle.py` (extend) — `run_session` invoked from the live orchestrator path with Ollama-backed roles (mocked client), executing through the shared runtime helper.
- `tests/integration/test_planexecutor_uses_shared_helper.py` — `PlanExecutor.execute` routes every step's container run through `execute_tool_through_safety_chain` (refactor verification); the plan-time filter trio stays in `service.py` at plan cardinality.
- `tests/integration/test_autonomous_dispatch_runs_filter_trio_per_dispatch.py` — the autonomous lane runs `filter_plan_steps → filter_by_tier_flags → RiskFilter` per `_dispatch_tool` call (the per-lane plan-time filter location for the autonomous path).
- `tests/integration/test_coordinator_safety_chain.py` (extend) — full envelope on the autonomous path: per-dispatch filter trio + tier gate, then runtime helper egress/kill-reg/rescope.
- `tests/integration/test_autonomous_dispatch_from_understanding.py` — Understanding → `_materialize_families` → roles actually queried/driven.
- `tests/integration/test_autonomous_ollama_unreachable_fails_safe.py` — `ModelUnreachable` → clean fail + audit row.
- `tests/integration/test_interview_inline_wait.py` — messages endpoint round-trips a blocking interview answer **while the Performer lease is released** (no concurrency starvation).
- `tests/integration/test_interview_does_not_starve_lease.py` — a blocked interview turn does not hold `_active_performers`, so a second session can acquire the lease.

### E2E
- `tests/e2e/test_ws_auth_relay_loop.py` — WebSocket auth + topic relay loop (none exists today; AC6 requirement).
- `tests/e2e/test_scanme_real_docker_recon.py` — **milestone gate**, marked `@pytest.mark.docker`/`@pytest.mark.e2e` (opt-in, not in default suite): full session against `scanme.nmap.org` runs real `osa-agent-nmap:latest` (+ one of nuclei/httpx/subfinder) **through the shared runtime helper**, produces real findings with evidence tags, exploit-tier steps stay blocked without `approval_flags`, and a synthetic new-host finding pauses for rescope.

### Safety / Observability / Replay
- `tests/regression/test_planexecutor_refactor_byte_identical.py` — **LIVE differential harness** (NOT a fixture self-check): runs the real saved-workflow pipeline before AND after the PR2 refactor, feeding BOTH emitted `audit_log` AND `agent_execution` row sets into `compare_audit_log_rows` + `compare_agent_execution_rows`. Asserts zero drift. This is the harness the prior draft falsely assumed already existed.
- `tests/regression/test_deterministic_lane_unchanged_with_xbow_off.py` — with all `osa_*` flags False, a live deterministic run's `audit_log` AND `agent_execution` rows match the golden set; explicitly asserts the autonomous lane's per-step `AgentExecution` rows do NOT appear / do NOT alter `compare_agent_execution_rows` when flags are OFF (agent_execution is NOT covered by `EXCLUDED_AUDIT_PREFIXES`, so flag-gating is its only protection).
- `tests/safety/test_safety_chain_full_envelope_spy.py` — spy asserts the FULL ordered chain on the autonomous path: per-dispatch `filter_plan_steps → filter_by_tier_flags → RiskFilter` (plan-time, in `_dispatch_tool`) THEN the runtime helper's `shims → IMAGE_REGEX → egress → kill-reg → rescope-harvest → shim-audit`.
- `tests/safety/test_egress_kill_fires_on_autonomous_path.py` — a poisoned log line on the autonomous path triggers `KillSwitch` via `monitor_log_line`.
- `tests/safety/test_kill_switch_registration_on_autonomous_path.py` — the container ID is registered for the kill switch on the autonomous path.
- `tests/safety/test_autonomous_new_host_pauses_for_rescope.py` — a new-host discovery on the autonomous lane calls `RescopeService.pause_for_rescope` and halts on pending approval (D4).
- `tests/safety/test_shim_block_audit_on_autonomous_path.py` — a `SafetyViolation` on the autonomous path persists a kali shim-block audit row.
- `tests/safety/test_autonomous_tier_gate_blocks_unapproved.py` — an active-exploit-tier dispatch without `session.approval_flags` is blocked by the per-dispatch tier gate in `_dispatch_tool`.
- `tests/ast/test_adapter_execute_only_via_safety_helper.py` — structural guard: walks `ast.Call` nodes for `<x>.execute(...)` where the receiver resolves to an adapter; asserts such calls appear ONLY inside `execute_tool_through_safety_chain` (RUNTIME helper scope). NOTE: the existing `tests/ast/test_no_direct_backend_calls.py:13` docstring falsely claims it checks "AgentAdapter.execute directly" but its implementation (lines 45-68) only walks `ast.Import`/`ast.ImportFrom` for docker/backend symbols — this new guard supplies the call-site check the existing one does not, and PR0 corrects the false docstring.
- `tests/safety/test_scrubber_runs_on_live_path.py` — `ConversationScrubber` invoked when Performer is live.
- `tests/integration/test_conversation_topic_live_producer.py` — Performer role turns publish to `conversation` + `raw_conversation` and persist to `MsgChain`.
- Metric assertions on `conversation_topic_dropped_events_total` token-bucket behavior.

---

## 4. Wave / PR Sequence

> Ordering rationale: invariant-preserving + low-risk first (PR0 LIVE differential harness + full-envelope spy + corrected structural guard, PR1 WS-path C6, **PR2 runtime-helper refactor — the single audited RUNTIME choke point lands before any new autonomous behavior**), then the autonomous core inside-out (C2 engine/Ollama → C1 interview → C3 dispatch → C4 real exec), then hardening (C5/C7), then the flag flip. Every PR keeps the LIVE differential harness, fixture comparator, and both AST guards green; each new behavior is default-OFF until PR10.

---

### PR0 — LIVE differential replay harness + full-envelope spy + corrected structural adapter-exec guard + CI baseline (C7 prep, no behavior change)
- **Goal:** make the FULL live runtime envelope observable and asserted, and (critically) BUILD the live differential replay harness the prior plan falsely assumed existed, before any wiring change.
- **C-components:** C7 (prep), cross-cutting.
- **Files:**
  - `tests/regression/test_planexecutor_refactor_byte_identical.py` (new) — **LIVE differential harness**: drives the real saved-workflow pipeline (`OrchestratorService.run` / `PlanExecutor.execute`) end-to-end, captures emitted `audit_log` AND `agent_execution` rows, and feeds them into `compare_audit_log_rows` + `compare_agent_execution_rows`. Authored to pass against the PRE-refactor code so it is a true before/after differential in PR2. (BLOCKING fix: the existing `test_v11_byte_identical.py` is fixture-only and cannot catch a refactor drift.)
  - `tests/safety/test_safety_chain_full_envelope_spy.py` (new) — spy/monkeypatch asserting the autonomous-path ordered chain: per-dispatch `filter_plan_steps → filter_by_tier_flags → RiskFilter` THEN runtime helper `shims → IMAGE_REGEX → EgressMonitor.monitor_log_line → container-kill registration → rescope harvest → shim-audit`.
  - `tests/ast/test_adapter_execute_only_via_safety_helper.py` (new) — AST guard walking `ast.Call` nodes for adapter-`.execute(...)` call sites (NOT imports); asserts they appear only inside `execute_tool_through_safety_chain`. Authored now asserting the intended invariant (`xfail`-marked until PR2 introduces the helper, then flipped to passing in PR2).
  - `tests/ast/test_no_direct_backend_calls.py` — **correct the false docstring** at line 13 (it claims to check `AgentAdapter.execute directly` but only walks imports); either narrow the docstring to "import-level docker/backend symbol guard" or extend it — the plan delegates the call-site check to the new guard above and reconciles the two explicitly.
  - `tests/regression/test_deterministic_lane_unchanged_with_xbow_off.py` (new) — default-OFF flags ⇒ live deterministic `audit_log` + `agent_execution` rows byte-identical; explicit assertion that no autonomous `AgentExecution` rows leak into the golden set (agent_execution NOT covered by `EXCLUDED_AUDIT_PREFIXES`).
  - Reuse: `tests/regression/test_v11_byte_identical.py`, `tests/_regression/v11_comparator.py`, `tests/ast/test_no_direct_backend_calls.py`.
- **Acceptance criteria:**
  - The LIVE differential harness runs the real pipeline and is green against pre-refactor code (so a PR2 drift would turn it red).
  - Spy harness fails loudly if ANY chain stage (per-dispatch filter trio incl. tier gate, OR runtime egress/kill-reg/rescope) is skipped or reordered.
  - With all `osa_*` flags False, both the live differential harness and `test_deterministic_lane_unchanged_with_xbow_off.py` are byte-identical (green), including `agent_execution` rows.
  - Existing AST guard green and its docstring corrected; the new adapter-exec structural guard is authored (`xfail` until PR2, then flipped to passing in PR2).
- **Safety/replay invariant:** pure test addition + a docstring correction; no source-behavior change ⇒ replay trivially green.

---

### PR1 — Fix the WebSocket path mismatch + add WS auth/relay E2E (C6)
- **Goal:** frontend hooks + Vite proxy + backend route agree so live monitoring actually receives data.
- **C-components:** C6.
- **Files (file:line where known):**
  - `frontend/src/hooks/useWebSocket.ts:18` — `/ws/sessions/...` → `/api/v1/ws/sessions/...` (align with `InteractionDashboard.tsx:77`, which is correct).
  - `frontend/src/hooks/useTopicWebSocket.ts:40` — same fix.
  - `frontend/vite.config.ts:21` — add an `/api/v1/ws` proxy target or rewrite `/ws`→`/api/v1/ws`; backend serves `/api/v1/ws/sessions/...` (`main.py:181`, `api/v1/ws.py:91`).
  - `tests/e2e/test_ws_auth_relay_loop.py` (new) — AC6: WS auth + relay loop coverage.
- **Acceptance criteria (AC6):**
  - Monitor + FlowPage Terminal/Agents tabs receive live data in dev and prod path.
  - E2E covers WS auth + topic relay (token + topics query params per `ws.py:93,99`).
  - No backend route change required.
- **Safety/replay invariant:** frontend + test only; backend untouched ⇒ replay green.

---

### PR2 — Extract the shared RUNTIME helper `execute_tool_through_safety_chain` + refactor `PlanExecutor` onto it (C7 core, BLOCKING fix — two-seam synthesis)
- **Goal:** create ONE audited RUNTIME execution choke point (adapter.execute + runtime brakes only), and prove the deterministic lane is byte-identical over it via the LIVE harness before any autonomous caller exists. The plan-time filter trio is explicitly NOT moved.
- **C-components:** C7 (the structural fix the Architect + Critic both require, in its corrected two-seam form).
- **Files (file:line):**
  - `backend/app/orchestrator/safety_exec.py` (new) — `async def execute_tool_through_safety_chain(step, target, *, whitelist_rules, egress_monitor, kill_switch, container_kill_registry, rescope_service, audit, db, event_bus, session_id, actor_id)` running, in order: `get_adapter(...).execute(...)` through shims/IMAGE_REGEX → per-log `EgressMonitor.monitor_log_line` + `KillSwitch` (mirror `executor.py:77-81`) → container-ID kill-switch registration (mirror `executor.py:68-74`) → rescope harvest + `RescopeService.pause_for_rescope` halting on pending approval (mirror `executor.py:167-206`) → `SafetyViolation`/`persist_kali_shim_block` audit (mirror `executor.py:103-133`). This is the `executor.py:62-216` body **moved verbatim**. **The plan-time filter trio (`filter_plan_steps`/`filter_by_tier_flags`/`RiskFilter`) is NOT a parameter of and NOT called by this helper** — it stays at plan-time cardinality per lane. This helper is the ONLY place `adapter.execute` may be called.
  - `backend/app/orchestrator/executor.py:55-225` — refactor `PlanExecutor.execute` so the per-step container run delegates to `execute_tool_through_safety_chain(...)`. **The plan-time filter trio stays exactly where it is in `OrchestratorService.run` (`service.py:268-291`) at plan cardinality — it is NOT pulled into the per-step loop.** **MUST keep the saved-workflow `audit_log` AND `agent_execution` traces byte-identical** (same rows, same order, same shapes) — gated by the LIVE differential harness every PR.
  - `backend/app/orchestrator/service.py:268-291` — UNCHANGED for the deterministic lane: `filter_plan_steps` (`:268`) → `filter_by_tier_flags` (`:274`) → `RiskFilter` (`:291`) still run once per plan and emit the `steps_blocked` summary (`:294-301`) + `persist_kali_blocked_steps` rows (`:282-288`). Explicitly documented so reviewers confirm no plan-level audit row moves.
  - Reuse: `safety/egress_monitor.py`, `safety/risk_filter.py`, `safety/whitelist.py`, `rescope.py`, `kali_allowlist.persist_kali_shim_block`. (`safety/exploit_allowlist.filter_by_tier_flags` is NOT touched here — it stays at its plan-time call site `service.py:274`.)
- **Acceptance criteria:**
  - `PlanExecutor.execute` routes every step's container run through the helper; no `adapter.execute` call remains outside `safety_exec.py`.
  - The plan-time filter trio is verifiably unmoved (`service.py:268-291` still owns it; no per-step filter call added to `PlanExecutor`).
  - `tests/regression/test_planexecutor_refactor_byte_identical.py` (the LIVE before/after harness from PR0) is green — explicitly a before/after live-pipeline run feeding `audit_log` AND `agent_execution` rows into the comparator, NOT a fixture self-comparison.
  - `tests/ast/test_adapter_execute_only_via_safety_helper.py` (from PR0) flips from `xfail` to passing.
  - `tests/unit/test_runtime_helper_runs_full_envelope.py` asserts the runtime envelope order (filter trio asserted separately at its call sites).
- **Safety/replay invariant:** behavior-preserving refactor of the deterministic lane only; runtime brake code moved verbatim, plan-time filters unmoved; no new lane yet; the LIVE differential harness green every PR or the refactor is reverted.

---

### PR3 — Ollama routing seam for all agent roles (C2 prep, default-OFF)
- **Goal:** give every role a single, flag-gated way to reach `OllamaClient` instead of `settings.anthropic_default_model`.
- **C-components:** C2.
- **Files (file:line):**
  - `backend/app/orchestrator/roles/pentester.py:61` — replace hardcoded `settings.anthropic_default_model` default with a provider-aware resolver (mirror `planner.py:60-71`'s `osa_llm_provider` switch).
  - `backend/app/orchestrator/roles/adviser.py:46` — same resolver.
  - `backend/app/orchestrator/roles/generator.py:81` — supply `OllamaClient` when provider=ollama.
  - New helper `backend/app/orchestrator/roles/llm_provider.py` — single `resolve_role_client()` returning `OllamaClient` or `ModelClient` per `osa_llm_provider`.
  - Reuse: `backend/app/orchestrator/ollama_client.py` (unchanged).
- **Acceptance criteria (AC2 partial, D3):**
  - With `osa_llm_provider="ollama"`, all three roles resolve to `OllamaClient`; with `"anthropic"`, behavior unchanged.
  - Smoke fallback (no client) still returns fixtures for unit isolation.
  - `tests/unit/test_ollama_role_client_routing.py` green.
- **Safety/replay invariant:** roles not yet invoked on the live path ⇒ no runtime behavior change; replay green.

---

### PR4 — Wire Performer into the live path through the shared runtime helper + add per-dispatch tier gate + de-stub roles into Ollama tool-use loops (C2, BLOCKING fixes folded in)
- **Goal:** `Performer.run_session` runs from `OrchestratorService.run` (XBOW lane); roles execute net-new Ollama tool-use loops; `_dispatch_tool` runs the per-dispatch filter trio (incl. the newly-added tier gate) and delegates the real container run to `execute_tool_through_safety_chain` (so the autonomous path inherits the FULL envelope: per-lane tier gate + the runtime helper's egress, kill-reg, rescope, shim-audit).
- **C-components:** C2 (and closes the tier-gate + egress + kill-reg + rescope gaps in the Performer path via the per-lane gate + shared runtime helper).
- **EgressMonitor lifecycle (BLOCKING resolution — session-scoped):** `PlanExecutor` constructs ONE `EgressMonitor` per `execute()` call seeded with `whitelist_rules` (`executor.py:34`; constructor `egress_monitor.py:17-27` takes `session_id` + `whitelist_rules`). `_dispatch_tool` has NO `whitelist_rules` in scope and is called per-tool-call. **Resolution: construct ONE `EgressMonitor` per Performer session** (seeded with the session's `whitelist_rules`, resolved at session start the same way `PlanExecutor` resolves them) and thread it into every `_dispatch_tool` call for that session — one monitor per session, NOT per dispatch. The session-scoped monitor (plus kill switch + container-kill registry + `RescopeService`) is passed as the helper's runtime params on each call. `whitelist_rules` provenance on the autonomous path is documented at the session-construction site.
- **Files (file:line):**
  - `backend/app/orchestrator/service.py:103-318` — add an XBOW-lane branch (new flag `osa_xbow_autonomous_enabled`, default False) that constructs a `Performer`, resolves the session's `whitelist_rules`, constructs the session-scoped `EgressMonitor`/kill switch/container-kill registry/`RescopeService`, registers Ollama-backed roles, and calls `run_session` (legacy `PlanExecutor` preserved when flag off).
  - `backend/app/orchestrator/performer.py:295-309` — **ADD `filter_by_tier_flags(session.approval_flags)` to the per-dispatch filter trio**, alongside the existing `filter_plan_steps` (`:295`) + `RiskFilter` (`:302`). This is the per-lane tier gate for the autonomous path (the deterministic lane keeps its gate at `service.py:274`; `PlanExecutor` gains NO redundant gate).
  - `backend/app/orchestrator/performer.py:320-334` — replace the deferred step 5–7 stub: `_dispatch_tool` now calls `execute_tool_through_safety_chain(...)` (the SAME runtime helper `PlanExecutor` uses), passing the session-scoped egress monitor, kill switch, container-kill registry, and `RescopeService`. **The runtime envelope (egress monitor, kill-switch registration, rescope harvest, shim-audit) fires here because it lives inside the helper; the tier gate fires here because it was added to the per-dispatch filter trio above** — not re-implemented piecemeal.
  - `backend/app/orchestrator/roles/pentester.py:88-101` — replace smoke fixture `run()` with a net-new Ollama tool-use loop: emit a JSON tool-call envelope → `runtime_delegator.delegate_tool_call` → read result → iterate to `done` or `IterationCapHit`. **Define the envelope schema** (`{"tool": str, "intent": str, "config": {...}}` or `{"done": true, "summary": str}`); parse-failure and `ModelUnreachable` both route to clean session-fail + audit; turn cap + wall-clock cap enforced (first-class, not a footnote).
  - `backend/app/orchestrator/roles/adviser.py:46-63` — replace static message with an Ollama guidance call (preserve trigger semantics).
  - `backend/app/orchestrator/runtime_delegator.py:32` — invoked from the live Pentester loop; its `_dispatch_tool` target now carries the per-dispatch tier gate + the runtime helper (resolves the `runtime_delegator.py:16-17` brake-contract mismatch).
  - Reuse: `performer._publish_role_turn` (scrubber + topics already wired).
- **Acceptance criteria (AC2.x):**
  - `Performer.run_session` has a live (non-test) app caller behind the XBOW flag.
  - Pentester/Adviser/Generator + family roles run live Ollama loops (no fixture envelopes when client present).
  - At least one agent reads another agent's output via shared `Performer.context` / `delegate_tool_call` and adapts; inter-agent messages publish to `conversation` and persist to `MsgChain`.
  - **Per-dispatch filter trio runs on the autonomous path** (`filter_plan_steps → filter_by_tier_flags → RiskFilter`) — asserted by `test_autonomous_dispatch_runs_filter_trio_per_dispatch.py`; the tier gate blocks an unapproved active-exploit dispatch.
  - **Runtime envelope fires on the autonomous path** (asserted by the PR0 spy now exercised live): a poisoned log line triggers `KillSwitch`; the container ID is registered for the kill switch; a synthetic new-host finding pauses for rescope; a `SafetyViolation` persists a shim-block audit row. The session-scoped `EgressMonitor` is constructed once per session and threaded into each dispatch.
  - **autonomous `agent_execution` rows do not collide with the deterministic golden set when flags are OFF** — `test_deterministic_lane_unchanged_with_xbow_off.py` (extended) asserts no autonomous `AgentExecution` rows leak (agent_execution NOT covered by `EXCLUDED_AUDIT_PREFIXES`).
  - **Ollama tool-use loop is first-class:** envelope schema defined; non-JSON / `ModelUnreachable` → clean fail + audit; turn + wall-clock caps trip `IterationCapHit`.
  - Named tests: `test_autonomous_tier_gate_blocks_unapproved.py`, `test_autonomous_dispatch_runs_filter_trio_per_dispatch.py`, `test_egress_kill_fires_on_autonomous_path.py`, `test_kill_switch_registration_on_autonomous_path.py`, `test_autonomous_new_host_pauses_for_rescope.py`, `test_shim_block_audit_on_autonomous_path.py`, `test_pentester_live_tool_loop.py`, `test_ollama_tool_envelope_parse_failure.py`, `test_autonomous_iteration_cap_hit.py`, `test_autonomous_ollama_unreachable_fails_safe.py`, `test_deterministic_lane_unchanged_with_xbow_off.py`.
- **Safety/replay invariant:** entire branch behind `osa_xbow_autonomous_enabled` default False; the autonomous path shares the SAME audited RUNTIME choke point as the deterministic lane and runs the same filter trio per-dispatch; the LIVE differential harness + `test_deterministic_lane_unchanged_with_xbow_off.py` stay green with the flag off.

---

### PR5 — Interview-driven Coordinator: blocking LLM interview WITHOUT starving the Performer lease (C1, BLOCKING fix folded in)
- **Goal:** the component named "Coordinator" drives a multi-turn, Ollama-driven, blocking interview and builds Understanding from the transcript — and a blocked interview turn does NOT hold the per-session Performer lease.
- **C-components:** C1.
- **Files (file:line):**
  - `backend/app/orchestrator/ask_tool.py:8-12,32-46` — upgrade from "does NOT wait inline" to an inline-waiting turn, **but release/avoid the `_PerformerLease` while awaiting the operator reply**. Chosen mechanism: **the interview runs OUTSIDE the Performer lease** — the Coordinator's interview loop owns turn-pacing via the existing AmbiguityLoop and only acquires a Performer lease once the interview terminates and dispatch begins. The await for the operator reply (via `/pentest-sessions/{id}/messages`) must not occupy `_active_performers`, so the documented ADR-003 concurrency cap (`max_concurrent_performer_sessions`, `performer.py:350-369`) is not starved by a blocked interview.
  - `backend/app/orchestrator/coordinator.py:50-104` — add an LLM-driven interview path (Ollama) producing `UnderstandingOfTarget` from the transcript; keep `UnderstandingBuilder`/`PlanOfWorkBuilder` as the deterministic fallback (unchanged for replay).
  - Reuse mislocated loop logic from `workflow_service.py:242-467` (move/own inside Coordinator; do not rewrite the AmbiguityLoop math).
  - `frontend` `CoordinatorPage` / ConversationTab — add a user-input affordance so the ConversationTab is no longer read-only.
- **Acceptance criteria (AC1.x):**
  - Coordinator poses explicit clarifying questions and blocks on the user's answer; terminates on ambiguity≤threshold or turn cap → human review.
  - Interview is Ollama-driven (not the keyword/TLD builder); Understanding produced from the transcript by the LLM.
  - **A blocked interview turn does not hold the Performer lease** (`tests/integration/test_interview_does_not_starve_lease.py`); a second session can acquire a slot while one is interviewing.
  - ConversationTab accepts user input; round-trip covered by `tests/integration/test_interview_inline_wait.py`.
- **Safety/replay invariant:** LLM interview path flag-gated; deterministic builders untouched ⇒ replay green; `test_autonomous_iteration_cap_hit.py` covers the interview turn cap.

---

### PR6 — Understanding-driven dynamic dispatch (C3)
- **Goal:** dispatch is selected by the Understanding/Plan-of-Work, not hardcoded phases; materialized families actually drive execution.
- **C-components:** C3.
- **Files (file:line):**
  - `backend/app/orchestrator/coordinator.py:97-104` — `PlanOfWorkBuilder` (LLM path) derives `ordered_phases` + `family_recommendations` from the understanding (deterministic builder keeps the constant for replay).
  - `backend/app/orchestrator/service.py:349-376` — `_materialize_families` rows become queried drivers: the XBOW-lane branch reads materialized families and registers the matching `seed_xbow` roles with the per-vector `vector_to_tool_palette`.
  - `backend/app/orchestrator/roles/seed_xbow.py:38-130` — family roles select tools from the understanding's vector; de-stub `run()` to dispatch via the Pentester/delegator loop (which routes the container run through the shared runtime helper and the per-dispatch filter trio).
- **Acceptance criteria (AC3.x):**
  - `ordered_phases`/`family_recommendations` derived from target/understanding (assert non-hardcoded for a web vs network target).
  - `_materialize_families` rows drive execution (queried, not empty placeholders).
  - Agent/tool selection flows Understanding → dispatch.
  - `tests/integration/test_autonomous_dispatch_from_understanding.py` + `tests/unit/test_understanding_drives_dispatch.py` green.
- **Safety/replay invariant:** autonomous-lane-only; deterministic `_materialize_families` preserved for the demo lane; replay green.

---

### PR7 — Real Docker recon execution against scanme (C4) — milestone behavioral crux
- **Goal:** the autonomous loop runs REAL `osa-agent-*:latest` recon containers against `scanme.nmap.org` and produces real findings — **all through `execute_tool_through_safety_chain`** (so real exec inherits the full runtime envelope automatically).
- **C-components:** C4.
- **Files (file:line):**
  - `backend/app/orchestrator/safety_exec.py` — the real `adapter.execute` path lands here (already the only legal call site from PR2); the autonomous lane reaches it via `_dispatch_tool` (PR4). No new `adapter.execute` call site is introduced in `performer.py`.
  - `backend/app/agents/nmap.py:11`, `nuclei.py:14`, `httpx_tool.py:17`, `subfinder.py:9`, `dnsx.py:11` — recon image set (`osa-agent-nmap/nuclei/httpx/subfinder/dnsx:latest`); document the build set + enable `osa_kali_backend_enabled` for the recon path.
  - `backend/app/agents/headless_browser.py:17`, `mitmproxy.py:17`, `interactsh.py:15` — return real exec results for the recon path OR document explicitly out-of-scope-for-recon (AC4 allows this).
  - `tests/e2e/test_scanme_real_docker_recon.py` (new, `@pytest.mark.docker`, opt-in).
- **Acceptance criteria (AC4.x):**
  - A full session against `scanme.nmap.org` runs real Docker recon containers (nmap + ≥1 of nuclei/httpx/subfinder) and produces real findings (no `*-stub-exec` IDs), with every container call traversing the shared runtime helper.
  - Required `osa-*:latest` images build (documented build set); Kali recon path enabled.
  - Headless/mitmproxy/interactsh either return real exec results or are documented out-of-scope-for-recon.
- **Safety/replay invariant:** real exec only on the XBOW lane (flag off ⇒ legacy path, replay green); `adapter.execute` routes through `agents/backends/docker.py` ⇒ `test_no_direct_backend_calls.py` green; the new structural guard confirms it is called only via the helper.

---

### PR8 — Evidence tags + Interactsh OOB correlation for approved exploit steps (C5)
- **Goal:** findings carry evidence tags; OOB canary minted + correlated for any human-approved exploit step.
- **C-components:** C5.
- **Files:**
  - Finding model / `app/reports/generator.py` — add `evidence_tag` to findings.
  - `backend/app/agents/interactsh.py`, `canary.py:15` — mint OOB canary per session; correlate to findings; `OOBCallback` row + `collaborator` topic.
  - Document the milestone-2 dedicated validator agent (not built).
- **Acceptance criteria (AC5.x):**
  - Findings carry an evidence tag.
  - Interactsh OOB canary minted per session + correlated for human-approved exploit steps.
  - Milestone-2 validator agent documented, not built.
- **Safety/replay invariant:** additive finding metadata behind the autonomous lane; exploit steps still require approval (per-dispatch tier gate in `_dispatch_tool`); replay green.

---

### PR9 — Live-path safety verification + egress widening or documented gap (C7 close-out)
- **Goal:** verify (not assume) the full chain (per-dispatch filter trio + runtime envelope) + scrubber fire on the live autonomous path; widen egress coverage or document the recon-only gap.
- **C-components:** C7.
- **Files (file:line):**
  - `backend/app/safety/egress_monitor.py:12-14` — extend beyond the single IPv4 `CONNECTION_PATTERN` (DNS / TLS-SNI / Host-header) OR explicitly accept+document the gap for the recon-only milestone.
  - `backend/app/safety/conversation_scrubber.py` — confirm it runs on the live path (`_publish_role_turn:185`); add `tests/safety/test_scrubber_runs_on_live_path.py`.
  - MITM egress routing: verify `seed_xbow.AttackAgent:82-87` integration when `osa_traffic_via_mitm`.
- **Acceptance criteria (AC7.x):**
  - The full-envelope spy harness (PR0) asserts the entire chain (per-dispatch filter trio incl. tier gate + runtime egress/kill-reg/rescope/shim-audit) fires on every autonomous-agent tool call, now exercised on a live run.
  - Scrubber verified on the live path.
  - Egress coverage extended OR gap explicitly accepted+documented for recon-only.
  - Exploit-tier steps remain blocked without `approval_flags`; **rescope still pauses for human approval — backed by the real implementation in PR2's runtime helper + PR4's autonomous wiring** (`test_autonomous_new_host_pauses_for_rescope.py`), not a vacuous criterion.
- **Safety/replay invariant:** hardening + verification only; replay green; AST guards green.

---

### PR10 — Flag flip to default-ON after verification + ADR (cross-cutting, D5)
- **Goal:** flip the XBOW flags default-ON once the scanme E2E passes; keep the deterministic lane reachable as offline fallback; record the ADR.
- **C-components:** cross-cutting (D5).
- **Files (file:line):**
  - `backend/app/core/config.py` — flip `osa_coordinator_enabled:125`, `osa_xbow_families_enabled:101`, `osa_kali_backend_enabled:99`, `osa_flow_ui_enabled:93`, and the new `osa_xbow_autonomous_enabled` from False → True **only after** `tests/e2e/test_scanme_real_docker_recon.py` is green in CI.
  - Keep deterministic lane reachable when Ollama is down or `osa_llm_provider="anthropic"`/deterministic.
- **Acceptance criteria (cross-cutting, made concrete):**
  - **With flags ON, the saved-workflow lane still emits an `audit_log` + `agent_execution` trace that passes the LIVE differential harness and `assert_no_coordinator_in_saved_workflow_trace`** — i.e. the deterministic demo lane remains byte-identical even under default-ON, including `agent_execution` rows (which flag-gating, not `EXCLUDED_AUDIT_PREFIXES`, protects).
  - `skip_coordinator_replay` / `osa_coordinator_replay_enabled:126` / `osa_coordinator_populate_on_replay:132` keep the deterministic lane selectable as offline fallback.
  - Full backend suite stays green (baseline ~995); new behavior test-gated.
- **Safety/replay invariant:** flip is the LAST PR, gated on the E2E milestone; replay regression (LIVE harness + fixture comparator) must remain green under the new defaults or the flip is reverted.

---

## 5. Risks and Mitigations

| Risk | Mitigation | Named test / gate |
|------|------------|-------------------|
| **Real Docker exec on the autonomous path runs with egress monitor / kill-registration / rescope pause absent (DOMINANT)** | PR2 extracts the single `execute_tool_through_safety_chain` RUNTIME helper (verbatim move) running the full runtime envelope; PR4 routes `_dispatch_tool` through it; PR0 spy + structural AST guard make parity structural | `test_safety_chain_full_envelope_spy.py`, `test_egress_kill_fires_on_autonomous_path.py`, `test_kill_switch_registration_on_autonomous_path.py`, `test_autonomous_new_host_pauses_for_rescope.py`, `test_adapter_execute_only_via_safety_helper.py` |
| Tier gate missing on Performer dispatch | Tier gate is per-lane: added to the per-dispatch filter trio in `_dispatch_tool` (PR4); deterministic lane keeps `service.py:274`; no redundant gate in `PlanExecutor` | `test_autonomous_tier_gate_blocks_unapproved.py`, `test_autonomous_dispatch_runs_filter_trio_per_dispatch.py` |
| Rescope human-approval pause missing on autonomous lane (D4) | Rescope harvest + `pause_for_rescope` inside the shared runtime helper (PR2); PR4 wires findings through it | `test_autonomous_new_host_pauses_for_rescope.py` |
| Shim-block audit missing on autonomous lane | `SafetyViolation`/`persist_kali_shim_block` inside the shared runtime helper (PR2) | `test_shim_block_audit_on_autonomous_path.py` |
| **Folding plan-time filters into a per-step helper drifts the deterministic audit trace (the prior-draft trap)** | Plan-time filter trio stays at plan cardinality in `service.py:268-291`; only runtime brakes move (verbatim) into the helper; LIVE differential harness gates every PR | `test_planexecutor_refactor_byte_identical.py` (LIVE before/after), `test_planexecutor_uses_shared_helper.py` |
| **The existing fixture comparator cannot catch a `PlanExecutor` refactor drift** | PR0 BUILDS a LIVE differential harness that runs the real pipeline before/after and feeds `audit_log` + `agent_execution` rows into the comparator | `test_planexecutor_refactor_byte_identical.py` |
| **autonomous `agent_execution` rows leak into / alter the deterministic golden set when flags OFF** (agent_execution NOT covered by `EXCLUDED_AUDIT_PREFIXES`) | All new behavior default-OFF; explicit assertion that no autonomous `AgentExecution` rows appear with flags off | `test_deterministic_lane_unchanged_with_xbow_off.py` |
| **Structural guard rests on a false premise** (existing `test_no_direct_backend_calls.py` only walks imports, not `adapter.execute` call sites) | New guard walks `ast.Call` nodes for adapter-`.execute()` call sites, scoped to the runtime helper; PR0 corrects the existing guard's false docstring | `test_adapter_execute_only_via_safety_helper.py`, `test_no_direct_backend_calls.py` |
| **EgressMonitor has no construction site on the `_dispatch_tool` path** | Construct ONE session-scoped `EgressMonitor` per Performer session (seeded with session `whitelist_rules`), threaded into each dispatch — one per session, not per dispatch | `test_egress_kill_fires_on_autonomous_path.py`, `test_kill_switch_registration_on_autonomous_path.py` |
| Byte-identical replay drift (new lane mutates shared state) | All new behavior default-OFF; LIVE harness + fixture comparator run every PR; lazy seed registration | `test_v11_byte_identical.py`, `test_seed_xbow_isolation.py`, `test_deterministic_lane_unchanged_with_xbow_off.py` |
| Ollama unreachable / non-JSON / hangs | Net-new loop catches `ModelUnreachable` + parse failures → fail safe + audit; turn/wall caps | `test_autonomous_ollama_unreachable_fails_safe.py`, `test_ollama_tool_envelope_parse_failure.py`, `test_autonomous_iteration_cap_hit.py` |
| Blocked interview starves the Performer concurrency lease | Interview runs OUTSIDE the `_PerformerLease`; lease acquired only at dispatch | `test_interview_does_not_starve_lease.py`, `test_interview_inline_wait.py` |
| Direct docker import / out-of-helper adapter.execute escapes guards | `performer.py` calls the helper, never imports docker or calls adapter.execute directly; two AST guards (one import-level, one call-site) | `test_no_direct_backend_calls.py`, `test_adapter_execute_only_via_safety_helper.py` |
| Scrubber assumed-but-not-firing live | PR9 asserts scrubber on live path | `test_scrubber_runs_on_live_path.py` |
| Real Docker exec destabilizes default CI | scanme E2E is `@pytest.mark.docker` opt-in; flag flip gated on it | `test_scanme_real_docker_recon.py` |
| Worker Bash hook blocked at sub-agent level | Lead runs pytest + commits; workers Write-only per PR | execution-protocol note (below) |

## 6. Verification Steps
1. Per PR: Lead runs `pytest backend/tests` (unit+integration+safety+ast+regression); the LIVE differential harness, the fixture comparator, and both AST guards must be green.
2. PR2: confirm `PlanExecutor.execute` refactor is byte-identical via the LIVE before/after harness (real pipeline run feeding `audit_log` + `agent_execution` rows), and that the plan-time filter trio did NOT move; the adapter-exec structural guard flips to passing.
3. PR1: dev + prod WS handshake reaches `/api/v1/ws/sessions/...`; Monitor receives live events.
4. PR4: confirm the per-dispatch filter trio (incl. the newly-added tier gate) runs on the autonomous path AND the session-scoped `EgressMonitor` is constructed once per session; spy + tier-gate tests green.
5. PR4/PR7: run the opt-in `tests/e2e/test_scanme_real_docker_recon.py` (requires Docker + built `osa-agent-*` images + reachable Ollama); confirm the full chain (per-dispatch filter trio/tier + runtime egress/kill-reg/rescope/shim-audit) fires on the live run.
6. PR9: full-envelope spy exercised on a live autonomous run; confirm scrubber fires.
7. PR10: re-run full suite under default-ON flags; confirm the LIVE harness + `assert_no_coordinator_in_saved_workflow_trace` still pass and the deterministic fallback stays selectable; baseline ~995 maintained.

## 7. Flag Dependency Note (default-OFF → default-ON per D5)
- **Stay OFF through PR0–PR9:** `osa_coordinator_enabled` (`config.py:125`), `osa_flow_ui_enabled` (`:93`), `osa_xbow_families_enabled` (`:101`), `osa_kali_backend_enabled` (`:99`), new `osa_xbow_autonomous_enabled`.
- **`osa_llm_provider`** (`:143`) set to `"ollama"` for the autonomous lane (per-session or env), default `"anthropic"` preserved for legacy.
- **Flip ON in PR10 only after** `test_scanme_real_docker_recon.py` is green: the four XBOW flags + `osa_xbow_autonomous_enabled` → True. Replay-lane selectability preserved (`skip_coordinator_replay`, `osa_coordinator_replay_enabled:126`, `osa_coordinator_populate_on_replay:132`).
- **Worker execution constraint:** sub-agent Bash hook is blocked — the implementing **Lead** runs pytest + commits; worker sub-agents **Write only** (no shell/test/commit). Sequence each PR so Writes are batched, then Lead verifies + commits.

---

## ADR — Autonomous XBOW lane, additive over the deterministic fallback, through TWO safety seams (per-lane plan-time filters + ONE shared runtime helper)

- **Decision:** Build the XBOW autonomous loop by wiring + de-stubbing the existing Performer/Coordinator/role scaffolding (Option A), Ollama-driven, recon-autonomous / exploit-human-gated, with TWO structurally-distinct safety seams: (1) the plan-time filter trio (`filter_plan_steps → filter_by_tier_flags → RiskFilter`) kept at its current cardinality **per lane** — `service.py:268-291` for the deterministic lane (unchanged) and per-dispatch in `_dispatch_tool` for the autonomous lane; and (2) a single shared `execute_tool_through_safety_chain` **runtime helper** (the `executor.py:62-216` body moved verbatim: `adapter.execute` + egress + kill-reg + rescope + shim-audit) that BOTH `PlanExecutor.execute` and `_dispatch_tool` call for the actual container run — behind default-OFF flags flipped ON only after a real-Docker scanme E2E passes.
- **Drivers:** safety-regression risk dominates, and the dominant facet is RUNTIME brake-parity (egress + kill-registration + rescope), not the plan-time filters; the scaffolding is real but unwired; "done" = real Docker exec, not fixtures.
- **Alternatives considered:**
  - **Monolithic single-helper (the prior draft's design) — REJECTED.** It folded the plan-time filter trio AND the runtime brakes into one per-step helper. Verified incompatible with byte-identical replay: the filter trio runs once-per-plan in `service.py:268-291` and emits plan-level audit rows (`steps_blocked` `:294-301`, `persist_kali_blocked_steps` `:282-288`); moving it per-step changes which rows are emitted, in what order, and how many. Replaced by the two-seam split.
  - **B (new parallel orchestrator) — rejected;** it creates a THIRD divergent execution path and doubles the safety-audit surface, whereas Option A + the shared runtime helper already delivers a single clean runtime choke point.
  - **C (flip flags as-is) — rejected;** verified zero callers, deferred exec (`performer.py:320-323`), broken WS path, and absent live brakes.
- **Why chosen:** smallest reviewable diff per PR; preserves byte-identical replay because the deterministic lane's plan-time filter rows do not move and the runtime brake code is moved verbatim; **makes runtime-brake parity a structural property enforced by a call-site AST guard, not manual vigilance**, by collapsing the two divergent runtime paths into one audited choke point — while keeping the tier gate a documented per-lane invariant so `PlanExecutor` gains no redundant second gate that would itself perturb the deterministic trace.
- **Explicit safety delta (corrected from the prior draft):** `_dispatch_tool` today contains ONLY `filter_plan_steps` + `RiskFilter` (plan-time). ABSENT until this plan lands: the per-dispatch tier gate (`filter_by_tier_flags`), and the runtime envelope (`EgressMonitor.monitor_log_line` + `KillSwitch`, container-ID kill registration, rescope harvest + `pause_for_rescope`, `persist_kali_shim_block` audit). This plan adds the tier gate to the per-dispatch filter trio and the runtime envelope via the shared runtime helper — not piecemeal, and NOT by relocating the deterministic lane's plan-time filters.
- **Verification correction (BLOCKING fix):** the existing `tests/regression/test_v11_byte_identical.py` is a pure fixture self-comparison and does NOT run `PlanExecutor.execute`/`OrchestratorService.run`; it cannot catch a refactor drift. PR0 builds `test_planexecutor_refactor_byte_identical.py` as a LIVE before/after differential feeding `audit_log` AND `agent_execution` rows into the comparator. `agent_execution` rows are NOT covered by `EXCLUDED_AUDIT_PREFIXES` and are protected only by flag-gating, asserted by `test_deterministic_lane_unchanged_with_xbow_off.py`.
- **Consequences:** the runtime-helper refactor touches `PlanExecutor.execute` and must stay byte-identical (gated by the LIVE harness every PR); the tier gate is a per-lane invariant enforced by tests rather than physical co-location; the `EgressMonitor` is session-scoped on the autonomous path (one per session); the net-new Ollama tool-use loop (JSON envelope schema + parse/`ModelUnreachable` handling + caps) is a real build cost on top of single-shot `OllamaClient.send`; the new lane carries the full-envelope spy + call-site structural guard + LIVE replay harness on every PR.
- **Follow-ups (milestone 2):** dedicated exploit-validator agent (C5); multi-target scope; full Kali backend breadth; widened egress DPI; cloud/multi-provider LLM + per-user credential routing.

### Open Questions
- [ ] Exact `frontend/src/pages/CoordinatorPage` ConversationTab file path + the messages-endpoint shape for the blocking interview reply — confirm at PR5 implementation.
- [ ] Whether `headless/mitmproxy/interactsh` are in-scope for the recon milestone or documented out-of-scope (AC4 permits either) — decide before PR7.
- [ ] Whether the flag flip (PR10) keys off a single master `osa_xbow_autonomous_enabled` or flips the four legacy flags independently — affects fallback selectability.
- [ ] Confirm the chosen lease mechanism for the blocking interview (interview-outside-lease) survives the ADR-003 cap under concurrent sessions — validate at PR5 with `test_interview_does_not_starve_lease.py`.
- [ ] Confirm `whitelist_rules` provenance for the session-scoped autonomous `EgressMonitor` (same resolution path `PlanExecutor` uses at `executor.py:34`, or a session-config source) — resolve before PR4.
- [ ] Decide whether to NARROW the existing `test_no_direct_backend_calls.py:13` docstring to "import-level guard" or EXTEND that test to also walk call sites (vs delegating call-site coverage to the new guard) — resolve in PR0.
