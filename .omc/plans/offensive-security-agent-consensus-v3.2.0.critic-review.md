# Critic Evaluation — `offensive-security-agent-consensus-v3.2.0`

**Reviewer:** Critic (consensus stage of `/ralplan --consensus --deliberate`)
**Plan under review:** `.omc/plans/offensive-security-agent-consensus-v3.2.0.md` (661 lines)
**Architect review consumed:** `.omc/plans/offensive-security-agent-consensus-v3.2.0.architect-review.md`
**Date:** 2026-05-12
**Mode:** deliberate — full gate (principles, alternatives, risks, ADRs, expanded tests, pre-mortem).
**Operating posture:** THOROUGH initially, escalated to ADVERSARIAL after surfacing >3 MAJOR defects and one BLOCKER previously raised by the Architect.

---

## Pre-commitment predictions

Before reading the plan in detail, I predicted these would be the most likely failure surfaces, based on the §0 summary and the architect's headline:

1. Discovered-target re-validation flow will be a one-line bullet with no state-machine, despite being the most consequential safety path.
2. The deterministic ambiguity scorer will have hand-tuned weights and no calibration data.
3. The active/passive boundary will be binary instead of three-tier and will mislabel `httpx` / `subfinder -passive`.
4. Schema sprawl: `workflows` and `pentest_sessions` will substantially overlap.
5. Pre-mortem will cover legal / cost / hallucination but miss model-API outage and human-vs-machine ambiguity-score disagreement.

**All five predictions hit.** (1)–(4) are confirmed by the Architect §1.6/§3.1/§4.4 and re-verified below; (5) is confirmed by §0.4 having exactly three scenarios and no provider-outage or scorer-disagreement scenario.

---

## 1. Criterion-by-Criterion Scorecard

| # | Criterion | Verdict | One-line justification |
|---|---|---|---|
| 1 | Principle-option consistency | **FAIL** | Architect found 4 principle violations (P2/P3/P4/P5). P2 is BLOCKER (`single approval gate` contradicts `discovered-target re-validation` in §5.1 with no state to land in). Plan does not respond to these in v3.2.0. |
| 2 | Fair alternatives | **PARTIAL** | A1/A2/B1/B3/C1/C3 invalidations are real, not strawmen, but invalidations are one-line and miss the strongest alternatives the Architect surfaced (B1.5: in-code dict; C1.5: pentest_sessions + messages JSONB). Architect's "merged-schema" steelman is not in the alternatives table. |
| 3 | Risk mitigation clarity | **PARTIAL** | S1 mitigations (a)/(c)/(d) are concrete; S1 mitigation (b) and S2 (b) are vague ("re-validates", "re-validates"). No state machine for what happens when re-validation rejects. S3 mitigations are concrete (turn cap + USD budget). |
| 4 | Testable acceptance criteria | **PARTIAL** | §1.5, §2.6, §3.6, §4.7, §5.6, §6.4 are mostly objective, but §3.6 ("8 or 10 for an admin") and §2.6 ("New Docker images build") are necessary-not-sufficient. No coverage gate for the new safety carve-out (NativePassiveAdapter audit). |
| 5 | Concrete verification steps | **PASS** | Phase acceptance criteria name commands (`alembic upgrade head`, `pytest tests/...`, `python -m app.agents.knowledge_pack_loader --verify`, `docker compose ... build`). §4.7 names an E2E spec by file. |
| 6 | Pre-mortem adequacy | **FAIL** | Three scenarios are right shape but the planner missed (a) **Claude API outage mid-interview** — what state does the workflow land in, and does the user lose their draft? and (b) **deterministic scorer disagrees with user** — user thinks plan is specific, scorer says ambiguity=0.8, loop won't exit. Both are first-order failures for this design. |
| 7 | Expanded test plan adequacy | **PARTIAL** | Unit/integration/E2E/observability buckets are populated with named targets — good. Gaps: no test for `validate_discovered_targets` rejection path (the BLOCKER), no test for ModelRouter cost-budget accounting accuracy, no test for `NativePassiveAdapter` failing closed when `passive_egress_allowlist` is empty, no fuzz/property test on ambiguity scorer monotonicity beyond the unit. |
| 8 | ADR completeness | **PARTIAL** | All three ADRs have Decision / Drivers / Alternatives / Why / Consequences / Follow-ups, but ADR-v3.2.0.3 admits in its Follow-ups that the scorer threshold "will be tuned after first 50 real sessions" — i.e., the chosen option ships an uncalibrated control as a default. ADR-v3.2.0.2 does not address why a YAML/dict isn't sufficient (Architect Tension A). ADR-v3.2.0.1 does not consider the shared-Docker-image alternative for passive validators. |
| 9 | Architect §4 synthesis incorporation | **FAIL** | The plan was authored before the Architect review and incorporates **zero** of the five concrete moves (merge into `pentest_sessions`, drop `domain_agents` table, shared Docker image for passive validators, `paused_for_rescope` state, model self-rating). All five must be addressed in v3.2.1. |

