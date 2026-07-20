# RALPLAN-DR: OSA → XBOW Autonomous Pentest — Milestone 1 (single-safe-target E2E)

- **Status:** pending approval
- **Branch:** `feat/kali-coexistence-v1` (cut PR branches `feat/xbow-autonomous-*` off this)
- **Mode:** DELIBERATE consensus (RALPLAN-DR) — high-risk: live autonomous tool execution against a real network target.
- **Source spec:** `.omc/specs/deep-interview-osa-xbow-autonomous-pentest.md` (ambiguity 14%, PASSED)
- **Milestone target:** a single safe target — `scanme.nmap.org` — runs an end-to-end autonomous loop with REAL Docker recon-tool execution, Ollama-driven agent reasoning, recon-autonomous / exploit-human-gated, additive over the preserved deterministic/no-LLM fallback lane.

> **⚠ Expert consensus was NOT fully reached within the max consensus cycles.** The final Architect review is BLOCKING and the final Critic verdict is REJECT, both for the SAME single root cause: the prior draft diagnosed the "verbatim 62-216 move" trap in prose but did not propagate the fix into its NORMATIVE sections (Principle 2, Option A, the PR2 spec, the Risk table, and the ADR still asserted a literal verbatim move). This revision propagates the two reviewers' required fix into every normative section and acceptance criterion. The plan is now "one focused revision past" the rejection in the reviewers' own words, but because the rejection was issued against the prior text and a fresh adversarial pass was not run within the cycle budget, this is submitted for human approval rather than auto-advanced. **Residual open concerns the approver should weigh** are listed in [§0 Residual Open Concerns](#0-residual-open-concerns) immediately below.

---

## 0. Residual Open Concerns (consensus not fully reached)

These are the items the final review round flagged and this revision addresses on paper but that were NOT re-validated by a fresh adversarial pass. Each is a sign-off gate, not a blocker to starting PR0/PR1 (which are pure test/frontend additions).

1. **Helper-boundary correctness (was the BLOCKING/REJECT root cause).** This revision redefines `execute_tool_through_safety_chain` to own ONLY `get_adapter().execute` + the four runtime brakes and to RETURN structured results, leaving the `AgentExecution` lifecycle and all `tasks`/`terminal`/`agents` publishes in each caller. This is the reviewers' prescribed fix, but it has not been re-reviewed against the live code after rewording. **Gate: the implementer must confirm at PR2 that no `AgentExecution` row-creation/finalization site moves and that the LIVE harness diffs `agent_execution` row count AND creation-order, not only `audit_log`.**
2. **AST guard feasibility is asserted, not proven.** `get_adapter()` returns a dynamically-typed object; `ast` cannot resolve a receiver's type. The chosen heuristic is pinned in PR0 (below) but its false-positive/negative envelope is unmeasured. **Gate: PR0 must demonstrate the heuristic on the real tree before PR2 flips the xfail.**
3. **C7 chain decomposition needs an explicit safety-reviewer sign-off.** No single function ever runs the full spec-ordered chain end-to-end; the immutable-chain invariant is now a distributed, test-enforced property. This is correct and necessary for replay, but it changes the invariant's nature and a safety reviewer must consciously accept it.
4. **`whitelist_rules` provenance on the autonomous path** is now pulled into PR4 scope as a hard precondition (no longer deferred), but the exact source has not been selected. A wrong source silently disables egress filtering on the only live-exec path.
5. **PR4 was split** (PR4a safety-only, PR4b Ollama loop) per the reviewers' recommendation; the split has not been re-reviewed for hidden coupling between the per-dispatch tier gate and the role-loop de-stub.

---

> **Revision note (consensus rounds 1–3).** The round-1 draft asserted a single monolithic `execute_tool_through_safety_chain` helper that ran BOTH the plan-time filter trio (`filter_plan_steps → filter_by_tier_flags → RiskFilter`) AND the runtime brakes per step. Architect + Critic proved this incompatible with byte-identical replay: the filter trio runs ONCE PER PLAN in `OrchestratorService.run` (`service.py:268` filter_plan_steps, `:274` filter_by_tier_flags, `:291` RiskFilter) and emits plan-level audit rows before the executor loop (`steps_blocked` summary at `service.py:294-301`; per-slug `persist_kali_blocked_steps` at `service.py:282-288`), whereas `PlanExecutor.execute` (`executor.py:37-225`) loops per-step and runs ONLY the runtime brakes (egress `:77-81`, kill-reg `:68-74`, rescope `:167-206`, shim-audit `:103-133`) and never calls the filter trio. Round 2 adopted the two-seam split (plan-time filters per-lane + a runtime helper) — but still described the runtime helper as the `executor.py:62-216` body "moved verbatim," and round 3 (the final review) proved THAT framing is ALSO incoherent.
>
> **Why "62-216 verbatim" is wrong (verified against `executor.py`).** The `AgentExecution` lifecycle straddles the claimed boundary and is interleaved with the runtime brakes — it is NOT cleanly contained in 62-216:
> - row CREATION + `agent_started` `tasks` publish: `executor.py:42-59` (ABOVE line 62);
> - container-ID kill registration (brake): `:68-74`;
> - egress monitor (brake): `:77-81`;
> - per-event `terminal`/`agents` publishes: `:91-96`;
> - `SafetyViolation` shim-block audit (brake) INTERLEAVED with row-`failed` update + `agent_failed` publish: `:103-133`;
> - terminal `status`/`output_json` finalization: `:117-161` (BELOW the egress block);
> - rescope harvest + `pause_for_rescope` (brake): `:167-206`;
> - `agent_completed` `tasks` publish: `:218-223` (OUTSIDE the 62-216 range).
>
> A literal "move 62-216 into a helper both callers invoke" therefore relocates `AgentExecution` status-finalization (`:117-161`) and the `tasks`/`terminal`/`agents` publishes into the helper while leaving row creation (`:42-51`) behind — splitting the lifecycle across the boundary incoherently. `compare_agent_execution_rows` (`v11_comparator.py:170-204`) diffs exactly this surface by row count/order (`:176-178`), slug, normalised_args, exit_code, parsed_findings_canonical, and started_at. So the relocation is a replay hazard the "verbatim" wording HID.
>
> **The fix (now adopted, round 3 — replaces all "verbatim 62-216" language).**
> 1. **Plan-time filtering stays where it is, at its current cardinality.** `filter_plan_steps → filter_by_tier_flags → RiskFilter` remains in `OrchestratorService.run` (`service.py:268-291`) for the deterministic lane (unchanged ⇒ byte-identical). For the autonomous lane the SAME trio runs per-dispatch in `_dispatch_tool` (`performer.py:295-309` already does `filter_plan_steps` + `RiskFilter`; PR4a ADDS `filter_by_tier_flags(session.approval_flags)` there).
> 2. **The runtime helper owns ONLY the inner per-adapter-call envelope and RETURNS structured results.** `execute_tool_through_safety_chain` owns `get_adapter().execute` + the four runtime brakes — per-log egress + kill (mirror `executor.py:77-81`), container-ID kill registration (mirror `:68-74`), rescope harvest + `pause_for_rescope` (mirror `:167-206`), and `SafetyViolation`/`persist_kali_shim_block` shim-block audit (mirror `:103-133`) — and returns a result object (`findings, container_id, killed, paused, safety_violation`). It does NOT create, update, or finalize `AgentExecution` rows, and it does NOT emit the `tasks`/`terminal`/`agents` topic publishes.
> 3. **`AgentExecution` row creation, status/output_json finalization, and the `tasks`/`terminal`/`agents` publishes STAY in EACH caller's loop.** `PlanExecutor.execute` keeps its exact row lifecycle (`:42-51`, `:117-161`) and publishes (`:54-59`, `:91-96`, `:218-223`) — so its trace is byte-identical BY CONSTRUCTION (no row-creation site moves). `_dispatch_tool` adds its OWN `AgentExecution` creation + publishes around the same helper, satisfying C2's persistence goal. The duplication of the *lifecycle wrapper* is intentional and is the price of replay safety; the *brake code* is the only thing shared.
>
> **Only the inner `adapter.execute` call + the four brake bodies are byte-identical "verbatim"** — the surrounding `AgentExecution` lifecycle is deliberately NOT centralized. The structural AST guard scopes its invariant to `adapter.execute` appearing ONLY inside the runtime helper (still achievable — the inner call IS verbatim), while row creation is explicitly NOT centralized. The tier gate is a documented per-lane invariant (plan-time in `service.py:274` for deterministic; per-dispatch in `_dispatch_tool` for autonomous), enforced by tests, NOT by physical co-location.
>
> **C7 decomposition surfaced for sign-off (not buried):** the spec's single immutable chain (`filter_plan_steps → filter_by_tier_flags → RiskFilter → shims → backend hardening → IMAGE_REGEX`) is intentionally decomposed into (plan-time filter trio, per-lane) + (runtime brake helper). NO single function runs the full spec-ordered chain end-to-end; the immutable-chain invariant is now a distributed, test-enforced property asserted by `test_safety_chain_full_envelope_spy.py`. This requires explicit safety-reviewer sign-off (Residual Concern #3).

---

## 1. RALPLAN-DR Summary

### Principles
1. **Additive over rip-and-replace.** Every new autonomous behavior lands behind a default-OFF flag beside the existing deterministic lane; the deterministic Coordinator + legacy `PlanExecutor` + no-LLM demo lane stay byte-identical-green throughout. The byte-identical guarantee has TWO distinct enforcement surfaces, and the plan does NOT conflate them: (a) the **static fixture comparator** (`tests/_regression/v11_comparator.py`: `compare_audit_log_rows:117`, `compare_agent_execution_rows:170`, `assert_no_coordinator_in_saved_workflow_trace:207`), today exercised only by `tests/regression/test_v11_byte_identical.py`, which loads `golden_*.json` and compares them to themselves/poisoned copies — it **never runs `PlanExecutor.execute` or `OrchestratorService.run`** and therefore **cannot, by itself, catch a `PlanExecutor` refactor drift**; and (b) a NEW **live differential harness** (`tests/regression/test_planexecutor_refactor_byte_identical.py`, built in PR0) that runs the real saved-workflow pipeline and feeds its emitted rows into the same comparator functions. Critically, the agent_execution comparison (`v11_comparator.py:170-204`) is **NOT** covered by `EXCLUDED_AUDIT_PREFIXES` (which only filters `audit_log` actions via `is_excluded_action`); `agent_execution` rows are the real replay-exposure surface and are protected ONLY by flag-gating (asserted by `test_deterministic_lane_unchanged_with_xbow_off.py`) AND by the fact that **no `AgentExecution` row-creation/finalization site moves** in the PR2 refactor. (D5)
2. **The full runtime brake envelope is a hard invariant, enforced structurally through ONE shared runtime helper that owns ONLY the inner adapter-call envelope — NOT the plan-time filters and NOT the `AgentExecution` lifecycle.** No autonomous tool call reaches Docker except through the shared `execute_tool_through_safety_chain` helper, which owns the live runtime brakes that today live ONLY inside `PlanExecutor.execute`'s loop: `get_adapter().execute` through shims/IMAGE_REGEX, per-log `EgressMonitor.monitor_log_line` + `KillSwitch` (mirror `executor.py:77-81`), container-ID kill-switch registration (mirror `:68-74`), rescope-on-new-hosts harvest + `RescopeService.pause_for_rescope` (mirror `:167-206`), and `SafetyViolation`/`persist_kali_shim_block` audit (mirror `:103-133`). The helper **RETURNS structured results** (findings, container_id, killed/paused flags, safety-violation); it does **NOT** create/update/finalize `AgentExecution` rows and does **NOT** emit the `tasks`/`terminal`/`agents` publishes — those stay in each caller. The plan-time filter trio (`filter_plan_steps → filter_by_tier_flags → RiskFilter`) is **NOT** inside this helper — it stays at plan-time cardinality per lane (Principle 3). A NEW structural guard (`tests/ast/test_adapter_execute_only_via_safety_helper.py`) asserts `get_adapter().execute(...)` is invoked only inside the runtime helper. `tests/ast/test_no_direct_backend_calls.py` stays green. (D4, C7)
3. **Tier gate is a per-lane invariant with a single source of truth per lane — NOT inside the runtime helper.** Deterministic lane: the tier gate stays at `service.py:274` (`filter_by_tier_flags`), unchanged. Autonomous lane: the tier gate runs per-dispatch inside `_dispatch_tool` against `session.approval_flags`, added alongside the existing `filter_plan_steps` + `RiskFilter` (`performer.py:295-309`). `PlanExecutor` does **not** gain a redundant second tier-gate pass (which would itself perturb the deterministic audit trace). Recon is autonomous; any active-exploit-tier step blocks on `session.approval_flags`; a new-host discovery on the autonomous lane triggers `RescopeService.pause_for_rescope` (inside the runtime helper) and halts on pending approval, exactly as the legacy lane does. (D4)
4. **Local Ollama only; reuse the client object — the agentic loop is net-new.** All agent reasoning routes through the already-built `OllamaClient` (`ollama_client.py`, `ModelClient.send`-compatible, `format="json"`, strips `<think>`, raises `ModelUnreachable`). Note explicitly: `OllamaClient.send` is a **single-shot `format=json` request/response with no native tool-call structure and no loop**; the envelope-driven tool-use loop (emit JSON tool envelope → `delegate_tool_call` → read result → iterate to done/cap) is **net-new machinery layered on single-shot calls**. No new cloud-LLM dependency. (D3)
5. **Land low-risk and invariant-preserving first.** CI guards, the live differential harness, the WS-path fix (C6), the runtime-envelope spy harness, and the runtime-helper refactor land before any new autonomous behavior, so each subsequent PR is verified against a green, observable baseline with a single audited runtime choke point already in place.

### Decision Drivers (top 3)
1. **Safety regression risk dominates — and the dominant facet is runtime brake-parity, not the plan-time filters.** The platform's only real asset today is the safety control-plane. The worst outcome is **real Docker exec against scanme with the egress monitor, kill-switch registration, and rescope pause silently absent** — four of the five live runtime brakes live ONLY in `PlanExecutor.execute`, none in `_dispatch_tool`. `runtime_delegator.py:16-17` literally advertises `tier_gating + egress_monitor + RescopeService` as the brakes on a path that has none of them. Drives the shared RUNTIME helper + the full-envelope spy harness + the structural AST guard.
2. **The autonomous core is ~85% unbuilt but the scaffolding is real.** `Performer.run_session`, `_dispatch_tool` (partial chain), `OllamaClient`, role classes, and `_materialize_families` all exist with zero/partial live callers. Drives a wiring-and-de-stub plan, not a greenfield build.
3. **"Done" = real Docker exec against scanme, not fixtures.** `_dispatch_tool` step 5–7 (`adapter.execute`) is explicitly deferred (`performer.py:320-323`, "wired in P4"). The real-exec bridge — routed through the shared runtime helper — is the milestone's crux and gates the flag flip.

### Viable Options

**Option A — Wire-and-de-stub the existing scaffolding, with TWO safety seams: per-lane plan-time filters + ONE shared runtime helper that owns only the inner adapter-call envelope (CHOSEN).**
Reuse `Performer.run_session`, `_dispatch_tool`, `runtime_delegator.delegate_tool_call`, `OllamaClient`, the role classes, and `_materialize_families`; inject Ollama into the role loops; **extract a single `execute_tool_through_safety_chain` runtime helper that owns ONLY `get_adapter().execute` + the four runtime brakes and RETURNS structured results — the `AgentExecution` lifecycle and all topic publishes STAY in each caller** (so `PlanExecutor`'s replay-anchoring rows do not relocate); both `PlanExecutor.execute` and `Performer._dispatch_tool` call the helper for the actual container run, each wrapping it in their own `AgentExecution` lifecycle; keep the plan-time filter trio at its current cardinality per lane (`service.py:268-291` for deterministic; `_dispatch_tool` per-dispatch for autonomous); complete the real-adapter exec inside the runtime helper; derive dispatch from the LLM Understanding.

- **Explicit brake inventory for `_dispatch_tool` *today* (so reviewers size the real safety delta):**
  - PRESENT (plan-time filters, per-dispatch): `filter_plan_steps` (`performer.py:295`), `RiskFilter` (`performer.py:302`).
  - ABSENT (plan-time): `filter_by_tier_flags` (tier gate) — added per-dispatch in PR4a.
  - ABSENT (runtime): `adapter.execute` itself (step 5–7 deferred at `performer.py:320-323`), `EgressMonitor.monitor_log_line` + `KillSwitch`, container-ID kill-switch registration, rescope harvest + `RescopeService.pause_for_rescope`, `SafetyViolation`/`persist_kali_shim_block` audit — all delivered via the shared runtime helper in PR2/PR4b. `runtime_delegator.py:16-17` literally names `tier_gating + egress_monitor + RescopeService` as the brakes — all absent from the path it invokes today.
  - ABSENT (lifecycle): `_dispatch_tool` returns a plain dict today (`performer.py:324-334`) and does NOT create an `AgentExecution` row; PR4b adds its OWN row creation + finalization + publishes AROUND the helper (the helper does not own them) to satisfy C2's persistence goal.
- Pros: smallest diff per PR; preserves byte-identical replay because (i) the deterministic lane's plan-time filter rows do NOT move, (ii) **no `AgentExecution` row-creation/finalization site moves** (the helper does not touch the lifecycle), and (iii) the runtime brake CODE is moved verbatim into the helper; the shared runtime helper makes runtime brake-parity a **structural** invariant enforced by a guard, not manual vigilance; matches the "additive" constraint exactly; one audited runtime choke point instead of two divergent ones.
- Cons: the runtime-helper refactor touches `PlanExecutor.execute`, so it must be gated by the LIVE differential harness on every PR (mitigated: PR0 builds that harness diffing BOTH `audit_log` AND `agent_execution` rows; it runs each PR); the `AgentExecution` lifecycle wrapper is duplicated between `PlanExecutor` and `_dispatch_tool` rather than centralized — this is intentional (the price of not relocating the replay anchor) but means the persistence logic has two sites to keep in sync; the net-new Ollama tool-use loop machinery is a real build cost (JSON envelope schema + parse/`ModelUnreachable` handling + caps); the tier gate is a documented per-lane invariant, not physically co-located in the runtime helper (mitigated by `test_autonomous_tier_gate_blocks_unapproved.py`).

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
Root cause risk: the live runtime envelope (`EgressMonitor.monitor_log_line` + kill at `executor.py:77-81`, container-ID kill registration at `executor.py:68-74`, rescope harvest + `pause_for_rescope` at `executor.py:167-206`, `persist_kali_shim_block` at `executor.py:103-133`) lives ONLY inside `PlanExecutor.execute`'s loop. If the autonomous lane runs `adapter.execute` via the old `_dispatch_tool` ad-hoc block, an autonomous recon step would run a real container against scanme with **no per-log egress monitoring, no container registered for the kill switch, and no rescope human-approval pause** — a safety-control-plane bypass on the one path that executes live tools.
- Mitigation: PR2 extracts `execute_tool_through_safety_chain` as the single RUNTIME execution choke point running the four runtime brakes and RETURNING structured results; PR0's spy harness asserts egress + kill-registration + rescope-harvest fire on **every** autonomous dispatch; a structural/AST guard (walking `ast.Call` nodes for `<x>.execute()` where `<x>` is bound from `get_adapter(...)` in the same function, NOT imports) asserts `adapter.execute` is never called except through the helper.
- Named tests: `tests/safety/test_safety_chain_full_envelope_spy.py`, `tests/safety/test_egress_kill_fires_on_autonomous_path.py`, `tests/safety/test_kill_switch_registration_on_autonomous_path.py`, `tests/safety/test_autonomous_new_host_pauses_for_rescope.py`, `tests/ast/test_adapter_execute_only_via_safety_helper.py`.

**Scenario 2 — A wiring change silently bypasses the tier gate; an active-exploit step runs against scanme without approval.**
Root cause risk: today `_dispatch_tool` runs `filter_plan_steps` + `RiskFilter` but NOT `filter_by_tier_flags` (verified `performer.py:295,302`); the legacy lane runs the tier gate at `service.py:274`. The tier gate is **per-lane** (not inside the runtime helper), so the autonomous lane must add it explicitly.
- Mitigation: PR4a adds `filter_by_tier_flags(session.approval_flags)` per-dispatch in `_dispatch_tool` (alongside the existing filter trio at `performer.py:295-309`); the deterministic lane keeps its gate at `service.py:274` unchanged; an active-tier dispatch without the flag is blocked on the autonomous lane.
- Named tests: `tests/safety/test_autonomous_tier_gate_blocks_unapproved.py`, `tests/safety/test_safety_chain_full_envelope_spy.py`.

**Scenario 3 — Byte-identical replay drifts because the runtime-helper refactor relocated an `AgentExecution` row-creation/finalization site or changed `PlanExecutor.execute`'s audit trace — and the existing fixture comparator fails to catch it.**
Root cause risk: PR2 refactors `PlanExecutor.execute` to call the runtime helper. The trap (proved by both reviewers): if the helper is mis-scoped to own the `AgentExecution` lifecycle, row CREATION moves to a new place/order relative to the deterministic trace, and `compare_agent_execution_rows` (`v11_comparator.py:170-204`) diffs row count/order/slug/args/exit_code/findings. The existing `test_v11_byte_identical.py` is a PURE FIXTURE test (loads `golden_*.json`, compares to itself/poisoned copies, lines 35-107) and **never runs the live pipeline**, so it cannot detect this drift. Separately, `seed_xbow._register_all()` mutates `ROLE_REGISTRY`.
- Mitigation: the helper is scoped to NOT touch the `AgentExecution` lifecycle (no row-creation site moves — replay byte-identical by construction); PR0 BUILDS `tests/regression/test_planexecutor_refactor_byte_identical.py` as a **LIVE differential harness** that runs the real saved-workflow pipeline before AND after the refactor and feeds BOTH emitted `audit_log` AND `agent_execution` row sets into `compare_audit_log_rows` + `compare_agent_execution_rows`, **explicitly asserting `agent_execution` row COUNT and creation-ORDER are unchanged**; PR2's refactor is required to keep this green; the plan-time filter rows do NOT move; `seed_xbow` registration stays lazy (`tests/ast/test_seed_xbow_isolation.py`).
- Named tests: `tests/regression/test_planexecutor_refactor_byte_identical.py` (LIVE before/after, every PR, diffs agent_execution count+order), `tests/regression/test_deterministic_lane_unchanged_with_xbow_off.py`, `tests/regression/test_v11_byte_identical.py` (fixture self-check, retained), `tests/ast/test_seed_xbow_isolation.py`.

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
- `tests/unit/test_runtime_helper_runs_full_envelope.py` — `execute_tool_through_safety_chain` invokes (in order) `get_adapter().execute` through shims/IMAGE_REGEX → per-log egress + kill → kill-registration → rescope harvest/pause → shim-block audit, and RETURNS a result object — and does NOT create/finalize any `AgentExecution` row nor emit `tasks`/`terminal`/`agents` publishes (those are the caller's; the plan-time filter trio is asserted separately at its call sites).

### Integration
- `tests/integration/test_performer_full_cycle.py` (extend) — `run_session` invoked from the live orchestrator path with Ollama-backed roles (mocked client), executing through the shared runtime helper, with `_dispatch_tool` creating/finalizing its own `AgentExecution` rows around the helper.
- `tests/integration/test_planexecutor_uses_shared_helper.py` — `PlanExecutor.execute` routes every step's container run through `execute_tool_through_safety_chain` while keeping its `AgentExecution` row creation (`:42-51`) and finalization (`:117-161`) in its own loop (refactor verification); the plan-time filter trio stays in `service.py` at plan cardinality.
- `tests/integration/test_autonomous_dispatch_runs_filter_trio_per_dispatch.py` — the autonomous lane runs `filter_plan_steps → filter_by_tier_flags → RiskFilter` per `_dispatch_tool` call (the per-lane plan-time filter location for the autonomous path).
- `tests/integration/test_dispatch_tool_persists_agent_execution.py` — `_dispatch_tool` creates AND finalizes its OWN `AgentExecution` row around the helper (the helper does not), satisfying C2's MsgChain/agent_execution persistence goal.
- `tests/integration/test_coordinator_safety_chain.py` (extend) — full envelope on the autonomous path: per-dispatch filter trio + tier gate, then runtime helper egress/kill-reg/rescope.
- `tests/integration/test_autonomous_dispatch_from_understanding.py` — Understanding → `_materialize_families` → roles actually queried/driven.
- `tests/integration/test_autonomous_ollama_unreachable_fails_safe.py` — `ModelUnreachable` → clean fail + audit row.
- `tests/integration/test_interview_inline_wait.py` — messages endpoint round-trips a blocking interview answer **while the Performer lease is released** (no concurrency starvation).
- `tests/integration/test_interview_does_not_starve_lease.py` — a blocked interview turn does not hold `_active_performers`, so a second session can acquire the lease.

### E2E
- `tests/e2e/test_ws_auth_relay_loop.py` — WebSocket auth + topic relay loop (none exists today; AC6 requirement).
- `tests/e2e/test_scanme_real_docker_recon.py` — **milestone gate**, marked `@pytest.mark.docker`/`@pytest.mark.e2e` (opt-in, not in default suite): full session against `scanme.nmap.org` runs real `osa-agent-nmap:latest` (+ one of nuclei/httpx/subfinder) **through the shared runtime helper**, produces real findings with evidence tags, exploit-tier steps stay blocked without `approval_flags`, and a synthetic new-host finding pauses for rescope.

### Safety / Observability / Replay
- `tests/regression/test_planexecutor_refactor_byte_identical.py` — **LIVE differential harness** (NOT a fixture self-check): runs the real saved-workflow pipeline before AND after the PR2 refactor, feeding BOTH emitted `audit_log` AND `agent_execution` row sets into `compare_audit_log_rows` + `compare_agent_execution_rows`. Asserts zero drift, **including `agent_execution` row COUNT and creation-ORDER** (the surface a mis-scoped helper would perturb). This is the harness the prior draft falsely assumed already existed.
- `tests/regression/test_deterministic_lane_unchanged_with_xbow_off.py` — with all `osa_*` flags False, a live deterministic run's `audit_log` AND `agent_execution` rows match the golden set; explicitly asserts the autonomous lane's per-step `AgentExecution` rows do NOT appear / do NOT alter `compare_agent_execution_rows` when flags are OFF (agent_execution is NOT covered by `EXCLUDED_AUDIT_PREFIXES`, so flag-gating is its only protection).
- `tests/safety/test_safety_chain_full_envelope_spy.py` — spy asserts the FULL ordered chain on the autonomous path: per-dispatch `filter_plan_steps → filter_by_tier_flags → RiskFilter` (plan-time, in `_dispatch_tool`) THEN the runtime helper's `shims → IMAGE_REGEX → egress → kill-reg → rescope-harvest → shim-audit`. Also documents that NO single function runs the full spec-ordered chain end-to-end (the C7 decomposition).
- `tests/safety/test_egress_kill_fires_on_autonomous_path.py` — a poisoned log line on the autonomous path triggers `KillSwitch` via `monitor_log_line`.
- `tests/safety/test_kill_switch_registration_on_autonomous_path.py` — the container ID is registered for the kill switch on the autonomous path.
- `tests/safety/test_autonomous_new_host_pauses_for_rescope.py` — a new-host discovery on the autonomous lane calls `RescopeService.pause_for_rescope` and halts on pending approval (D4).
- `tests/safety/test_shim_block_audit_on_autonomous_path.py` — a `SafetyViolation` on the autonomous path persists a kali shim-block audit row.
- `tests/safety/test_autonomous_tier_gate_blocks_unapproved.py` — an active-exploit-tier dispatch without `session.approval_flags` is blocked by the per-dispatch tier gate in `_dispatch_tool`.
- `tests/ast/test_adapter_execute_only_via_safety_helper.py` — structural guard. **Pinned receiver-resolution heuristic (Residual Concern #2):** walk `ast.Call` nodes; flag any call to an attribute named `execute` whose receiver is a `Name` bound from `get_adapter(...)` within the SAME function body (assignment-tracked), OR, as the simpler fallback the guard MUST fall back to if assignment-tracking proves brittle, assert the literal token `get_adapter(` appears only in `safety_exec.py` + `registry.py`. The chosen rule and its documented false-positive/negative envelope are recorded in PR0. Asserts such calls appear ONLY inside `execute_tool_through_safety_chain`. NOTE: the existing `tests/ast/test_no_direct_backend_calls.py:13` docstring falsely claims it checks "AgentAdapter.execute directly" but its implementation (lines 45-68) only walks `ast.Import`/`ast.ImportFrom` for docker/backend symbols — this new guard supplies the call-site check the existing one does not, and PR0 corrects the false docstring.
- `tests/safety/test_scrubber_runs_on_live_path.py` — `ConversationScrubber` invoked when Performer is live.
- `tests/integration/test_conversation_topic_live_producer.py` — Performer role turns publish to `conversation` + `raw_conversation` and persist to `MsgChain`.
- Metric assertions on `conversation_topic_dropped_events_total` token-bucket behavior.

---

## 4. Wave / PR Sequence

> Ordering rationale: invariant-preserving + low-risk first (PR0 LIVE differential harness + full-envelope spy + corrected/pinned structural guard, PR1 WS-path C6, **PR2 runtime-helper refactor — the single audited RUNTIME choke point lands before any new autonomous behavior**), then the autonomous core inside-out (C2 engine/Ollama → C1 interview → C3 dispatch → C4 real exec), then hardening (C5/C7), then the flag flip. **PR4 is split** (per the reviewers' recommendation) into PR4a (pure-safety: live-path wiring + per-dispatch tier gate + helper-wiring + own AgentExecution lifecycle, spy-verified) and PR4b (Ollama tool-use-loop de-stub), so a safety regression is not entangled with LLM-loop bugs in one reviewable unit. Every PR keeps the LIVE differential harness, fixture comparator, and both AST guards green; each new behavior is default-OFF until PR10.

---

### PR0 — LIVE differential replay harness + full-envelope spy + pinned structural adapter-exec guard + CI baseline (C7 prep, no behavior change)
- **Goal:** make the FULL live runtime envelope observable and asserted, and (critically) BUILD the live differential replay harness the prior plan falsely assumed existed, before any wiring change.
- **C-components:** C7 (prep), cross-cutting.
- **Files:**
  - `tests/regression/test_planexecutor_refactor_byte_identical.py` (new) — **LIVE differential harness**: drives the real saved-workflow pipeline (`OrchestratorService.run` / `PlanExecutor.execute`) end-to-end, captures emitted `audit_log` AND `agent_execution` rows, and feeds them into `compare_audit_log_rows` + `compare_agent_execution_rows`. **Adds an explicit assertion that `agent_execution` row COUNT and creation-ORDER are unchanged** (not just shape). Authored to pass against the PRE-refactor code so it is a true before/after differential in PR2. (BLOCKING fix: the existing `test_v11_byte_identical.py` is fixture-only and cannot catch a refactor drift.)
  - `tests/safety/test_safety_chain_full_envelope_spy.py` (new) — spy/monkeypatch asserting the autonomous-path ordered chain: per-dispatch `filter_plan_steps → filter_by_tier_flags → RiskFilter` THEN runtime helper `shims → IMAGE_REGEX → EgressMonitor.monitor_log_line → container-kill registration → rescope harvest → shim-audit`. Documents the C7 decomposition (no single function runs the full spec-ordered chain).
  - `tests/ast/test_adapter_execute_only_via_safety_helper.py` (new) — AST guard with the **pinned receiver-resolution heuristic** (see §3): flag `.execute` on a name bound from `get_adapter(...)` in the same function, with the `get_adapter(`-token-location fallback; document the chosen rule + its false-positive/negative envelope IN THIS PR. Asserts adapter-`.execute(...)` appears only inside `execute_tool_through_safety_chain`. Authored now asserting the intended invariant (`xfail`-marked until PR2 introduces the helper, then flipped to passing in PR2). **Gate: the heuristic must be demonstrated on the real tree in this PR before PR2 flips the xfail (Residual Concern #2).**
  - `tests/ast/test_no_direct_backend_calls.py` — **correct the false docstring** at line 13 (it claims to check `AgentAdapter.execute directly` but only walks imports); narrow the docstring to "import-level docker/backend symbol guard" — the plan delegates the call-site check to the new guard above and reconciles the two explicitly.
  - `tests/regression/test_deterministic_lane_unchanged_with_xbow_off.py` (new) — default-OFF flags ⇒ live deterministic `audit_log` + `agent_execution` rows byte-identical; explicit assertion that no autonomous `AgentExecution` rows leak into the golden set (agent_execution NOT covered by `EXCLUDED_AUDIT_PREFIXES`).
  - Reuse: `tests/regression/test_v11_byte_identical.py`, `tests/_regression/v11_comparator.py`, `tests/ast/test_no_direct_backend_calls.py`.
- **Acceptance criteria:**
  - The LIVE differential harness runs the real pipeline and is green against pre-refactor code (so a PR2 drift would turn it red), AND asserts `agent_execution` row count + creation-order.
  - Spy harness fails loudly if ANY chain stage (per-dispatch filter trio incl. tier gate, OR runtime egress/kill-reg/rescope) is skipped or reordered.
  - With all `osa_*` flags False, both the live differential harness and `test_deterministic_lane_unchanged_with_xbow_off.py` are byte-identical (green), including `agent_execution` rows.
  - Existing AST guard green and its docstring corrected; the new adapter-exec structural guard is authored with a documented heuristic + envelope (`xfail` until PR2, then flipped to passing in PR2).
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

### PR2 — Extract the shared RUNTIME helper `execute_tool_through_safety_chain` (inner adapter-call envelope only) + refactor `PlanExecutor` onto it (C7 core, BLOCKING fix — two-seam synthesis, helper-boundary corrected)
- **Goal:** create ONE audited RUNTIME execution choke point (adapter.execute + the four runtime brakes only, returning structured results), and prove the deterministic lane is byte-identical over it via the LIVE harness before any autonomous caller exists. **The plan-time filter trio is explicitly NOT moved, and the `AgentExecution` lifecycle is explicitly NOT moved.**
- **C-components:** C7 (the structural fix the Architect + Critic both require, in its corrected helper-boundary form).
- **Helper boundary (the BLOCKING decision, now made explicit):** the helper owns ONLY the inner per-adapter-call envelope and RETURNS a result; it does NOT own the `AgentExecution` lifecycle.
  - **INSIDE the helper:** `get_adapter(...).execute(...)` through shims/IMAGE_REGEX; the `async for` over its events; per-log `EgressMonitor.monitor_log_line` + `KillSwitch` (mirror `executor.py:77-81`); container-ID kill-switch registration (mirror `:68-74`); rescope harvest + `RescopeService.pause_for_rescope` (mirror `:167-206`); `SafetyViolation`/`persist_kali_shim_block` shim-block audit (mirror `:103-133`). It RETURNS a structured result `{findings, container_id, killed, paused, safety_violation}`.
  - **STAYS in EACH caller:** `AgentExecution` row creation (`executor.py:42-51`), the `agent_started` `tasks` publish (`:54-59`), the per-event `terminal`/`agents` publishes (`:91-96`), the terminal `status`/`output_json` finalization (`:117-161`), and the `agent_completed` `tasks` publish (`:218-223`). `PlanExecutor` keeps these EXACTLY where they are — its trace is byte-identical by construction. `_dispatch_tool` adds its OWN equivalents around the same helper (PR4b).
- **Files (file:line):**
  - `backend/app/orchestrator/safety_exec.py` (new) — `async def execute_tool_through_safety_chain(step, target, *, whitelist_rules, egress_monitor, kill_switch, container_kill_registry, rescope_service, audit, db, session_id, actor_id) -> SafetyExecResult` running, in order: `get_adapter(...).execute(...)` through shims/IMAGE_REGEX → per-log `EgressMonitor.monitor_log_line` + `KillSwitch` → container-ID kill-switch registration → rescope harvest + `RescopeService.pause_for_rescope` → `SafetyViolation`/`persist_kali_shim_block` audit, RETURNING `{findings, container_id, killed, paused, safety_violation}`. **It does NOT create/update/finalize `AgentExecution` rows and does NOT emit `tasks`/`terminal`/`agents` publishes** (the caller owns those). **The plan-time filter trio (`filter_plan_steps`/`filter_by_tier_flags`/`RiskFilter`) is NOT a parameter of and NOT called by this helper** — it stays at plan-time cardinality per lane. This helper is the ONLY place `adapter.execute` may be called.
  - `backend/app/orchestrator/executor.py:37-225` — refactor `PlanExecutor.execute` so the per-step container run delegates to `execute_tool_through_safety_chain(...)` and consumes its returned result, while **leaving row creation (`:42-51`), all topic publishes, and status/output_json finalization (`:117-161`) in place, unmoved.** **No `AgentExecution` row-creation or finalization site moves.** **The plan-time filter trio stays exactly where it is in `OrchestratorService.run` (`service.py:268-291`) at plan cardinality — it is NOT pulled into the per-step loop.** **MUST keep the saved-workflow `audit_log` AND `agent_execution` traces byte-identical** (same rows, same order, same count, same shapes) — gated by the LIVE differential harness every PR.
  - `backend/app/orchestrator/service.py:268-291` — UNCHANGED for the deterministic lane: `filter_plan_steps` (`:268`) → `filter_by_tier_flags` (`:274`) → `RiskFilter` (`:291`) still run once per plan and emit the `steps_blocked` summary (`:294-301`) + `persist_kali_blocked_steps` rows (`:282-288`). Explicitly documented so reviewers confirm no plan-level audit row moves.
  - Reuse: `safety/egress_monitor.py`, `safety/risk_filter.py`, `safety/whitelist.py`, `rescope.py`, `kali_allowlist.persist_kali_shim_block`. (`safety/exploit_allowlist.filter_by_tier_flags` is NOT touched here — it stays at its plan-time call site `service.py:274`.)
- **Acceptance criteria (strengthened per both reviewers):**
  - `PlanExecutor.execute` routes every step's container run through the helper; **no `adapter.execute` call remains outside `safety_exec.py`.**
  - **No `AgentExecution` row-creation site moves; `PlanExecutor` still creates AND finalizes its `AgentExecution` rows in its own loop.**
  - The plan-time filter trio is verifiably unmoved (`service.py:268-291` still owns it; no per-step filter call added to `PlanExecutor`).
  - `tests/regression/test_planexecutor_refactor_byte_identical.py` (the LIVE before/after harness from PR0) is green — explicitly a before/after live-pipeline run feeding `audit_log` AND `agent_execution` rows into the comparator, **and explicitly asserting `agent_execution` row COUNT and creation-ORDER are unchanged across the refactor** — NOT a fixture self-comparison.
  - `tests/ast/test_adapter_execute_only_via_safety_helper.py` (from PR0) flips from `xfail` to passing.
  - `tests/unit/test_runtime_helper_runs_full_envelope.py` asserts the runtime envelope order AND that the helper does NOT touch the `AgentExecution` lifecycle or emit topic publishes (filter trio asserted separately at its call sites).
- **Safety/replay invariant:** behavior-preserving refactor of the deterministic lane only; runtime brake code moved verbatim into the helper, plan-time filters AND the `AgentExecution` lifecycle unmoved; no new lane yet; the LIVE differential harness green every PR (incl. agent_execution count+order) or the refactor is reverted.

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

### PR4a — Wire Performer into the live path through the shared runtime helper + per-dispatch tier gate + own AgentExecution lifecycle (C2, PURE-SAFETY half — no Ollama loop yet)
- **Goal (safety-only, spy-verified BEFORE any LLM-loop bug can entangle it):** `Performer.run_session` runs from `OrchestratorService.run` (XBOW lane); `_dispatch_tool` runs the per-dispatch filter trio (incl. the newly-added tier gate), delegates the real container run to `execute_tool_through_safety_chain`, and creates/finalizes its OWN `AgentExecution` row around the helper — so the autonomous path inherits the FULL envelope (per-lane tier gate + the helper's egress, kill-reg, rescope, shim-audit) AND persists agent_execution rows. Roles still return fixtures here (the live Ollama loop lands in PR4b).
- **C-components:** C2 (closes the tier-gate + egress + kill-reg + rescope + agent_execution-persistence gaps in the Performer path via the per-lane gate + shared runtime helper + caller-owned lifecycle).
- **EgressMonitor lifecycle + `whitelist_rules` provenance (BLOCKING resolution — session-scoped, pulled IN-scope as a hard precondition per the reviewers):** `PlanExecutor` constructs ONE `EgressMonitor` per `execute()` call seeded with `whitelist_rules` (`executor.py:34`; constructor `egress_monitor.py:17-27` takes `session_id` + `whitelist_rules`). `_dispatch_tool` has NO `whitelist_rules` in scope and is called per-tool-call. **Resolution: construct ONE `EgressMonitor` per Performer session** (seeded with the session's `whitelist_rules`) and thread it into every `_dispatch_tool` call for that session — one monitor per session, NOT per dispatch. The session-scoped monitor (plus kill switch + container-kill registry + `RescopeService`) is passed as the helper's runtime params on each call. **`whitelist_rules` provenance is a hard precondition of THIS PR (Residual Concern #4, no longer deferred):** resolve it from the same path `PlanExecutor` uses at session start (`executor.py:34`) or a documented session-config source; a wrong source silently disables egress filtering on the only live-exec path, so PR4a MUST NOT merge without the provenance pinned at the session-construction site.
- **Files (file:line):**
  - `backend/app/orchestrator/service.py:103-318` — add an XBOW-lane branch (new flag `osa_xbow_autonomous_enabled`, default False) that constructs a `Performer`, resolves the session's `whitelist_rules`, constructs the session-scoped `EgressMonitor`/kill switch/container-kill registry/`RescopeService`, and calls `run_session` (legacy `PlanExecutor` preserved when flag off).
  - `backend/app/orchestrator/performer.py:295-309` — **ADD `filter_by_tier_flags(session.approval_flags)` to the per-dispatch filter trio**, alongside the existing `filter_plan_steps` (`:295`) + `RiskFilter` (`:302`). This is the per-lane tier gate for the autonomous path (the deterministic lane keeps its gate at `service.py:274`; `PlanExecutor` gains NO redundant gate).
  - `backend/app/orchestrator/performer.py:320-334` — replace the deferred step 5–7 stub: `_dispatch_tool` now (a) CREATES its own `AgentExecution` row, (b) calls `execute_tool_through_safety_chain(...)` (the SAME runtime helper `PlanExecutor` uses), passing the session-scoped egress monitor, kill switch, container-kill registry, and `RescopeService`, (c) FINALIZES the row from the returned result, and (d) emits its own topic publishes. **The runtime envelope (egress monitor, kill-switch registration, rescope harvest, shim-audit) fires inside the helper; the tier gate fires in the per-dispatch filter trio above; the `AgentExecution` lifecycle is owned by `_dispatch_tool` (not the helper)** — satisfying C2's persistence goal without relocating `PlanExecutor`'s rows.
  - `backend/app/orchestrator/runtime_delegator.py:32` — its `_dispatch_tool` target now carries the per-dispatch tier gate + the runtime helper (resolves the `runtime_delegator.py:16-17` brake-contract mismatch).
  - Reuse: `performer._publish_role_turn` (scrubber + topics already wired).
- **Acceptance criteria (AC2.x, safety half):**
  - `Performer.run_session` has a live (non-test) app caller behind the XBOW flag.
  - **Per-dispatch filter trio runs on the autonomous path** (`filter_plan_steps → filter_by_tier_flags → RiskFilter`) — asserted by `test_autonomous_dispatch_runs_filter_trio_per_dispatch.py`; the tier gate blocks an unapproved active-exploit dispatch.
  - **Runtime envelope fires on the autonomous path** (asserted by the PR0 spy now exercised live): a poisoned log line triggers `KillSwitch`; the container ID is registered for the kill switch; a synthetic new-host finding pauses for rescope; a `SafetyViolation` persists a shim-block audit row. The session-scoped `EgressMonitor` is constructed once per session (with pinned `whitelist_rules` provenance) and threaded into each dispatch.
  - **`_dispatch_tool` persists its OWN `AgentExecution` rows** around the helper (`test_dispatch_tool_persists_agent_execution.py`), and the helper does not.
  - **autonomous `agent_execution` rows do not collide with the deterministic golden set when flags are OFF** — `test_deterministic_lane_unchanged_with_xbow_off.py` (extended) asserts no autonomous `AgentExecution` rows leak (agent_execution NOT covered by `EXCLUDED_AUDIT_PREFIXES`).
  - Named tests: `test_autonomous_tier_gate_blocks_unapproved.py`, `test_autonomous_dispatch_runs_filter_trio_per_dispatch.py`, `test_dispatch_tool_persists_agent_execution.py`, `test_egress_kill_fires_on_autonomous_path.py`, `test_kill_switch_registration_on_autonomous_path.py`, `test_autonomous_new_host_pauses_for_rescope.py`, `test_shim_block_audit_on_autonomous_path.py`, `test_deterministic_lane_unchanged_with_xbow_off.py`.
- **Safety/replay invariant:** entire branch behind `osa_xbow_autonomous_enabled` default False; the autonomous path shares the SAME audited RUNTIME choke point as the deterministic lane and runs the same filter trio per-dispatch; the LIVE differential harness + `test_deterministic_lane_unchanged_with_xbow_off.py` stay green with the flag off; **no Ollama loop is introduced here, so a safety regression cannot be entangled with an LLM-loop bug.**

---

### PR4b — De-stub roles into net-new Ollama tool-use loops (C2, on top of the spy-verified safety wiring)
- **Goal:** with PR4a's safety wiring already spy-verified, replace the role fixtures with net-new Ollama tool-use loops that drive `_dispatch_tool` (which already routes through the helper + tier gate).
- **C-components:** C2.
- **Files (file:line):**
  - `backend/app/orchestrator/roles/pentester.py:88-101` — replace smoke fixture `run()` with a net-new Ollama tool-use loop: emit a JSON tool-call envelope → `runtime_delegator.delegate_tool_call` → read result → iterate to `done` or `IterationCapHit`. **Define the envelope schema** (`{"tool": str, "intent": str, "config": {...}}` or `{"done": true, "summary": str}`); parse-failure and `ModelUnreachable` both route to clean session-fail + audit; turn cap + wall-clock cap enforced (first-class, not a footnote).
  - `backend/app/orchestrator/roles/adviser.py:46-63` — replace static message with an Ollama guidance call (preserve trigger semantics).
  - `backend/app/orchestrator/runtime_delegator.py:32` — invoked from the live Pentester loop (the dispatch target already carries the gate + helper from PR4a).
- **Acceptance criteria (AC2.x, LLM half):**
  - Pentester/Adviser/Generator + family roles run live Ollama loops (no fixture envelopes when client present).
  - At least one agent reads another agent's output via shared `Performer.context` / `delegate_tool_call` and adapts; inter-agent messages publish to `conversation` and persist to `MsgChain`.
  - **Ollama tool-use loop is first-class:** envelope schema defined; non-JSON / `ModelUnreachable` → clean fail + audit; turn + wall-clock caps trip `IterationCapHit`.
  - Named tests: `test_pentester_live_tool_loop.py`, `test_ollama_tool_envelope_parse_failure.py`, `test_autonomous_iteration_cap_hit.py`, `test_autonomous_ollama_unreachable_fails_safe.py`.
- **Safety/replay invariant:** still behind `osa_xbow_autonomous_enabled` default False; PR4a's safety spy harness remains green (the LLM loop only changes WHAT is dispatched, not the brake envelope around dispatch).

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
  - `backend/app/orchestrator/safety_exec.py` — the real `adapter.execute` path lands here (already the only legal call site from PR2); the autonomous lane reaches it via `_dispatch_tool` (PR4a). No new `adapter.execute` call site is introduced in `performer.py`.
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
  - Exploit-tier steps remain blocked without `approval_flags`; **rescope still pauses for human approval — backed by the real implementation in PR2's runtime helper + PR4a's autonomous wiring** (`test_autonomous_new_host_pauses_for_rescope.py`), not a vacuous criterion.
  - **Safety-reviewer sign-off recorded for the C7 chain decomposition** (Residual Concern #3): no single function runs the full spec-ordered chain end-to-end; the immutable-chain invariant is a distributed, test-enforced property.
- **Safety/replay invariant:** hardening + verification only; replay green; AST guards green.

---

### PR10 — Flag flip to default-ON after verification + final ADR confirmation (cross-cutting, D5)
- **Goal:** flip the XBOW flags default-ON once the scanme E2E passes; keep the deterministic lane reachable as offline fallback; confirm the ADR.
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
| **Real Docker exec on the autonomous path runs with egress monitor / kill-registration / rescope pause absent (DOMINANT)** | PR2 extracts the single `execute_tool_through_safety_chain` RUNTIME helper (inner adapter-call envelope only; returns results) running the four runtime brakes; PR4a routes `_dispatch_tool` through it; PR0 spy + structural AST guard make parity structural | `test_safety_chain_full_envelope_spy.py`, `test_egress_kill_fires_on_autonomous_path.py`, `test_kill_switch_registration_on_autonomous_path.py`, `test_autonomous_new_host_pauses_for_rescope.py`, `test_adapter_execute_only_via_safety_helper.py` |
| **Helper mis-scoped to own the `AgentExecution` lifecycle → row creation/order relocates → replay drift (the round-3 BLOCKING root cause)** | Helper owns ONLY `adapter.execute` + 4 brakes and RETURNS results; `AgentExecution` creation/finalization + all topic publishes STAY in each caller; `PlanExecutor` byte-identical by construction; LIVE harness diffs agent_execution COUNT + ORDER | `test_planexecutor_refactor_byte_identical.py` (asserts agent_execution count+order), `test_planexecutor_uses_shared_helper.py`, `test_runtime_helper_runs_full_envelope.py`, `test_dispatch_tool_persists_agent_execution.py` |
| Tier gate missing on Performer dispatch | Tier gate is per-lane: added to the per-dispatch filter trio in `_dispatch_tool` (PR4a); deterministic lane keeps `service.py:274`; no redundant gate in `PlanExecutor` | `test_autonomous_tier_gate_blocks_unapproved.py`, `test_autonomous_dispatch_runs_filter_trio_per_dispatch.py` |
| Rescope human-approval pause missing on autonomous lane (D4) | Rescope harvest + `pause_for_rescope` inside the shared runtime helper (PR2); PR4a wires findings through it | `test_autonomous_new_host_pauses_for_rescope.py` |
| Shim-block audit missing on autonomous lane | `SafetyViolation`/`persist_kali_shim_block` inside the shared runtime helper (PR2) | `test_shim_block_audit_on_autonomous_path.py` |
| **Folding plan-time filters into a per-step helper drifts the deterministic audit trace (the round-1 trap)** | Plan-time filter trio stays at plan cardinality in `service.py:268-291`; only runtime brakes move into the helper; LIVE differential harness gates every PR | `test_planexecutor_refactor_byte_identical.py` (LIVE before/after), `test_planexecutor_uses_shared_helper.py` |
| **The existing fixture comparator cannot catch a `PlanExecutor` refactor drift** | PR0 BUILDS a LIVE differential harness that runs the real pipeline before/after and feeds `audit_log` + `agent_execution` rows into the comparator | `test_planexecutor_refactor_byte_identical.py` |
| **autonomous `agent_execution` rows leak into / alter the deterministic golden set when flags OFF** (agent_execution NOT covered by `EXCLUDED_AUDIT_PREFIXES`) | All new behavior default-OFF; explicit assertion that no autonomous `AgentExecution` rows appear with flags off | `test_deterministic_lane_unchanged_with_xbow_off.py` |
| **Structural guard rests on a false premise** (existing `test_no_direct_backend_calls.py` only walks imports, not `adapter.execute` call sites) AND **its receiver-resolution is non-trivial** (`get_adapter()` is dynamically typed; `ast` cannot type-resolve the receiver) | New guard pins a heuristic — flag `.execute` on a name bound from `get_adapter(...)` in the same function, with the `get_adapter(`-token-location fallback; document the false-pos/neg envelope; demonstrate on the real tree in PR0 before PR2 flips xfail; PR0 corrects the existing guard's false docstring | `test_adapter_execute_only_via_safety_helper.py`, `test_no_direct_backend_calls.py` |
| **EgressMonitor has no construction site on the `_dispatch_tool` path; `whitelist_rules` provenance unresolved** | Construct ONE session-scoped `EgressMonitor` per Performer session (seeded with session `whitelist_rules`), threaded into each dispatch; **`whitelist_rules` provenance pinned IN PR4a scope** (same path `PlanExecutor` uses, or documented session-config source) — a wrong source silently disables egress filtering | `test_egress_kill_fires_on_autonomous_path.py`, `test_kill_switch_registration_on_autonomous_path.py` |
| **C7 spec chain decomposed → no single function runs the full ordered chain** | Surfaced explicitly (not buried); invariant becomes a distributed, test-enforced property; safety-reviewer sign-off recorded at PR9 | `test_safety_chain_full_envelope_spy.py` |
| Byte-identical replay drift (new lane mutates shared state) | All new behavior default-OFF; LIVE harness + fixture comparator run every PR; lazy seed registration | `test_v11_byte_identical.py`, `test_seed_xbow_isolation.py`, `test_deterministic_lane_unchanged_with_xbow_off.py` |
| Ollama unreachable / non-JSON / hangs | Net-new loop catches `ModelUnreachable` + parse failures → fail safe + audit; turn/wall caps | `test_autonomous_ollama_unreachable_fails_safe.py`, `test_ollama_tool_envelope_parse_failure.py`, `test_autonomous_iteration_cap_hit.py` |
| Blocked interview starves the Performer concurrency lease | Interview runs OUTSIDE the `_PerformerLease`; lease acquired only at dispatch | `test_interview_does_not_starve_lease.py`, `test_interview_inline_wait.py` |
| Direct docker import / out-of-helper adapter.execute escapes guards | `performer.py` calls the helper, never imports docker or calls adapter.execute directly; two AST guards (one import-level, one call-site) | `test_no_direct_backend_calls.py`, `test_adapter_execute_only_via_safety_helper.py` |
| **Safety regression entangled with LLM-loop bug in one reviewable unit** | PR4 split: PR4a lands the per-dispatch tier gate + helper-wiring + own agent_execution lifecycle (pure safety, no Ollama) and is spy-verified BEFORE PR4b de-stubs the Ollama tool-use loop | PR4a spy suite green before PR4b merges |
| Scrubber assumed-but-not-firing live | PR9 asserts scrubber on live path | `test_scrubber_runs_on_live_path.py` |
| Real Docker exec destabilizes default CI | scanme E2E is `@pytest.mark.docker` opt-in; flag flip gated on it | `test_scanme_real_docker_recon.py` |
| Worker Bash hook blocked at sub-agent level | Lead runs pytest + commits; workers Write-only per PR | execution-protocol note (below) |

## 6. Verification Steps
1. Per PR: Lead runs `pytest backend/tests` (unit+integration+safety+ast+regression); the LIVE differential harness, the fixture comparator, and both AST guards must be green.
2. PR2: confirm `PlanExecutor.execute` refactor is byte-identical via the LIVE before/after harness (real pipeline run feeding `audit_log` + `agent_execution` rows, asserting agent_execution COUNT + creation-ORDER), confirm **no `AgentExecution` row-creation site moved**, confirm the plan-time filter trio did NOT move; the adapter-exec structural guard flips to passing.
3. PR1: dev + prod WS handshake reaches `/api/v1/ws/sessions/...`; Monitor receives live events.
4. PR4a: confirm the per-dispatch filter trio (incl. the newly-added tier gate) runs on the autonomous path, the session-scoped `EgressMonitor` is constructed once per session (with pinned `whitelist_rules` provenance), and `_dispatch_tool` persists its OWN `AgentExecution` rows; spy + tier-gate tests green BEFORE PR4b.
5. PR4b: confirm the Ollama tool-use loop drives dispatch and fails safe on `ModelUnreachable`/parse-failure/cap; PR4a's spy suite still green.
6. PR4/PR7: run the opt-in `tests/e2e/test_scanme_real_docker_recon.py` (requires Docker + built `osa-agent-*` images + reachable Ollama); confirm the full chain (per-dispatch filter trio/tier + runtime egress/kill-reg/rescope/shim-audit) fires on the live run.
7. PR9: full-envelope spy exercised on a live autonomous run; confirm scrubber fires; record safety-reviewer sign-off on the C7 decomposition.
8. PR10: re-run full suite under default-ON flags; confirm the LIVE harness + `assert_no_coordinator_in_saved_workflow_trace` still pass and the deterministic fallback stays selectable; baseline ~995 maintained.

## 7. Flag Dependency Note (default-OFF → default-ON per D5)
- **Stay OFF through PR0–PR9:** `osa_coordinator_enabled` (`config.py:125`), `osa_flow_ui_enabled` (`:93`), `osa_xbow_families_enabled` (`:101`), `osa_kali_backend_enabled` (`:99`), new `osa_xbow_autonomous_enabled`.
- **`osa_llm_provider`** (`:143`) set to `"ollama"` for the autonomous lane (per-session or env), default `"anthropic"` preserved for legacy.
- **Flip ON in PR10 only after** `test_scanme_real_docker_recon.py` is green: the four XBOW flags + `osa_xbow_autonomous_enabled` → True. Replay-lane selectability preserved (`skip_coordinator_replay`, `osa_coordinator_replay_enabled:126`, `osa_coordinator_populate_on_replay:132`).
- **Worker execution constraint:** sub-agent Bash hook is blocked — the implementing **Lead** runs pytest + commits; worker sub-agents **Write only** (no shell/test/commit). Sequence each PR so Writes are batched, then Lead verifies + commits.

---

## 8. ADR — Autonomous XBOW lane, additive over the deterministic fallback, through TWO safety seams (per-lane plan-time filters + ONE shared runtime helper that owns only the inner adapter-call envelope)

- **Decision:** Build the XBOW autonomous loop by wiring + de-stubbing the existing Performer/Coordinator/role scaffolding (Option A), Ollama-driven, recon-autonomous / exploit-human-gated, with TWO structurally-distinct safety seams: (1) the plan-time filter trio (`filter_plan_steps → filter_by_tier_flags → RiskFilter`) kept at its current cardinality **per lane** — `service.py:268-291` for the deterministic lane (unchanged) and per-dispatch in `_dispatch_tool` for the autonomous lane; and (2) a single shared `execute_tool_through_safety_chain` **runtime helper that owns ONLY the inner per-adapter-call envelope** (`get_adapter().execute` + egress + kill-reg + rescope + shim-audit) and **RETURNS structured results** — BOTH `PlanExecutor.execute` and `_dispatch_tool` call it for the actual container run, each wrapping it in their OWN `AgentExecution` lifecycle (the helper does not create/finalize rows or emit topic publishes) — behind default-OFF flags flipped ON only after a real-Docker scanme E2E passes.
- **Drivers:** safety-regression risk dominates, and the dominant facet is RUNTIME brake-parity (egress + kill-registration + rescope), not the plan-time filters; the scaffolding is real but unwired; "done" = real Docker exec, not fixtures.
- **Alternatives considered:**
  - **Monolithic single-helper (the round-1 draft's design) — REJECTED.** It folded the plan-time filter trio AND the runtime brakes into one per-step helper. Verified incompatible with byte-identical replay: the filter trio runs once-per-plan in `service.py:268-291` and emits plan-level audit rows (`steps_blocked` `:294-301`, `persist_kali_blocked_steps` `:282-288`); moving it per-step changes which rows are emitted, in what order, and how many. Replaced by the two-seam split.
  - **"Move `executor.py:62-216` verbatim into the helper" framing (the round-2 draft's wording) — REJECTED.** Verified against `executor.py`: the `AgentExecution` lifecycle straddles 42-161 and is interleaved with the runtime brakes (creation `:42-51` above the range; finalization `:117-161` and `tasks`/`terminal`/`agents` publishes inside/around the range). A literal verbatim move would relocate row creation/finalization relative to the deterministic trace, and `compare_agent_execution_rows` (`v11_comparator.py:170-204`) diffs exactly that surface by count/order/slug/args/exit_code/findings — a silent replay hazard. Replaced by the corrected boundary: the helper owns ONLY the inner adapter-call + the four brakes and returns results; the lifecycle stays in each caller.
  - **B (new parallel orchestrator) — rejected;** it creates a THIRD divergent execution path and doubles the safety-audit surface, whereas Option A + the shared runtime helper already delivers a single clean runtime choke point.
  - **C (flip flags as-is) — rejected;** verified zero callers, deferred exec (`performer.py:320-323`), broken WS path, and absent live brakes.
- **Why chosen:** smallest reviewable diff per PR; preserves byte-identical replay because (i) the deterministic lane's plan-time filter rows do not move, (ii) **no `AgentExecution` row-creation/finalization site moves** (the helper does not touch the lifecycle), and (iii) the runtime brake code is moved verbatim into the helper; **makes runtime-brake parity a structural property enforced by a call-site AST guard, not manual vigilance**, by collapsing the two divergent runtime paths into one audited choke point — while keeping the tier gate a documented per-lane invariant so `PlanExecutor` gains no redundant second gate that would itself perturb the deterministic trace.
- **Explicit safety delta (corrected from the prior drafts):** `_dispatch_tool` today contains ONLY `filter_plan_steps` + `RiskFilter` (plan-time) and returns a plain dict (no `AgentExecution` row). ABSENT until this plan lands: the per-dispatch tier gate (`filter_by_tier_flags`), the runtime envelope (`EgressMonitor.monitor_log_line` + `KillSwitch`, container-ID kill registration, rescope harvest + `pause_for_rescope`, `persist_kali_shim_block` audit), AND its own `AgentExecution` persistence. This plan adds the tier gate to the per-dispatch filter trio, the runtime envelope via the shared runtime helper, and the `AgentExecution` lifecycle in `_dispatch_tool` itself — not piecemeal, and NOT by relocating the deterministic lane's plan-time filters or its `AgentExecution` rows.
- **Verification correction (BLOCKING fix):** the existing `tests/regression/test_v11_byte_identical.py` is a pure fixture self-comparison and does NOT run `PlanExecutor.execute`/`OrchestratorService.run`; it cannot catch a refactor drift. PR0 builds `test_planexecutor_refactor_byte_identical.py` as a LIVE before/after differential feeding `audit_log` AND `agent_execution` rows into the comparator and explicitly asserting `agent_execution` row COUNT + creation-ORDER. `agent_execution` rows are NOT covered by `EXCLUDED_AUDIT_PREFIXES` and are protected only by flag-gating (asserted by `test_deterministic_lane_unchanged_with_xbow_off.py`) plus the no-row-relocation guarantee.
- **C7 decomposition (surfaced for sign-off):** the spec's single immutable chain is intentionally decomposed into (plan-time filter trio, per-lane) + (runtime brake helper); NO single function runs the full spec-ordered chain end-to-end; the invariant becomes a distributed, test-enforced property asserted by `test_safety_chain_full_envelope_spy.py`. Safety-reviewer sign-off is recorded at PR9.
- **Consequences:** the runtime-helper refactor touches `PlanExecutor.execute` and must stay byte-identical (gated by the LIVE harness every PR, incl. agent_execution count+order); the `AgentExecution` lifecycle wrapper is duplicated between `PlanExecutor` and `_dispatch_tool` (intentional — the price of not relocating the replay anchor) and is two sites to keep in sync; the tier gate is a per-lane invariant enforced by tests rather than physical co-location; the immutable safety chain is a distributed, test-enforced property; the `EgressMonitor` is session-scoped on the autonomous path (one per session) and its `whitelist_rules` provenance is pinned in PR4a; the net-new Ollama tool-use loop (JSON envelope schema + parse/`ModelUnreachable` handling + caps) is a real build cost on top of single-shot `OllamaClient.send`; the new lane carries the full-envelope spy + call-site structural guard + LIVE replay harness on every PR.
- **Follow-ups (milestone 2):** dedicated exploit-validator agent (C5); multi-target scope; full Kali backend breadth; widened egress DPI; cloud/multi-provider LLM + per-user credential routing.

---

## 9. Changelog (what the consensus loop changed)

- **Round 1 → 2:** Rejected the monolithic single-helper (filters + brakes in one per-step function). Architect + Critic proved it re-cardinalizes the plan-time filter trio (once-per-plan in `service.py:268-291`) to per-step, drifting which/how-many plan-level audit rows are emitted. Adopted the two-seam split: plan-time filters stay per-lane at plan cardinality; only the runtime brakes become a shared helper.
- **Round 2 → 3 (this revision):** Rejected the "move `executor.py:62-216` verbatim" framing of the runtime helper. The final Architect (BLOCKING) and Critic (REJECT) both proved the `AgentExecution` lifecycle straddles that range (creation `:42-51`, finalization `:117-161`, `tasks`/`terminal`/`agents` publishes around the brakes) and that `compare_agent_execution_rows` diffs that surface — so a verbatim move silently relocates the replay anchor. Applied changes:
  1. **Helper boundary made explicit and replay-anchored** (Principle 2, Option A, PR2 spec, Risk table, ADR): the helper owns ONLY `get_adapter().execute` + the four runtime brakes and RETURNS structured results; `AgentExecution` creation/finalization + all topic publishes STAY in each caller. Removed "verbatim 62-216" everywhere it appeared.
  2. **PR2 acceptance criteria strengthened:** added "no `AgentExecution` row-creation site moves" and "`PlanExecutor` still creates and finalizes its rows in its own loop"; the LIVE harness now explicitly asserts `agent_execution` row COUNT + creation-ORDER, not just `audit_log`.
  3. **AST guard heuristic pinned** (PR0 / §3): flag `.execute` on a name bound from `get_adapter(...)` in the same function, with a `get_adapter(`-token-location fallback; document the false-positive/negative envelope and demonstrate on the real tree before PR2 flips the xfail. Existing `test_no_direct_backend_calls.py:13` false docstring narrowed to "import-level guard."
  4. **C7 chain decomposition surfaced** (Principle 2, PR9, ADR) for explicit safety-reviewer sign-off — no single function runs the full spec-ordered chain end-to-end.
  5. **Open Question #5 (whitelist_rules provenance) pulled INTO PR4a scope** as a hard precondition (no longer deferred/open).
  6. **PR4 split into PR4a (pure-safety wiring + per-dispatch tier gate + own AgentExecution lifecycle, spy-verified) and PR4b (Ollama tool-use-loop de-stub)** so a safety regression is not entangled with LLM-loop bugs in one reviewable unit.
  7. **`_dispatch_tool` now explicitly owns its OWN `AgentExecution` lifecycle** around the helper (new test `test_dispatch_tool_persists_agent_execution.py`), satisfying C2's persistence goal without relocating `PlanExecutor`'s rows.
  8. Added the **Residual Open Concerns** section (§0) and the **not-fully-reached** banner at the top; Status set to "pending approval."

### Open Questions
- [ ] Exact `frontend/src/pages/CoordinatorPage` ConversationTab file path + the messages-endpoint shape for the blocking interview reply — confirm at PR5 implementation.
- [ ] Whether `headless/mitmproxy/interactsh` are in-scope for the recon milestone or documented out-of-scope (AC4 permits either) — decide before PR7.
- [ ] Whether the flag flip (PR10) keys off a single master `osa_xbow_autonomous_enabled` or flips the four legacy flags independently — affects fallback selectability.
- [ ] Confirm the chosen lease mechanism for the blocking interview (interview-outside-lease) survives the ADR-003 cap under concurrent sessions — validate at PR5 with `test_interview_does_not_starve_lease.py`.
- [ ] Confirm `whitelist_rules` provenance for the session-scoped autonomous `EgressMonitor` (same resolution path `PlanExecutor` uses at `executor.py:34`, or a session-config source) — **now a hard precondition of PR4a, not deferrable.**
- [ ] Confirm the pinned AST-guard heuristic's false-positive/negative envelope on the real tree before PR2 flips the xfail (Residual Concern #2).
- [ ] Obtain explicit safety-reviewer sign-off on the C7 chain decomposition (distributed, test-enforced invariant) at PR9 (Residual Concern #3).
