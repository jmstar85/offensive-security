# Plan Verification — v3.1.3 (RALPLAN + Deep-Interview Lens)

**Date:** 2026-05-10
**Scope reviewed:** v2.1 baseline (implemented) + v3.0 base (`§0–§8`) + v3.1+v3.1.3 revisions (`§A–§T`)
**Reviewer:** Copilot CLI (Opus 4.7), session 272ff947
**Method:** Cross-read v2.1 source code (`backend/app/orchestrator/executor.py`, `safety/egress_monitor.py`, `core/events.py`) against amended specs. Then RALPLAN dimensions (Risk/Ambiguity/Logic/Pre-mortem/Acceptance/Naming) + deep-interview Contrarian/Simplifier challenge.

**Verdict:** **NEEDS REVISION** — 7 contradictions, 7 high-impact ambiguities, 13 medium-low ambiguities, 4 minor. Recommend Iteration 4 patch (`v3.1.4`) before implementation start. Plan is sound in approach but specs need tightening to be implementation-ready.

---

## Summary by Severity

| Severity | Count | Action |
|---|---|---|
| **HIGH (contradictions / blocking)** | 7 | Must amend before code |
| **HIGH-MED (security/correctness ambiguity)** | 7 | Amend before respective phase starts |
| **MED-LOW (operational ambiguity)** | 11 | Amend during phase, document explicitly |
| **LOW (minor)** | 4 | Track, fix opportunistically |

---

## A. Contradictions (HIGH — must resolve)

### A-1. Blackboard `version` semantics conflict
- **Where:** §A class spec ("monotonic") vs §T NEW-1 ("version counter is **advisory**; readers tolerate skew") vs §S `_has_new_observations` (uses `snapshot.version > _last_replan_version`).
- **Problem:** If version is advisory/skewed, §S comparison can miss a new observation tick (sub appended but version not yet bumped) → master never replans on that finding.
- **Fix:** Either keep version strictly monotonic (atomic increment under lock) OR change §S to use `sum(len(sub_events_for_sub)) - last_observed_total`. Pick one and update both §A docstring and §S code.

### A-2. Convergence detection (§I.1 #3) is not actually terminal
- **Where:** §I.1 says "master simply stops calling Claude" but §I.2 code uses `continue` in the loop. On the next supervisor tick, `_has_new_observations()` returns True if any sub appended → loop calls `_claude_replan` again → defeats convergence.
- **Fix:** Add `self._converged: bool = False` state; once set, gate all subsequent replans on it. Or: after convergence, advance `_last_replan_version` to current snapshot.version even though no Claude call was made.

### A-3. §D shim contradicts §T NEW-4
- **Where:** §D code uses `from app.agents._tools.nmap import NmapAdapter, *  # noqa: F401, F403`. §T NEW-4 explicitly amends to "no wildcard, explicit names only".
- **Fix:** Replace the §D code block with the §T NEW-4 form so a reader of §D alone follows the correct pattern.

### A-4. Column rename `whitelist_rules` → `scope_rules` not specified
- **Where:** v2.1 baseline `targets.whitelist_rules` (verified in `executor.py:30` and `egress_monitor.py:27`). v3.0 §5.1 says "`scope_rules JSONB` (existing column kept, semantics extended)" — but the existing column is named `whitelist_rules`, not `scope_rules`. v3.1 §J.1 lists `scope_rules JSONB` as an addition with semantics extended but does not include a RENAME COLUMN step.
- **Fix:** Either (a) Migration 003 explicitly `ALTER TABLE targets RENAME COLUMN whitelist_rules TO scope_rules`, OR (b) keep `whitelist_rules` name in code and update plan text. Choose one and fix all references.

### A-5. AC #4 (v3.0 §7) inconsistent with §J.2
- **Where:** v3.0 §7 AC #4: "Multi-domain session runs sub-orchestrators in parallel up to `concurrency_limit` (default 3); excess queued." v3.1 §J.2 moves this to `projects.max_concurrent_domains`.
- **Fix:** Update AC #4 text to use the new column name. Add to §N (AC clarifications).

### A-6. §Q exception scrubber `service.py` field reference incorrect
- **Where:** §Q says "`update(PentestSession).values(status='failed')` paths in `service.py`" but PentestSession has no `output_json` / error column in v2.1 schema (only AgentExecution does). The scrubber target field is unspecified for the session-level failure path.
- **Fix:** Either add an `error_message TEXT` column to `pentest_sessions` (Migration 003) or scrub only at the AgentExecution path and document that session-level failures carry only a status, no message.