**Tally:** 1 PASS, 5 PARTIAL, 3 FAIL. Three FAIL criteria block APPROVE.

---

## 2. Top Defects (in priority order)

### D-1 — `BLOCKER` — Discovered-target re-validation has no state machine

- **Where:** §5.1 (line: "splits into `accepted` / `rejected`; called by every active OSINT adapter after enumeration"), §0.4 S1 mitigation (b), §4.1 state-transition table.
- **Why this matters:** The plan's Principle 2 declares approval is the **single** gate. §5.1 then introduces a second, post-approval gate (per discovered hostname). Three possible behaviors exist; the plan picks none. This is the single most legally consequential path in the system — it determines whether a scope-violating probe gets dropped, halts execution, or auto-approves. Inaction here is a contract-breach vector.
- **Evidence (backtick-quoted):** §5.1 says `"validate_discovered_targets(discoveries: list[str], rules) -> tuple[list[str], list[str]]` — splits into `accepted` / `rejected`; called by every active OSINT adapter after enumeration, before any probe of discovered hosts." Plan never specifies what the orchestrator does with the `rejected` list after that split. §4.1's state-transition table has no `paused_for_rescope` state. The Architect's §3.1 audit confirms: "the workflow state machine in §4.3 must list these transitions."
- **Confidence:** HIGH.
- **Realist check:** Worst case is silent scope expansion or silent scope drop; either is non-recoverable in an engagement contract. No deployment gate, retry layer, or upstream filter mitigates this. Severity stays BLOCKER.
- **Remediation:** Adopt Architect §4.5 verbatim — add `paused_for_rescope` status, `POST /workflows/{id}/rescope` endpoint, default safe-drop with audit `rescope_auto_drop` after `settings.rescope_decision_timeout_seconds`, frontend modal on Monitor page. Update §4.1 state-transition table and §4.3 state machine. Required before any executor work in P3.

### D-2 — `MAJOR` — Pre-mortem missing two first-order failure modes

- **Where:** §0.4 (only S1/S2/S3).
- **Why this matters:** Deliberate-mode requires the most impactful failure modes for THIS plan. (a) The interview loop hard-depends on Anthropic API — if the API 5xxs mid-turn, where does the workflow land? does `interview_turn_count` get incremented? is the partial assistant message persisted? (b) The deterministic scorer claims authority over loop termination; if a user thinks their plan is fully specified but the scorer disagrees (e.g., user uses synonyms the regex penalty doesn't catch), the loop will demand more turns and burn budget until cap.
- **Evidence:** §0.4 enumerates only "Legal/scope blowback," "AI hallucinates out-of-scope steps," "Model-cost explosion." §4.3 scorer has no escape hatch other than the 6-turn cap. §4.2's `append_user_message` is described with no failure-mode treatment.
- **Confidence:** HIGH.
- **Realist check:** API outage detection is "immediate" (the call errors), so the system fails fast — but the *state recovery* path is not specified. Severity stays MAJOR (causes rework, not catastrophe).
- **Remediation:** Add S4 (Claude API outage) and S5 (scorer-user disagreement) to §0.4 with concrete mitigations: S4 — retries with exponential backoff (max 3), on persistent failure transition to `needs_human_review` with audit `claude_api_unreachable`, preserve `draft_json` so user can resume. S5 — UI shows the *specific unsatisfied predicate* the scorer is asking about, and an override button gated to admin that forces `ready_for_review` with audit `ambiguity_override`.

### D-3 — `MAJOR` — Deterministic ambiguity scorer ships uncalibrated as default

- **Where:** §4.3 (9-component weighted sum), §1.3 (`workflow_ambiguity_threshold: float = 0.35`), ADR-v3.2.0.3 follow-up admission.
- **Why this matters:** The scorer is the default termination condition for every Workflow chat in production. Its 9 weights (0.20/0.10/0.20/0.15/0.10/0.10/0.05/0.05/0.05) are hand-picked with no calibration data. ADR's own follow-up says "Tune `workflow_ambiguity_threshold` after first 50 real sessions" — i.e., the plan ships a known-untuned control. Architect §1.2 makes the same argument: if it'll be tuned post-hoc, why ship the scaffolding at all?
- **Evidence:** §4.3 code block weights, ADR-v3.2.0.3 follow-up section quote.
- **Confidence:** HIGH.
- **Realist check:** Worst case is operators frustrated with too-many or too-few questions; cost cap and turn cap (S3 mitigations) limit blast radius. **Mitigated by:** the existing $5/day cap and 6-turn cap make cost-explosion bounded even if the scorer behaves badly. Severity DOWNGRADED from CRITICAL to MAJOR.
- **Remediation:** Either (a) replace with model self-rating per Architect §4.2 ("ask the model: rate 0.0–1.0 + return the single most underspecified field") and ship the deterministic scorer as a fallback only, OR (b) keep the scorer but ship behind a feature flag `workflow_use_deterministic_scorer: bool = False` with model-self-rating as default. Either way, add a unit test that proves the scorer and model-self-rating agree on ≥10 fixture drafts before either is promoted to default.

### D-4 — `MAJOR` — `NativePassiveAdapter` weakens Principle 3 by carve-out

- **Where:** §2.2, §2.5 mitigation, §0.1 Principle 3 last sentence.
- **Why this matters:** Principle 3 says "Tool wrappers must be sandboxed by default" — then immediately carves out "Bare-metal Python execution is reserved for *passive-only* validators... opt-in via a `safety_profile` flag." This is a self-immunizing principle: the principle is true except where the plan needs it to be false. A bug in `secret_scan.py` running native will execute *in the FastAPI process* (cf. `backend/app/main.py` — same process as the API server); the same bug in Docker is contained.
- **Evidence:** §0.1 Principle 3, §2.2 file list, §2.5 mitigation (homegrown `httpx.AsyncClient(transport=AllowlistTransport)` does not replicate cgroups/netns/no-new-privs/read-only-FS).
- **Confidence:** HIGH.
- **Realist check:** The HTTPX allowlist is a real defense for network egress, but the FS/syscall/PID surface is exposed. Detection of an in-process compromise is slow (no container exit signal). **Mitigated by:** the validators are read-only Python with no shell exec — but that's a code-review property, not an architectural one. Severity stays MAJOR.
- **Remediation:** Adopt Architect §4.2 + §4.7: single shared `osint-passive` Docker image with multiple entrypoints. One Dockerfile, ~30s build, uniform isolation. If retained natively, narrow Principle 3's carve-out to *only* HTTP/DNS queries — explicitly prohibit any subprocess, FS write, or import of `os.system`/`subprocess.*`.

### D-5 — `MAJOR` — Schema sprawl: `workflows` table ~80% duplicates `pentest_sessions`

- **Where:** §1.1 `workflows` table definition.
- **Why this matters:** Verified against `backend/app/models/session.py:11-34`: `PentestSession` already has `id, project_id, prompt, plan_json, status, started_at, ended_at` + timestamps. The plan adds a parallel `workflows` table that *also* has `id, project_id, draft_json (=plan_json), status, approved_at (=started_at proxy), ...` plus an `executed_session_id` forward pointer creating a 1:1 join. This is textbook draft/published split where status enum suffices. Verified status enum is currently `pending|running|completed|failed` (grep results above) — extending it with `draft|interviewing|ready_for_review|approved|needs_human_review|rejected|paused_for_rescope` requires no new table.
- **Evidence:** `backend/app/models/session.py:11-34` shows the existing column overlap; §1.1 plan column list shows the duplication; Architect §1.4 explicitly maps the overlap.
- **Confidence:** HIGH.
- **Realist check:** Carrying two tables forever is a maintenance tax, but not a safety tax. **Mitigated by:** v3.2.1 can merge later. Severity stays MAJOR (causes rework in P0 and P3 if not addressed now; cheaper to fix before migration ships).
- **Remediation:** Adopt Architect §4.4 — extend `pentest_sessions` with `messages JSONB`, `model_id`, `approved_at`, `approved_by`, `cost_usd_accum`, `interview_turn_count`, `ambiguity_score`, `domain_agent_slug`. The `prompt: Text` column already exists as the seed message. Migration `003` becomes additive on the existing table; the `workflows` table is deleted from §1.1.

### D-6 — `MAJOR` — `domain_agents` + `domain_agent_tools` tables encode metadata that belongs on the tool

- **Where:** §1.1 (table defs), §3.1 (seed data), §3.2 (`DomainAgentResolver`).
- **Why this matters:** Verified that `backend/app/agents/registry.py` is a flat dict and `backend/app/orchestrator/planner.py:19` literally hardcodes `"Available agents: nmap, nuclei, metasploit, pyrit"` into the system prompt. The plan adds two tables + a resolver service to represent what amounts to "which tool tags belong to which persona" — pure code metadata. Principle 5 ("Adding a tool is a registry change, not an agent rewrite") is **violated** by the plan's own implementation because adding a tool now requires 4 touch points (registry, `domain_agent_tools` row, knowledge pack, capability map).
- **Evidence:** §1.1 table defs, §3.1 seed table, Architect §3.4 violation audit.
- **Confidence:** HIGH.
- **Realist check:** Two DB tables are not a safety risk, but they cement metadata at the schema layer where it's most expensive to change. **Mitigated by:** all changes are seed-data only, and the existing migration `002_rbac.py` is the precedent for safe additive migrations. Severity stays MAJOR.
- **Remediation:** Adopt Architect §4.4 second half — replace with `backend/app/orchestrator/domain_agents.py` (in-code dict). Tools gain `applicable_domain_tags: frozenset[str]` on `ToolEntry`. Adding a tool becomes one file change.

### D-7 — `MAJOR` — Three-tier active/passive needed; binary mislabels `httpx`/`subfinder`

- **Where:** §0.1 Principle 4, §3.1 palette table (`httpx (passive)` for `osint-agent`), §2.4 risk band table.
- **Why this matters:** `httpx -status-code -title -tech-detect` issues real HTTP GETs to live target hosts. Calling this "passive" is wrong in any responsible-disclosure framing. The audit log will then claim "passive" for activity that the target's WAF will log as suspicious. Architect §3.3 makes this case with examples.
- **Evidence:** §3.1 palette line for `osint-agent`, §5.3 `ACTIVE_OSINT_ALLOWED_FLAGS["httpx"]`, Architect §3.3 audit.
- **Confidence:** HIGH.
- **Realist check:** The narrow flag set keeps the wire activity small, but the audit-truth issue is real. **Mitigated by:** audit log is internal — the operator-facing UI can correct the labeling cheaply. Severity stays MAJOR.
- **Remediation:** Adopt Architect §4.6 three-tier taxonomy: `passive` / `narrow_active` / `active`. Re-derive `_AGENT_BASE_RISK` from `(tier, tool)` rather than hand-tuning per-tool. Update Principle 4 wording.

### D-8 — `MAJOR` — `ModelRouter` is a god-class (model selection + RBAC + USD budget)

- **Where:** §1.2 `ModelRouter` class definition.
- **Why this matters:** Three orthogonal responsibilities. When billing logic changes (new pricing tier, monthly cap, team pool), the orchestrator gets churned. When orchestration changes, billing accounting risks regression. Architect §1.5 details this.
- **Evidence:** §1.2 class with `resolve()`, `estimate_cost()`, `daily_budget_remaining()` colocated.
- **Confidence:** HIGH.
- **Realist check:** Refactoring later is possible but locks the structure into v3.2.0. **Mitigated by:** small surface today (only 2 models), can be split cheaply. Severity stays MAJOR.
- **Remediation:** Split into `ModelRegistry` (metadata dict in `core/models.py`), `CostQuotaService` (in `app/services/quota.py`), `AttackPlanner` consumes both. Defer `CostQuotaService` USD enforcement to v3.2.1 once there's telemetry, but keep the API surface stable.

### D-9 — `MINOR` — `Workflow.executed_session_id` forward pointer creates dual identity

- **Where:** §1.1 line "`executed_session_id UUID FK -> pentest_sessions.id NULL` — populated on approve→execute".
- **Why this matters:** A single logical session has two IDs (workflow + session). External integrations and audit log queries must JOIN. Subsumed by D-5 — fixed by the merge.
- **Confidence:** HIGH.
- **Remediation:** Disappears with D-5 fix.

### D-10 — `MINOR` — Open Q #1 admits placeholder model IDs ship in code

- **Where:** §1.2 `SUPPORTED_MODELS` `"claude-sonnet-4-6-20250514"` / `"claude-opus-4-6-20250514"`; Open Q #1.
- **Why this matters:** If the planner commits the migration before Q1 is answered, the workflow chat endpoint will 4xx on first request. Existing `settings.anthropic_model` is `claude-sonnet-4-20250514` (verified in `config.py:20`), not 4-6.
- **Evidence:** `backend/app/core/config.py:20`, plan §1.2.
- **Confidence:** HIGH.
- **Remediation:** Open Q #1 must be resolved before P0 ends; CI smoke test should call `client.messages.create(model=settings.workflow_default_model_id, ...)` against Anthropic with a 1-token prompt as a pre-deploy gate.

### D-11 — `MINOR` — Acceptance criteria for §2 don't test the new safety carve-out

- **Where:** §2.6.
- **Why this matters:** §2.5 introduces native passive runtime with homegrown sandbox; §2.6 only tests image build, secret-scan regex, and egress logging. No test that `NativePassiveAdapter` refuses subprocess/exec, no test that allowlist transport rejects non-listed domains under DNS-rebinding, no test that boot fails closed on SHA mismatch.
- **Confidence:** MEDIUM.
- **Remediation:** Add three unit tests: `test_native_adapter_rejects_subprocess`, `test_allowlist_transport_rejects_dns_rebind`, `test_knowledge_pack_loader_boot_fails_on_sha_mismatch`.

---

## 3. Risk-Not-Mitigated List

Risks the plan acknowledges but does not actually mitigate:

1. **Discovered-target re-validation outcome** — §0.4 S1(b) names the risk but §5.1 describes only the splitting function, not what the orchestrator does with `rejected`. Fully addressed by D-1.
2. **AI hallucination after approval** — §0.4 S2 mitigates *before* approval (client-side highlight + server re-check). What stops the AI from emitting a hallucinated target *during execution* of an approved plan (e.g., `subfinder` discovers a fabricated subdomain through stale CT data)? §5.1 attempts to address this but inherits D-1's gap.
3. **Claude API outage mid-interview** — not in §0.4 (see D-2). `append_user_message` flow has no defined behavior.
4. **Scorer/user disagreement** — not in §0.4 (see D-2). User has no override.
5. **Knowledge-pack supply-chain drift** — §0 names it (Open Q #7), §2.5 mitigates with vendoring + SHA, but the plan never says **what happens when SHA mismatches at boot**: hard-fail, soft-fail with audit, or continue with stale? Loader §2.2 says "refuses YAML/MD with executable hooks" but doesn't say it refuses to boot on SHA mismatch.
6. **Native passive runtime escape** — §2.5 mitigates network egress but not FS/subprocess/exec surface. D-4 remediation needed.
7. **Daily USD budget bypass via team-pool** — §1.3 sets `workflow_daily_usd_budget_default` per user. If admin creates 10 burner users, the team budget multiplies. Plan has no team-aggregate enforcement.
8. **Model-pricing drift** — `SUPPORTED_MODELS` hardcodes `input_usd_per_1k` / `output_usd_per_1k`. When Anthropic changes pricing, cost accounting silently drifts unless someone updates code. Open Q #1 implies awareness; no operational mitigation (no daily pricing-sync job, no admin UI override).
9. **RBAC re-check on approval** — §3.5 mitigates but doesn't say what happens if approver is demoted *between* RBAC check and orchestrator kickoff (TOCTOU). Worst case: user passes the approval check, gets demoted in the same transaction window, orchestrator runs with admin-grade plan.

---

## 4. Architect-Synthesis Incorporation Matrix

The Architect's §4 lists five concrete KEEP/DROP/DEFER/MERGE moves. For each:

| # | Architect move | Current plan state | Critic verdict |
|---|---|---|---|
| 1 | **Merge `workflows` into `pentest_sessions`** (Architect §4.4 first half) | Plan ships separate `workflows` + `workflow_messages` + `executed_session_id` FK forward pointer (§1.1). | **AMEND PLAN** — adopt merge. Required to clear D-5 and D-9. |
| 2 | **Drop `domain_agents` + `domain_agent_tools` tables** in favor of in-code dict + `applicable_domain_tags` on `ToolEntry` (Architect §4.4 second half) | Plan ships both tables with seed data (§1.1, §3.1). | **AMEND PLAN** — adopt drop. Required to clear D-6 and honor Principle 5. |
| 3 | **Single shared `osint-passive` Docker image** for all 7 validators + `secret_scan` (Architect §4.2 + §4.7) | Plan ships 7 native Python validators + 1 native `secret_scan` (§2.2). | **AMEND PLAN** — adopt shared image. Required to clear D-4 (Principle 3 violation). Acceptable engineering cost: one Dockerfile, ~30s build, multi-entrypoint via `CMD`. |
| 4 | **`paused_for_rescope` state + endpoint** to resolve §3.1 contradiction (Architect §4.5) | Plan §4.1 state-transition table has no such state; §5.1 has no flow for `rejected` list. | **AMEND PLAN — BLOCKER** — adopt rescope flow. Required to clear D-1. Includes endpoint `POST /workflows/{id}/rescope`, default safe-drop after timeout, audit `rescope_auto_drop`, frontend modal. |
| 5 | **Model self-rated ambiguity** replaces deterministic 9-component scorer (Architect §4.2 first item) | Plan ships deterministic scorer with hand-tuned weights as default (§4.3); admits post-hoc tuning in ADR-v3.2.0.3. | **AMEND PLAN with hedge** — make model-self-rating the default; keep the deterministic scorer behind a feature flag `workflow_use_deterministic_scorer = False` for users who want explainable termination. Required to clear D-3 cleanly. |

**All five moves are accepted by the Critic.** None should be rejected. The Architect's synthesis is technically sound and grounded in verified repo state (every cross-reference I sampled — `service.py`, `planner.py`, `session.py`, `registry.py`, status enum values — checks out).

---

## 5. Ambiguity Risks (statements with multiple valid interpretations)

- §5.1: `"called by every active OSINT adapter after enumeration, before any probe of discovered hosts"` → Interpretation A: adapter returns the split, orchestrator decides next step / Interpretation B: adapter itself drops rejected and continues. **Risk if B chosen:** silent scope drop with no operator notification. Subsumed by D-1.
- §0.4 S1(b): `"every active OSINT step re-validates each discovered target against whitelist before probing it, not just the seed"` → Interpretation A: each discovered host blocks the whole step on rejection / Interpretation B: only the rejected hosts are skipped, others continue. Subsumed by D-1.
- §4.3: `"If turn_count ≥ settings.workflow_max_interview_turns (6) OR last_two_turns_delta < settings.workflow_min_ambiguity_delta (0.15) → needs_human_review"` → Interpretation A: OR is short-circuit on first turn / Interpretation B: delta-check requires ≥2 turns of history. **Risk if A chosen:** every first-turn workflow lands in `needs_human_review` because no delta exists yet. Plan needs a guard like `if turn_count >= 2 and last_two_turns_delta < ...`.
- §3.2: `"intent='enumerate_subdomains'... mapped to concrete tool via lookup_by_capability filtered by the agent's palette"` → Interpretation A: AI emits intent strings from a closed enum / Interpretation B: AI emits free-form intents resolved via fuzzy match. **Risk if B chosen:** AI hallucinates unknown intents that resolve to wrong tool. Plan does not constrain the intent vocabulary.
- §4.4: `"out-of-scope hostnames highlighted red via client-side whitelist preview"` → Interpretation A: client implements `WhitelistValidator` in TS / Interpretation B: client calls a server preview endpoint. **Risk if A chosen:** TS implementation drifts from Python source-of-truth.

---

## 6. Multi-Perspective Notes (plan-mode lenses)

- **Executor perspective:** I cannot start P3 (Workflow UX) without knowing what to do when `validate_discovered_targets` returns a non-empty rejected list (D-1). I cannot ship P1 without confirmation on Open Q #8 (native vs Docker for `secret_scan`) — that's not an "open question," that's a *blocking* prerequisite for Phase 1 file layout. I cannot start P0 without Open Q #1 resolved or I'll write a migration with placeholder model IDs.
- **Stakeholder perspective:** The pitch was "chat-driven launch flow + tool catalog expansion + domain agents." The plan delivers that but adds 3 tables and a deterministic scorer the operator never sees. The success metric — "users launch faster than v3.1" — isn't measured anywhere. No metric in §0.5 captures user-perceived speed or quality of the resulting plan. `osa_workflow_interview_turns_total` measures cost, not value.
- **Skeptic perspective:** The strongest argument against this plan: it is **prompt engineering with infrastructure**. The Architect's steelman §1.1 lands hard — "one column on `pentest_sessions`, one method signature change on `AttackPlanner`, one frontend page" delivers the same observable behavior at ~30% of the schema cost. The plan does not address that steelman. ADR-v3.2.0.2 in particular hand-waves: "B2 is the only option that satisfies the user-facing market reorg ask *and* leaves the existing `AgentAdapter` surface untouched" — but a YAML+dict also leaves `AgentAdapter` untouched and satisfies market reorg with less code.

---

## 7. What's Missing

- No metric for "time from chat-start to first executable workflow" (the actual UX win the plan promises).
- No retry / circuit-breaker policy on Anthropic API calls (D-2).
- No team-pool USD budget aggregation (only per-user, see §3 risk #7 above).
- No SHA-mismatch boot-failure behavior specified for knowledge packs (§3 risk #5).
- No TOCTOU defense for RBAC between approval and execution (§3 risk #9).
- No test that `NativePassiveAdapter` refuses subprocess/exec (D-11).
- No test for `validate_discovered_targets` rejection path (D-1, must be added if rescope flow lands).
- No fallback or feature flag for the model-router if Anthropic is down for >X minutes.
- No documentation of how knowledge-pack `MANIFEST.yaml` is keyed to `domain_agents.knowledge_pack_id` — §1.1 says `"FK-like to filesystem packs (validated at boot)"`. What validates? What's the failure mode? Drops out with D-6 if `domain_agents` is dict-ified.
- No definition of `intent` vocabulary for `DomainAgentResolver.resolve_tool` (Ambiguity Risk §5 above).

---

## 8. Verdict

**VERDICT: `ITERATE`**

### Verdict Justification

The plan has correct safety instincts (Principle 1 invariance, S2 client-side whitelist preview, exploit/osint allowlist split, RBAC re-check on approval). The principle list, ADR structure, expanded test plan, and verification commands are all materially present. **However**, one defect (D-1, the discovered-target rescope flow) is a BLOCKER that puts the system into an undefined state on the most legally consequential path, and the plan also fails three of nine criteria (Principle-option consistency due to four principle violations; Pre-mortem adequacy due to missing API-outage and scorer-disagreement scenarios; Architect synthesis incorporation by ~0%). The other four PARTIAL criteria each have specific, addressable remediations.

The plan is not fundamentally unsound. The chosen options (A3 hybrid OSINT, B2 tiered agents, C2 chat + structured editor) are *the right shape* — the failure is over-modeling the supporting infrastructure and underspecifying the one safety state-machine that matters. A single planner revision can land all 11 defects and the 5 Architect synthesis moves.

**Realist check recalibrations applied:**
- D-3 (deterministic scorer) downgraded CRITICAL → MAJOR. **Mitigated by:** the existing 6-turn cap and $5/day cap make cost-explosion bounded even with a misbehaving scorer; worst case is annoyance, not data loss or breach.
- No CRITICAL findings remain after Realist Check. D-1 is the sole BLOCKER and earns it (legal/contract impact, no upstream mitigation).

**Operating mode:** Started THOROUGH. Escalated to ADVERSARIAL after surfacing D-1 (BLOCKER) plus D-2/D-3/D-4 (3 MAJOR) in the first pass — that triggered the escalation criterion (1 CRITICAL/BLOCKER OR 3+ MAJOR). Adversarial pass added D-7, D-8, and the team-pool/TOCTOU risks in §3.

`APPROVE` is blocked by D-1 (BLOCKER) and FAILs on criteria 1, 6, 9.
`REJECT` is not warranted — the option choices A3/B2/C2 are sound; the schema-sprawl and scorer issues are remediable.
`ITERATE` is the correct verdict.

---

## 9. Required Revisions for v3.2.1

The Planner must address all of the following in the next consensus pass:

1. **[BLOCKER]** Add `paused_for_rescope` status + `POST /workflows/{id}/rescope` endpoint + default safe-drop-after-timeout to §4.1, §4.3, §5.1. Resolves D-1 and the Principle 2 violation. Update state-machine diagram and add E2E test `discovered_target_rescope_flow.spec.ts`.
2. **[MAJOR]** Merge `workflows` table into `pentest_sessions` per Architect §4.4 first half. Update §1.1 migration to be an additive ALTER on `pentest_sessions`. Drop `workflows` and `workflow_messages` tables. Resolves D-5 and D-9.
3. **[MAJOR]** Drop `domain_agents` + `domain_agent_tools` tables. Replace with `backend/app/orchestrator/domain_agents.py` (Python dict) and add `applicable_domain_tags: frozenset[str]` to `ToolEntry`. Resolves D-6 and the Principle 5 violation.
4. **[MAJOR]** Replace deterministic ambiguity scorer with model self-rating as default. Keep the deterministic scorer behind `workflow_use_deterministic_scorer: bool = False`. Add `ambiguity_override` admin endpoint per D-2 remediation. Resolves D-3.
5. **[MAJOR]** Consolidate 7 native passive validators + `secret_scan` into a single shared `osint-passive` Docker image (multi-entrypoint). Update §2.2 file list and §2.5 risks/rollback. Resolves D-4 and the Principle 3 violation. If a native path is retained as a fallback, narrow it to HTTP/DNS only and explicitly prohibit subprocess/FS in the principle wording.
6. **[MAJOR]** Add pre-mortem scenarios S4 (Claude API outage mid-interview) and S5 (scorer-user disagreement) to §0.4 with concrete mitigations per D-2.
7. **[MAJOR]** Adopt three-tier active/passive classification per Architect §4.6. Update Principle 4 wording, §2.4 risk band table (derive from tier+tool), §3.1 palette table (`httpx (narrow_active)`, not `httpx (passive)`). Resolves D-7 and Principle 4 violation.
8. **[MAJOR]** Split `ModelRouter` into `ModelRegistry` (metadata) + `CostQuotaService` (billing/quota). Defer USD enforcement to v3.2.2 with a feature flag. Resolves D-8.
9. **[MAJOR]** Specify SHA-mismatch behavior in knowledge-pack loader §2.2 — must hard-fail boot with audit `knowledge_pack_sha_mismatch`. Resolves §3 risk #5.
10. **[MAJOR]** Add team-pool aggregate USD budget enforcement and TOCTOU-safe RBAC re-check on orchestrator kickoff (single transaction with FOR UPDATE on user role). Resolves §3 risks #7 and #9.
11. **[MINOR]** Resolve Open Q #1 (Anthropic model IDs + pricing) **before** P0 lands. Replace placeholders. Add pre-deploy smoke-test that calls Anthropic with the configured model.
12. **[MINOR]** Constrain `DomainAgentResolver.resolve_tool` intent vocabulary to a closed enum; reject AI plans with unknown intents and re-prompt. Resolves Ambiguity Risk §5 item 4.
13. **[MINOR]** Add explicit guard in §4.3 scorer transition: `last_two_turns_delta` check only fires when `turn_count >= 2`. Resolves Ambiguity Risk §5 item 3.
14. **[MINOR]** Add tests per D-11: `test_native_adapter_rejects_subprocess` (or drop if D-4 is adopted via shared Docker), `test_allowlist_transport_rejects_dns_rebind`, `test_knowledge_pack_loader_boot_fails_on_sha_mismatch`.
15. **[MINOR]** Add success-side metric `osa_workflow_time_to_ready_for_review_seconds` to §0.5 observability bucket — the user-facing UX win the plan promises but does not measure.

Upon delivery of v3.2.1 addressing items 1–11 (at minimum), Critic will re-evaluate. Items 12–15 are nice-to-have for v3.2.1 but acceptable as v3.2.2 follow-ups if explicitly enumerated as such.

---

## 10. Open Questions (unscored — moved here by self-audit)

These were Critic candidates that did not survive the self-audit's "could the author refute this with context I might be missing?" gate, and are surfaced for the Planner's attention rather than scored:

- Q-1: Is `safety_profile=passive` a per-tool default or a per-step override? §1.1 puts it on `domain_agent_tools.default_safety_profile`, but `step.active_recon` (§5.2) implies per-step toggle. Both? Either? Document intended semantics.
- Q-2: When `workflow_max_interview_turns` is hit and status → `needs_human_review`, who reviews? Admin? Original creator? The plan says `needs_human_review` but never defines the reviewer role or UI.
- Q-3: The plan says `pentest_sessions.workflow_id` is nullable for backwards compat (§1.1). If D-5 (merge) is adopted, this concern goes away. If D-5 is rejected, what's the long-term migration story to non-null? Owned ticket?
- Q-4: §4.5 keeps a "Legacy quick prompt" path for one release. If a user starts a session via the legacy path, can they then *upgrade* it into the workflow flow, or are they stuck? Important for adoption metrics.
- Q-5: Open Q #4 in the plan asks about `mobile-agent` static-vs-dynamic. If dynamic is chosen post-plan, does v3.2.0 ship with a placeholder that gets backfilled, or wait? Affects the seed migration's row count.

---

## 11. Ralplan Summary Row (deliberate mode)

| Gate | Pass/Fail | Reason |
|---|---|---|
| Principle/Option Consistency | **FAIL** | 4 principle violations (P2 BLOCKER, P3/P4/P5 MAJOR); §0.1 Principle 2 contradicts §5.1 discovered-target re-validation. |
| Alternatives Depth | **PARTIAL** | A1/A2/B1/B3/C1/C3 invalidated with real reasons but one-line; Architect's stronger steelmans (in-code dict, merged schema) not in alternatives. |
| Risk/Verification Rigor | **PARTIAL** | S3 mitigations concrete; S1(b)/S2(b) vague; verification commands named in every phase but coverage gap on native runtime audit. |
| Deliberate Additions (pre-mortem + expanded tests) | **PARTIAL** | Pre-mortem has 3/5 needed scenarios; test plan has buckets populated but misses rescope, API-outage, native-sandbox, scorer-disagreement tests. |

**Aggregate ralplan gate: FAIL — ITERATE required.**