### A-7. §L.1 multiplex contradicts v3.0 §5.9 API table
- **Where:** v3.0 §5.9 lists `WS /ws/projects/{id}/comments` and `WS /ws/projects/{id}/activity` as separate endpoints. §L.1 collapses these into a single `/ws/projects/{id}` with channel envelope. v3.0 table is not updated.
- **Fix:** Update v3.0 §5.9 row in the merged spec, or add explicit override note in §L.1 ("This supersedes the two rows in §5.9").

---

## B. High-impact ambiguities (HIGH-MED — security/correctness)

### B-1. `target.scope_rules` JSON schema is undefined
- **Where:** Referenced across §B, §G, AC #3, but no canonical schema.
- **Keys glimpsed:** `ip_ranges`, `domains`, `azure_subscriptions`, `tenants`, `allowed_storage_accounts`, `allowed_key_vaults`, `allow_ms_graph`, `git_url` (§5.4 SourceCodeAgent).
- **Fix:** Add a new section `§U. scope_rules canonical schema` with full JSON schema per `target_type`. Block on §B/§G/§5.4 implementation.

### B-2. `ApprovalGate._classify(step)` rules undefined
- **Where:** §F.2 calls `_classify(step)` returning `"privilege_escalation"` or None — no specification of how to classify.
- **Fix:** Define classification matrix: which `(domain_agent, internal_tool, action_or_module)` tuples map to `"privilege_escalation"`. PowerZure entirely? Specific Microburst storage-write actions? Add to §F.

### B-3. CoreDNS sidecar mechanism (§B.3) under-specified
- **Where:** "per-container CoreDNS instance" with `--dns 127.0.0.1` — but Docker sets `--dns` for the container itself, so the resolver must run *inside* that container's network namespace.
- **Options:** (a) Multi-process container (PID 1 = supervisord). (b) Separate sidecar container in same `network_mode: container:<peer>`. (c) Per-session shared CoreDNS in same Docker network with `--dns <core-dns-ip>` (not 127.0.0.1).
- **Fix:** Pick one mechanism and document with a sample docker run / compose snippet.

### B-4. Paused sub `plan_version` freezing during replan
- **Where:** §H.2 SubOrchestrator stores `self._plan_version` at suspend time; §I.2 master may increment plan_version during pause. On wake, `require()` is called with stale `self._plan_version` → §F's strict invalidation rule rejects → infinite re-pause loop possible.
- **Fix:** Either (a) on wake, refresh `self._plan_version` from current master state, OR (b) make replan-during-pause a no-op for paused subs' steps, OR (c) allow grant to match either `plan_version` or `plan_version+N` within a window.

### B-5. Concurrent ApprovalGrant POST race
- **Where:** §F.1 UNIQUE `(session_id, step_hash, plan_version)` + §H.5 POST endpoint. Two operators clicking Approve simultaneously: one INSERT succeeds, second hits UNIQUE violation.
- **Fix:** API handler must catch IntegrityError and return 409 with body `{"reason": "already_approved"}`. Add to §H.5 spec.

### B-6. Per-target credential binding 1:N relationship gap
- **Where:** §5.3 "per-target binding" but `credentials.target_id` is a single FK (1:N: one credential → one target). A cloud_azure target with both Azure SP + GitHub PAT (for any cross-cutting tooling) cannot bind both.
- **Fix:** Either (a) introduce `target_credentials` join table for M:N, OR (b) document that one target can only have one credential and constrain UI accordingly.

### B-7. `_has_new_observations` and `Blackboard.version` skew
- See A-1 (same root cause). Fix together.

---

## C. Medium-low ambiguities

| # | Issue | Suggested resolution |
|---|---|---|
| C-1 | Health agent uses `settings.anthropic_api_key` (no CredentialStore but has API key) — boundary unclear | §E.1 add: "Anthropic key is platform-level config, not user-managed credential. CredentialStore exclusion applies only to per-project user-supplied credentials." |
| C-2 | `cloud_provider` legacy column lifecycle | Migration 003 either drops the column or marks it `deprecated, kept-for-rollback`. Document in §K.1. |
| C-3 | `OrchestratorRegistry` lifecycle | Spec register on SubOrch.__init__, deregister on completion or exception, weakref to avoid leak |
| C-4 | SecretScrubber generic high-entropy regex false-positives in prose | Add a corpus test: 100 real english sentences containing tokens like "secret password" → expect 0 false positives. |
| C-5 | `asyncio.gather` + semaphore wiring | §5.5 add code: each SubOrchestrator wraps its run in `async with self._semaphore: await self._run()`; master passes shared `asyncio.Semaphore(project.max_concurrent_domains)`. |
| C-6 | Health agent `domain_agent.docker_image` arity | Pin to single image per domain agent (`type: str`). For internalized tools, health agent does not check inner tool images — only the wrapper image. Document in §E. |
| C-7 | `tests/e2e/v2_1_frontend_fixture/` source | Pin to a git tag of the frontend repo as a build artifact under `tests/e2e/`; do not commit the bundle to source. |
| C-8 | Comment depth O(N) check | Add `depth INT NOT NULL` column to `comments` table; CHECK constraint `depth <= 5`. Update Migration 005. |
| C-9 | activity_events 90-day prune | Add daily APScheduler job in `app/services/scheduling.py`; spec in §M.3. |
| C-10 | Partial sub-orchestrator failure reporting | Master's report aggregation marks domain results as `partial` (status='failed_after_partial') with the findings actually captured. Spec in §5.5. |
| C-11 | Approval timeout vs grant TTL mismatch (1800s wait vs 3600s validity) | Document as intentional: operator has 30 min from sub-suspension to approve; once granted, sub has up to grant TTL to consume. State explicitly in §H.4 / §F.1. |

---

## D. Minor (LOW)

- **D-1.** §F.1 schema lacks `created_at` (uses `granted_at` instead). Acceptable but inconsistent with v2.1 audit conventions.
- **D-2.** §H.5 `OrchestratorRegistry` fan-out: include `sub_id` (not just step_hash) as routing key to avoid edge-case duplicates.
- **D-3.** §M.1 6th-level reply enforcement under race — last-write-wins is acceptable; document.
- **D-4.** §F.1 column `consumed_at` could be just a NOT NULL `consumed_at` with default infinity; current NULLable is fine, doc convention.

---

## E. Pre-Mortem additions (deep-interview Contrarian)

### E-1. "Do we even need 4 domain agents in MVP?" (Simplifier challenge)
- v3.0 internally claims user explicitly chose all 4. If schedule slips, dropping SourceCodeAgent (lowest risk, separate Docker image cost) preserves the security-relevant scope. Document this fallback in Risks table for explicit operator decision rather than implicit slip.

### E-2. "Hierarchical orchestrator vs simpler executor.py loop" (Contrarian challenge)
- For projects with **1 target** (the v2.1 backward-compat path), the hierarchical machinery (Master + Blackboard + 1 SubOrch) is pure overhead. Spec a fast-path: single-target project bypasses Blackboard, runs directly in SubOrchestrator.run(). Document as optimization in §5.5 (do not rely on it for correctness).

### E-3. "Single uvicorn worker is a deployment regression" (Critic-style)
- v2.1 may have been deployed with multiple workers. §R enforces single worker. Production users with existing multi-worker deployments will break on upgrade. Add migration note in `docs/deployment.md` and a CHANGELOG entry tagged BREAKING.

---

## F. Recommended Action

1. **Block code start until §A (contradictions) resolved.** A-1 / A-2 / A-4 / A-6 / A-7 are blocking.
2. **Author `v3.1.4` patch** containing only §A fixes + §B (security ambiguities) — keep textual, no structural change.
3. **Defer §C/§D** to implementation-time clarification (track in todos).
4. **Add §U "scope_rules canonical schema"** to v3.1.4 — single source of truth for both adapters and validators.
5. **Re-run Critic agent** on v3.1.4 (focus: A+B fixes regression-free).

---

## G. Resume Pointer

If session is compacted, resume by:
1. Read `RESUME-CONTEXT.md`
2. Read this file (`PLAN-VERIFICATION-2026-05-10.md`)
3. If user wants to proceed → produce `v3.1.4` patch addressing §A+§B, save as `.omc/plans/offensive-security-agent-consensus-v3.1.4.md`
4. If user wants to start coding → block until §A items decided

**Verification status:** awaiting user direction.
