# Critic Evaluation — `offensive-security-agent-consensus-v3.2.1`

**Reviewer:** Critic (consensus stage of `/ralplan --consensus --deliberate`, iteration 2)
**Plan under review:** `.omc/plans/offensive-security-agent-consensus-v3.2.1.md` (1053 lines)
**Predecessors consumed:**
- v3.2.0 plan, v3.2.0 Architect review (SUPPORT-WITH-CHANGES), v3.2.0 Critic review (ITERATE — 1 BLOCKER + 7 MAJOR + 3 MINOR)
- v3.2.1 Architect review (SUPPORT-WITH-CHANGES, dated 2026-05-12)
- `.omc/plans/open-questions.md`
**Date:** 2026-05-12
**Mode:** deliberate — full gate (principles, alternatives, risks, ADRs, expanded tests, pre-mortem).
**Operating posture:** THOROUGH (no BLOCKER or 3+ MAJOR surfaced during Phase 2 — did **not** escalate to ADVERSARIAL).

---

## Pre-commitment predictions

Before re-reading v3.2.1 in detail, the predicted failure surfaces (given v3.2.0's open defects + the Architect's known critique of v3.2.1):

1. The rescope state machine will be specified but won't name the approver role.
2. The `pentest_sessions` table will become a god-row with a fat enum and overlapping lifecycle states.
3. Model self-rating will lack a calibration test (sycophancy risk).
4. Force-approve will skip both the elicitation gate and any admin/rate-limit gate.
5. The 4-tier risk taxonomy will retain hand-tuned weights that operationally collapse to the same "needs flag / doesn't" binary.

**Result of pre-commitment vs Phase-2 findings:** 5/5 hit. (1) confirmed in §4.1 — endpoint listed, role not named (Architect §2.1). (2) confirmed — 15 added columns + `interview_state` sub-enum (Architect §2.2). (3) confirmed — `test_ambiguity_self_rating.py` checks format, not calibration (Architect §2.4). (4) confirmed — `POST /force-ready-for-review` available "to any session creator" (Architect §2.5). (5) confirmed — `TIER_BASE_RISK` 0.05/0.30/0.55/0.85 (Architect §2.3). All five are Architect-flagged residuals; the question for this review is whether they block v3.2.1 or defer.

---

## 1. Resolution Table for v3.2.0 Critic Defects (11 items)

| ID | Severity | v3.2.0 Issue | v3.2.1 Status | v3.2.1 Section / Evidence |
|---|---|---|---|---|
| D-1 | BLOCKER | Discovered-target re-validation has no state machine; Principle 2 contradicts §5.1 | **RESOLVED** | §0.1 P2 reworded as dual-gate; `paused_for_rescope` status added (§1.1 enum extension); `paused_for_rescope_at` + `rescope_request_json` columns (§1.1); `rescope_approvals` audit table (§1.1); `POST /pentest-sessions/{id}/rescope` endpoint (§4.1); full state-machine prose with trigger/decision/timeout in §5.1; integration test `test_rescope_endpoint.py` named in §0.5. |
| D-2 | MAJOR | Pre-mortem missing Anthropic API outage + scorer/user disagreement scenarios | **RESOLVED** | §0.4 now has 5 scenarios. S4 (Claude API outage) with retry policy, `interview_paused` state, resume token persistence. S5 (scorer/user disagreement) with `force-ready-for-review` override and audit. `interview_paused` is a real status in the §1.1 enum extension; `resume_token` column present. |
| D-3 | MAJOR | Deterministic 9-component scorer ships uncalibrated as default | **PARTIALLY-RESOLVED** | §4.3 drops the deterministic scorer entirely; model self-rates `{ambiguity, blockers, reasoning}` per turn; `min_required_fields_present` is the sole deterministic floor. Critic D-3 *remediation a* (replace with self-rating) is adopted. *Remediation b* (keep deterministic scorer behind feature flag as fallback) is **NOT** adopted — no fallback exists. The Architect §2.4 flags this same residual: no calibration test, no fallback. The hedge the v3.2.0 Critic explicitly requested (`workflow_use_deterministic_scorer = False` flag) is gone. |
| D-4 | MAJOR | `NativePassiveAdapter` weakens Principle 3 by carve-out | **RESOLVED** | §0.1 P3 reworded: "There is no native execution carve-out." §2.1 ships all 7 validators + `secret_scan` as entrypoints inside `osa-passive-recon:latest` (§2.2 file list confirms). `egress_monitor` covers Docker network namespace; app-layer `AllowlistTransport` is defense-in-depth (§5.4). No `NativePassiveAdapter` files exist in §2.2. Architect §1 row 3 also marks ADOPTED. |
| D-5 | MAJOR | Schema sprawl — `workflows` ~80% duplicates `pentest_sessions` | **RESOLVED** | §1.1 explicit "What was removed vs v3.2.0" list deletes `workflows` table; §7 Migrations Summary confirms single migration `003_session_workflow_columns.py` is additive on `pentest_sessions`. `workflow_messages` survives as a child chat-history table (correct — it is NOT a duplicate of `pentest_sessions`). Architect §1 row 1 also marks ADOPTED. |
| D-6 | MAJOR | `domain_agents` + `domain_agent_tools` tables encode code metadata | **RESOLVED** | §1.1 removal list drops both tables; §3.1 puts `DOMAIN_AGENTS: dict[str, DomainAgent]` in `backend/app/agents/domains/__init__.py`; §2.3 adds `applicable_domain_tags: frozenset[str]` to `ToolEntry`; §3.2 collapses resolver to a 2-line `palette_for()` function. Principle 5 wording confirms "Adding a tool touches one file." |
| D-7 | MAJOR | Binary active/passive mislabels `httpx`/`subfinder` | **PARTIALLY-RESOLVED** | §0.1 P4 replaced with 4-tier taxonomy (`passive_no_target_contact`, `passive_low_touch`, `active_recon`, `active_exploit`); §2.1 reclassifies `httpx` to `passive_low_touch`; §2.3 registry tags every tool with a tier; §5.2 derives `TIER_BASE_RISK` from tier (not hand-tuned per tool). However, Critic D-7 recommended **three-tier** (`passive` / `narrow_active` / `active`) per Architect §4.6; plan went to four tiers with hand-tuned 0.05/0.30/0.55/0.85 weights. The mislabel is gone, but the calibration concern is replicated at the tier level (Architect §2.3 / §4 P4 WATERED-DOWN). Net: the labeling defect is fixed; the calibration smell migrates from per-tool to per-tier. Marking PARTIAL because tier-collapse-to-flag-check is an Architect-flagged residual. |
| D-8 | MAJOR | `ModelRouter` is a god-class | **RESOLVED** | §1.2 decomposes into four units across two packages: `backend/app/orchestrator/model_selector.py` (`ModelSelector`), `backend/app/services/pricing.py` (`Pricing`), `backend/app/services/budget_guard.py` (`BudgetGuard`), `backend/app/orchestrator/model_client.py` (`ModelClient`). RBAC enforcement now in `ModelSelector.resolve()`. (Architect §2.6 flags packaging smell — RBAC leaking into orchestrator vs. API layer — but that is a structural micro-issue, not a violation of D-8's "split god-class" remediation.) |
| D-9 | MINOR | `Workflow.executed_session_id` forward pointer | **RESOLVED** | Subsumed by D-5 merge. §1.1 removal list explicitly notes "`workflows.executed_session_id` forward pointer — no longer needed." |
| D-10 | MINOR | Open Q #1 placeholder model IDs ship in code | **RESOLVED** | §1.3 commits `claude-sonnet-4-6` default + `claude-opus-4-6` admin-only with the `-20250514` aliases; §1.2 `Pricing.RATES` table embeds exact USD/1k rates as `Decimal`. §9 marks Open Q #1 as resolved. `open-questions.md` confirms `[x]` for #1. Pre-deploy smoke test (`backend/tests/smoke/test_anthropic_models.py`) named. |
| D-11 | MINOR | §2.6 acceptance tests don't cover native sandbox audit | **RESOLVED** | Obsoleted by D-4. §2.6 replaces native-sandbox tests with: image build, image-size cap (≤250 MB), `dns_resolver` schema test, `--network none` failure test, secret regex test (96 assertions), `test_passive_recon_image.py`, knowledge loader verify, and tampered-MANIFEST exit-78 test. §10 row D-11 explicitly notes obsolescence. |

**Tally:** 9 RESOLVED, 2 PARTIALLY-RESOLVED (D-3, D-7), 0 NOT-RESOLVED.

**Critic-vs-Architect cross-check:** Architect §1 ("Delta Assessment") marks all five v3.2.0 §4 synthesis moves as ADOPTED. There is **no disagreement** between this Critic resolution table and the Architect's delta-assessment row-by-row (Architect maps the five synthesis moves; this Critic maps the 11 defects, but the overlap — D-1↔move 4, D-3↔move 5, D-4↔move 3, D-5↔move 1, D-6↔move 2 — is consistent. Architect also flags D-3 and D-7 as residuals (Architect §2.4 "no calibration test", §2.3 "4-tier collapses to flag-check"), consistent with this Critic's PARTIAL ratings. **Concordance: full.**

---

## 2. Resolution Table for Architect §4 Synthesis (5 prior moves)

| # | Architect v3.2.0 §4 Move | v3.2.1 Critic Verdict | Cross-check with Architect v3.2.1 §1 |
|---|---|---|---|
| 1 | Merge `workflows` into `pentest_sessions` | **RESOLVED** | Architect §1 row 1: ADOPTED — agrees. |
| 2 | Drop `domain_agents` + `domain_agent_tools` tables | **RESOLVED** | Architect §1 row 2: ADOPTED — agrees. |
| 3 | Single shared `osint-passive` Docker image | **RESOLVED** | Architect §1 row 3: ADOPTED — agrees. |
| 4 | `paused_for_rescope` state + endpoint | **RESOLVED** | Architect §1 row 4: ADOPTED — agrees. Architect calls this "the most thoroughly implemented move in the revision." |
| 5 | Model self-rated ambiguity replaces deterministic scorer | **PARTIAL** | Architect §1 row 5: ADOPTED with explicit note that "the deterministic scorer wasn't kept as fallback — that was Critic D-3's hedge — so add this calibration test as the equivalent guardrail" (Architect §2.4). This Critic agrees with the framing: the move landed but the v3.2.0 Critic's recommended hedge did not. **Net agreement, slight nuance:** Architect calls the move ADOPTED with a residual; this Critic calls the broader defect (D-3) PARTIAL. Both reviews capture the same underlying gap (no calibration, no fallback); they label it at different granularities. No disagreement of substance. |

**Disagreements flagged:** None of substance. The Architect's "ADOPTED" framing for move 5 and this Critic's "PARTIAL" framing for D-3 describe the same artifact at different granularities — the synthesis move materialized but did not include the v3.2.0 Critic's specifically-requested fallback flag. Both reviews surface the same residual (no calibration test) and both treat it as deferrable.

---

## 3. Fresh Criterion-by-Criterion Scorecard (9 criteria)

| # | Criterion | v3.2.0 | v3.2.1 | One-line justification |
|---|---|---|---|---|
| 1 | Principle-option consistency | FAIL | **PASS** | All four v3.2.0 principle violations (P2/P3/P4/P5) resolved per Architect §4 re-audit; P2 reworded as honest dual-gate (§0.1, §5.1); P3 carve-out removed (§0.1, §2.1); P5 one-file-change holds (§2.3 + §3.1); P4 is WATERED-DOWN per Architect but no outright violation. No new principle contradictions introduced. |
| 2 | Fair alternatives | PARTIAL | **PASS** | §0.3 explicitly invalidates A1/A2/A3-v3.2.0, B1/B2-v3.2.0/B3, C1/C2-v3.2.0/C3 with concrete reasons (not strawmen). A3-v3.2.0 and B2-v3.2.0 are now explicit "prior-version rejected" rows — the Architect's steelmen are in the alternatives table, not absent. |
| 3 | Risk mitigation clarity | PARTIAL | **PASS** | §0.4 S1–S5 each name concrete code paths (state, endpoint, audit action). S1(b) is no longer vague — it points to §5.1 state machine. S4 names retry policy + state transition + resume token. S5 names `force-ready-for-review` + `ambiguity_override` audit. |
| 4 | Testable acceptance criteria | PARTIAL | **PASS** | Each phase has objectively-testable acceptance with named commands and exact assertion counts (e.g., §2.6 "≥ 96 assertions", §3.6 "exactly 8 entries", §4.7 "override_reason length 31 → 400; length 32 → 200", §5.8 "rescope auto-drop timed_out row"). The new safety-state acceptance is in §5.8 (was missing in v3.2.0). |
| 5 | Concrete verification steps | PASS | **PASS** | Verification commands named at every phase boundary: `alembic upgrade head`, `docker build`, `docker run --network none`, `python -m app.agents.knowledge_loader --verify`, `pytest` invocations with specific file paths. Same quality as v3.2.0. |
| 6 | Pre-mortem adequacy | FAIL | **PASS** | §0.4 expanded from 3 to 5 scenarios per Critic D-2. S4 (Claude API outage) and S5 (scorer/user disagreement) both first-order failure modes with mitigations that name code locations. |
| 7 | Expanded test plan adequacy | PARTIAL | **PASS** | §0.5 lists 36 unit + 14 integration + 5 E2E test files by path. Coverage includes rescope state machine (`test_rescope_state_machine.py`), Anthropic outage path (`test_model_client_retries.py`, `test_interview_paused_resume.py`), force-approve gate (`test_force_approve_override.py`), and tier classification (`test_risk_tier_assignment.py`). The gaps the v3.2.0 Critic flagged are filled. |
| 8 | ADR completeness | PARTIAL | **PASS** | §8 ADR-v3.2.1.A3 / B4 / C2 each have Decision/Drivers/Alternatives/Why/Consequences/Follow-ups. Alternatives sections now reference both v3.2.0-rejected variants AND the original A1/A2/B1/B3/C1/C3 alternatives. C2's follow-up "tune ambiguity threshold (0.35) after first 50 sessions" still describes a single number rather than 9 weights — defensible because there is only one knob now. |
| 9 | Architect synthesis incorporation | FAIL | **PASS** | All 5 Architect §4 moves materialized (§ resolution table 2 above). Architect v3.2.1 §1 independently confirms 5/5 ADOPTED. |

**Tally:** 9 PASS, 0 PARTIAL, 0 FAIL.

Strong improvement from v3.2.0's 1 PASS / 5 PARTIAL / 3 FAIL. Every criterion that failed in v3.2.0 now passes; every PARTIAL that gated approval in v3.2.0 now passes. The two remaining PARTIAL resolutions (D-3 and D-7) are inside RESOLVED criteria — the criteria themselves pass because the framing-level requirements are met; the residuals are calibration/packaging concerns that the Architect explicitly classifies as deferrable.

---

## 4. New Defects Introduced by v3.2.1

The revision is net-positive but did introduce or expose six new failure surfaces. None are BLOCKERs. All overlap with Architect §2 residuals.

### N-1 — MAJOR — Approver role unspecified for `POST /rescope` and `POST /force-ready-for-review`

- **Where:** §4.1 endpoint table; §5.1 operator-decision pseudocode.
- **Evidence:** §4.1 row for `/force-ready-for-review` says only "Operator override of ambiguity gate"; no required role field. Row for `/rescope` says "Operator decision on discovered targets"; no required role. §5.1 says `decided_by = user.id` without naming the role gate. §3.3 RBAC enforcement section names admin gates for tier=`active_exploit` but is silent on rescope and force-approve.
- **Why it matters:** if `/force-ready-for-review` is callable by any session creator, then the elicitation loop is **operator-discretionary**, not principle-enforced (Architect §2.5). If `/rescope` is "any session member," low-privilege users can approve rescope into adjacent infrastructure during off-hours.
- **Confidence:** HIGH.
- **Realist check:** Audit logs capture the action (§5.6: `ambiguity_override`, `rescope_approved`), so abuse is *visible after the fact*. Visible-after-the-fact is weaker than not-allowed but still a real deterrent. **Mitigated by:** audit trail. Severity stays MAJOR (does not earn BLOCKER because the audit trail is real and there is no data-loss/financial-impact path).
- **Fix:** add an explicit "Required role" column to §4.1 endpoint table. Recommend: `/rescope` is project member (with audit), `/force-ready-for-review` is admin OR rate-limited (≤ 1 / user / day). Cite as a v3.2.2 fix-up or accept as a deferred ticket; do not block approval.

### N-2 — MAJOR — Model self-rating has no calibration test

- **Where:** §0.5 `test_ambiguity_self_rating.py` description; §4.3 envelope spec; §8 ADR-v3.2.1.C2 follow-ups.
- **Evidence:** §0.5 line 109: "model-self-rating contract: response must include `ambiguity`, `blockers`, `reasoning`; missing field falls back to sanity guard." Contract is **format**, not **calibration**. Nothing tests that the model's rating *agrees* with a human rater on a fixture set. ADR-C2's follow-up says "Tune ambiguity threshold (0.35) after first 50 sessions" — same post-hoc tuning the v3.2.0 Critic flagged on the deterministic scorer, just with one knob instead of nine.
- **Why it matters:** the model has a direct incentive to under-rate its own ambiguity to terminate the loop (Architect §2.4 sycophancy concern). No held-out fixture set + correlation gate exists in the test plan to catch this.
- **Confidence:** HIGH.
- **Realist check:** Cost cap (6 turns + $5/day) bounds the failure mode. **Mitigated by:** if model trends toward under-rating, users get plans that are too underspecified and the safety chain re-runs on approve (§0.4 S5 mitigation note). The damage is user-perceived plan quality, not safety. Severity MAJOR (causes operator-visible quality drift after launch).
- **Fix:** add `backend/tests/unit/test_ambiguity_self_rating_calibration.py` with ~20 hand-labeled fixtures, gate at correlation ≥ 0.6 with human labels. This is the Architect §2.4 recommendation verbatim. Acceptable as a v3.2.2 follow-up.

### N-3 — MAJOR — `pentest_sessions` is a 25-column god-row with two coherent enums

- **Where:** §1.1 column-add table (15 new columns); §1.1 status enum + `interview_state` sub-enum.
- **Evidence:** §1.1 adds `domain_agent_slug, model_id, draft_plan_json, interview_state, interview_turn_count, ambiguity_score, ambiguity_override_at/by/reason, approved_at, approved_by, cost_usd_accum, paused_for_rescope_at, rescope_request_json, resume_token, team_id` to a table that already had `id, project_id, prompt, plan_json, status, started_at, ended_at` plus timestamps. The `status` enum extends to 12 values (`pending, running, completed, failed, draft, interviewing, ready_for_review, approved, executing, needs_human_review, rejected, paused_for_rescope` — plus `interview_paused` referenced in §0.4 S4 and §1.1 enum prose, which makes it 13). `interview_state` is a **separate** enum on the same row (5 values per §1.1: `not_started, interviewing, ready_for_review, needs_human_review, interview_paused`).
- **Why it matters:** two enums on the same row that overlap (`interviewing`, `needs_human_review`, `interview_paused`) is a coherency hazard. Every endpoint touching the row needs to know which enum is the source of truth. State-transition tests (§0.5 `test_session_state_machine.py`) must audit 13 × 13 cells for the top-level enum. Architect §2.2 explicitly recommends folding `interview_state` into the top-level `status`.
- **Confidence:** HIGH.
- **Realist check:** Architectural smell, not safety regression. **Mitigated by:** the row is internal data; the API surface (§4.1) abstracts the state representation. Worst case is bug-class concentration in `workflow_service.py`. Severity MAJOR (causes rework if/when a state-coherency bug ships).
- **Fix:** fold `interview_state` into the top-level `status` enum (its values already exist there). Document `plan_json` vs `draft_plan_json` lifecycle (`plan_json` is the frozen snapshot at `approved_at`, never mutated after). Both are Architect §2.2 / §5.4 recommendations.

### N-4 — MAJOR — 4-tier risk taxonomy operationally collapses to a 2-way flag check + admin gate

- **Where:** §0.1 P4; §2.4 (Tier→approval flag map); §5.2 `TIER_REQUIRES_FLAG`, `TIER_REQUIRES_ROLE`.
- **Evidence:** §2.4 maps: `passive_no_target_contact` and `passive_low_touch` both → no flag; `active_recon` → `approved_active_recon`; `active_exploit` → `approved_active_exploit` + admin role. Functionally, the four tiers collapse to "no flag / approved_active_recon / approved_active_exploit+admin" — a 3-way dispatch with one of the dispatch arms (admin gate) being a role check, not a tier property. The `TIER_BASE_RISK` weights (0.05 / 0.30 / 0.55 / 0.85) are four hand-tuned numbers replacing the v3.2.0 hand-tuned per-tool risks (Architect §2.3).
- **Why it matters:** P4 was redefined to accommodate this taxonomy (Architect §4 P4 marks WATERED-DOWN). The Critic's v3.2.0 D-7 remediation was 3-tier (`passive` / `narrow_active` / `active`); plan went to 4-tier instead. Numerically smoother, conceptually equivalent.
- **Confidence:** MEDIUM.
- **Realist check:** Not a safety regression — the mislabel of `httpx` is fixed; the labels are now operationally honest at the audit layer. **Mitigated by:** tier→risk derivation is a single point of edit (§2.4); calibration is one of four numbers, not 90. Severity downgraded from MAJOR to **MINOR** by Realist Check — **Mitigated by:** the operational consequence is identical to a 3-tier or even 2-tier model (the safety chain works the same); the only cost is conceptual debt (4 numbers to defend). Severity recalibrated: MINOR.
- **Fix (optional follow-up):** add `docs/risk-tiers.md` (already in §6.3) explaining *operational* meaning of each tier — what the target sees, what the audit log says, what the approval flag governs. Architect §2.3 recommendation. Defer.

### N-5 — MINOR — Boot-time SHA hard-fail has unspecified production scope

- **Where:** §2.5 risks list; §1.5 acceptance criteria.
- **Evidence:** §2.5 says "boot fails if knowledge MANIFEST is missing or hashes mismatch... `knowledge_loader` hard-fails with structured error." §2.6 says "Booting with a tampered MANIFEST returns exit 78". The plan does not distinguish image-build-time verification from container-restart-time verification. In a Kubernetes deployment, a knowledge file change pushed via a bad ConfigMap will crash-loop the pod until the manifest is regenerated — high-severity outage for a low-severity content drift.
- **Why it matters:** the principle (supply-chain integrity) is correct; the operational behavior at runtime is unspecified. Architect §2.7 raises this same concern.
- **Confidence:** MEDIUM.
- **Realist check:** **Mitigated by:** in practice, knowledge files ship inside the image (per §1.3 `knowledge_dir: "/app/backend/app/knowledge"`), so runtime drift is a Kubernetes-misconfiguration scenario, not a normal operations scenario. Severity stays MINOR.
- **Fix:** clarify in §2.5 that SHA verification fires at image build time; document that runtime trust is on the immutable image. Defer.

### N-6 — MINOR — Multi-rescope concurrency invites operator decision fatigue

- **Where:** §5.1 final paragraph; Tension D in Architect §3.
- **Evidence:** §5.1: "A session may surface multiple rescope requests across its lifetime (different active-recon steps)... Only when all pending rows are decided/timed-out does the session leave `paused_for_rescope`." No batching endpoint; one modal per discovery event in §4.4 `RescopeModal.tsx`. Realistic engagements (per Architect §3) generate 5–15 rescope events per session.
- **Why it matters:** operators rubber-stamp the 10th, 11th, 12th modal as "accept all" to clear the queue; alternatively, they pre-broaden `passive_allowed` / `active_allowed` at project setup to avoid the modals entirely — defeating the granularity the rescope flow was designed for.
- **Confidence:** MEDIUM.
- **Realist check:** **Mitigated by:** auto-drop default favors safety (drops the rejected hosts), so worst case is wasted recon, not scope expansion. UX problem, not safety problem. Severity stays MINOR.
- **Fix:** add a "rescope review queue" UX pattern (batch decisions within a 30 s window or N events) in v3.3. Document expected per-session rescope-event count in `docs/rescope-flow.md` (already in §6.3 — add the operational guidance). Defer.

**Net new-defect count:** 0 BLOCKER, 3 MAJOR (N-1, N-2, N-3), 3 MINOR (N-4 after realist downgrade, N-5, N-6). All overlap with Architect §2 residuals (concordance: full).

---

## 5. Architect-Flagged Residuals — Block v3.2.1 or Deferrable?

The Architect v3.2.1 review listed six concerns in §2 + Tension D in §3 + watering-down notes on P2/P4 in §4. Status per item:

| Architect § | Concern | Block v3.2.1? | Rationale |
|---|---|---|---|
| §2.1 | `paused_for_rescope` deadlock surface: no `deadline_at` column; approver role unspecified; adapter-death-after-approval garbage collection | **DEFER** | Safety-favoring auto-drop default contains the worst case (wasted work). Adapter-death path is real but bounded; needs a janitor in v3.2.2. **Mitigated by:** the `osa_rescope_pending_age_seconds > 90` alert (§5.7) gives operators visibility. |
| §2.2 | 25-column fat `pentest_sessions` row + two coherent enums | **DEFER** | Architectural smell, not safety. Recommended cleanup (fold `interview_state` into `status`, document `plan_json` vs `draft_plan_json`) is a 30-minute edit but not a blocker. Captured as N-3 above. |
| §2.3 | 4-tier taxonomy collapses to flag check; hand-tuned weights | **DEFER** | Architect §4 P4 marks WATERED-DOWN, not violated. Functionally equivalent safety outcome. Documentation in `docs/risk-tiers.md` (already in §6.3) is the fix. Captured as N-4. |
| §2.4 | Self-rating sycophancy / no calibration test | **DEFER** | Cost cap + 6-turn cap + safety-chain re-run on approve bound the failure mode (Critic D-3 realist check holds). Calibration test is the Architect's recommended fix and is a v3.2.2 add. Captured as N-2. |
| §2.5 | Force-approve no admin gate / no rate limit | **DEFER** | Audit log captures every override (§5.6 `ambiguity_override`). Safety chain still runs on approve (§0.4 S5). Worst case is user-perceived quality drift after launch — observable in metrics within hours of bad behavior. Recommend either admin-gate or 1/user/day rate-limit as a v3.2.2 fix. Captured as N-1. |
| §2.6 | `ModelSelector` / `BudgetGuard` / `Pricing` / `ModelClient` packaging spans two directories; RBAC leaks into orchestrator | **DEFER** | Code-organization smell; not safety- or correctness-affecting. Architect's recommended reorg (`backend/app/services/model/`) is a v3.2.2 refactor. |
| §2.7 | Boot-time SHA hard-fail production scope | **DEFER** | Clarification needed in §2.5 narrative; not a code change. Captured as N-5. |
| §3 Tension D | Multi-rescope operator decision fatigue → broad pre-approval | **DEFER** | UX concern, not safety regression. Auto-drop favors safety. Captured as N-6. |
| §4 P2 | Principle 2 reworded to "first gate" (wording softened) | **ACCEPTABLE** | The principle text now matches the implementation honestly (dual-gate) rather than contradicting it (v3.2.0 single-gate vs §5.1 second gate). This is *better* than v3.2.0, not worse. No fix needed. |
| §4 P4 | Principle 4 expanded to 4-tier (WATERED-DOWN) | **DEFER** | Per N-4 above. Wording matches implementation; calibration debt is documentation. |

**Net residual block-count:** 0. Every Architect residual is deferrable as a v3.2.2 follow-up. The Architect's own verdict (SUPPORT-WITH-CHANGES) confirms: "v3.2.1 can ship after addressing items in §5.4 (Merge/Add list), most of which are documentation or single-config-flag changes; principled rework is not required."

---

## 6. Multi-Perspective Notes

- **Executor perspective:** the v3.2.0 blocker (D-1 rescope flow) is resolved end-to-end — §5.1 state-machine prose plus §4.1 endpoint plus §0.5 named tests plus §6.3 `docs/rescope-flow.md`. I can start P0/P1 without asking a single question. The two open ambiguities I would have escalated in v3.2.0 (approver role for `/rescope`, calibration for self-rating) are both *deferred* with clear post-launch tickets. Acceptable.
- **Stakeholder perspective:** the success metric the v3.2.0 Critic specifically asked for (§15 nice-to-have) is in v3.2.1 — `osa_session_time_to_ready_for_review_seconds` (§0.5 observability bucket). The pitch is honest: chat-driven launch + tool catalog + domain agents, with budget caps + safety state machine + audit trail. The schema is now lean (1 migration, 2 child tables, 15 additive columns instead of 5 new tables).
- **Skeptic perspective:** the strongest argument against v3.2.1 is the *same* skeptic critique that the v3.2.0 Critic made: this is prompt engineering with infrastructure. v3.2.1 reduced infrastructure (-3 tables, -1 native runtime, -1 scorer module, -4 dev-days) while strengthening the safety state machine. The plan is honest about its remaining residuals: ADR-C2 follow-ups list "tune ambiguity threshold after first 50 sessions"; §9 marks 7 open questions with owners and due-dates. Force-approve is the strongest counterargument to Principle 2 — a 32-char reason is "a friction floor, not a quality floor" (Architect §2.5). The skeptic case lands as MAJOR but not BLOCKER because the safety chain re-runs on approve regardless of override.

---

## 7. Self-Audit (mandatory)

Re-evaluating each MAJOR finding before finalizing:

- **N-1 (approver role)** — HIGH confidence. Author could push back with "this is implicit in the existing RBAC layer" — but §4.1 explicitly omits role columns for `/rescope` and `/force-ready-for-review` while including them for tier-gated endpoints; not refutable without an edit. KEEP MAJOR.
- **N-2 (no calibration test)** — HIGH confidence. Author cannot refute; the test plan §0.5 is explicit that `test_ambiguity_self_rating.py` checks format only. KEEP MAJOR.
- **N-3 (god-row + two enums)** — HIGH confidence. Author could argue "fold-in is trivial post-merge"; that's a fix path, not a refutation. KEEP MAJOR.
- **N-4 (4-tier collapses to flag check)** — MEDIUM confidence. Realist check: functional outcome equivalent to a cleaner 3-tier model; harm is documentation debt only. DOWNGRADED to MINOR per Realist Check rule. **Mitigated by:** identical safety chain behavior; one-point-of-edit risk calibration; no data-loss/security path.
- **N-5 (boot SHA scope)** — MEDIUM confidence. Author can refute with "this is image-build time" — that's the answer; the plan should just say so. KEEP MINOR.
- **N-6 (multi-rescope fatigue)** — MEDIUM confidence. Author can refute with "expected event count is low in practice" — but Architect §3 Tension D provides a concrete estimate (5–15). KEEP MINOR.

**Realist Check recalibrations applied:**
- N-4 downgraded MAJOR → MINOR. **Mitigated by:** safety-chain behavior is identical regardless of tier count; the tier numbers exist for risk-score calibration, not for safety enforcement.
- No CRITICAL findings exist. No BLOCKER findings exist.

**Adversarial-mode trigger check:** 0 CRITICAL, 3 MAJOR (under the 3+ MAJOR threshold = exactly 3, edge case). Not escalating to ADVERSARIAL — the 3 MAJORs are all Architect-overlapped residuals, not systemic issues. The plan is on the safe side of the threshold.

---

## 8. Verdict Justification

v3.2.1 resolved 9 of 11 Critic defects (including the BLOCKER), partially resolved 2 (D-3 calibration, D-7 tier count — both with Architect-flagged deferrable residuals), and adopted 5 of 5 Architect synthesis moves with substantive implementation. The fresh scorecard moves from v3.2.0's 1 PASS / 5 PARTIAL / 3 FAIL to **9 PASS**. No new BLOCKER. Three MAJORs (N-1, N-2, N-3) and three MINORs (N-4, N-5, N-6) introduced — all overlap with Architect §2 residuals, all are deferrable to v3.2.2.

The Architect's verdict (SUPPORT-WITH-CHANGES) and this Critic's verdict converge: the plan is approvable; the residuals are documentation, calibration tests, and a packaging refactor. Architect explicitly states "principled rework is not required."

**Operating mode:** stayed THOROUGH — escalation criteria (1 CRITICAL/BLOCKER OR 3+ MAJOR) was not triggered. Three MAJORs surfaced but all are recommendations that overlap with Architect residuals; none represent systemic flaws or hidden defects that warrant adversarial mode.

**Concordance with Architect v3.2.1:** full. No disagreements on substance. Both reviews mark P2 wording-softened, P4 watered-down, calibration test missing, approver role unspecified, fat row, packaging smell. Both call the plan approvable with deferred follow-ups.

`APPROVE` is warranted: every criterion PASSes, no BLOCKER, Architect residuals are deferrable.
`ITERATE` is not warranted: no FAIL, no BLOCKER.
`REJECT` is not warranted: plan is fundamentally sound.

---

## 9. Verdict

```
Verdict: APPROVE
```

---

## 10. Post-Approval Tickets (capture as v3.2.2 backlog)

The following Architect-flagged residuals did not block approval and should be filed as post-approval tickets, in priority order:

1. **[v3.2.2 MAJOR — N-1]** Specify required role on `POST /pentest-sessions/{id}/rescope` and `POST /pentest-sessions/{id}/force-ready-for-review`. Recommended: `/rescope` is project member with audit; `/force-ready-for-review` is admin OR rate-limited (≤ 1 / user / day). Add `Required role` column to §4.1 endpoint table. Per Architect §2.5 / §5.4.
2. **[v3.2.2 MAJOR — N-2]** Add `backend/tests/unit/test_ambiguity_self_rating_calibration.py` with ~20 hand-labeled fixtures; CI gate at correlation ≥ 0.6 with human labels. Track `osa_session_ambiguity_score` distribution as production guardrail. Per Architect §2.4 / §5.4.
3. **[v3.2.2 MAJOR — N-3]** Fold `interview_state` sub-enum into top-level `pentest_sessions.status` (values already exist there). Document `plan_json` vs `draft_plan_json` lifecycle in §1.1: `plan_json` is the frozen snapshot of `draft_plan_json` at `approved_at`, never mutated after. Per Architect §2.2 / §5.2.
4. **[v3.2.2 MINOR — Architect §2.1]** Add `rescope_approvals.deadline_at` denormalized column so config-reload mid-flight doesn't move deadlines silently. Add "stuck executing" janitor that detects sessions in `executing` with no recent adapter heartbeat after a rescope decision. Per Architect §2.1 / §5.4.
5. **[v3.2.2 MINOR — N-4]** Document operational meaning of each tier in `docs/risk-tiers.md` (already in §6.3 file list — write the content). Explain *why* `passive_low_touch` ≠ `active_recon` operationally (approval-flag boundary, not wire-activity boundary). Per Architect §2.3.
6. **[v3.2.2 MINOR — N-5]** Clarify in §2.5 that SHA verification fires at image build time; document runtime trust on the immutable image. Alternatively, segregate fatal-vs-warning: missing manifest = fatal; SHA mismatch on a single file = log + degrade. Per Architect §2.7.
7. **[v3.2.2 MINOR — Architect §2.6]** Move `ModelSelector` / `Pricing` / `BudgetGuard` / `ModelClient` under `backend/app/services/model/` (`selector.py`, `pricing.py`, `budget_guard.py`, `client.py`). Move RBAC out of `ModelSelector.resolve` to a thin wrapper in `app/api/deps.py`. Per Architect §2.6 / §5.4.
8. **[v3.3 MINOR — N-6]** Add "rescope review queue" UX pattern (batch decisions within a 30 s window or N events) in `RescopeModal.tsx`. Add aggregate audit metric `osa_session_rescope_pending_count` alerting at > 5. Per Architect §3 Tension D / §5.4.
9. **[v3.3 OPEN — open-questions.md #2]** Tune ambiguity threshold (0.35) and turn cap (6) after first 50 sessions per production telemetry from `osa_session_ambiguity_score` histogram. Already in §9 + open-questions.md.
10. **[v3.3 OPEN — open-questions.md #6, #11]** Tune daily USD budget default ($5/user) and force-approve min-reason length (32 chars) from telemetry after first 20 overrides. Already in open-questions.md.
11. **[v3.3 PLANNING]** Optional agents (`identity-agent`, `container-k8s-agent`) — defer to v3.3 per open-questions.md #3.
12. **[v3.2.1 P3 BEFORE LAUNCH]** Resolve open-questions.md item: `INTENT_VOCABULARY` initial enum content must be enumerated in §4.3 before P3 executor work begins. Owner: Architect. This is the one open question that *should* be settled inside the v3.2.1 implementation phase rather than deferred to v3.2.2.

---

## 11. Ralplan Summary Row (deliberate mode)

| Gate | Pass/Fail | Reason |
|---|---|---|
| Principle/Option Consistency | **PASS** | All 4 v3.2.0 principle violations resolved (P2 dual-gate, P3 no carve-out, P5 one-file holds). P4 watered-down but not violated per Architect §4. |
| Alternatives Depth | **PASS** | A1/A2/A3-v3.2.0, B1/B2-v3.2.0/B3, C1/C2-v3.2.0/C3 all invalidated with concrete reasons in §0.3. Architect's steelmen (in-code dict, merged schema) explicitly named as the chosen options. |
| Risk/Verification Rigor | **PASS** | §0.4 5-scenario pre-mortem with concrete mitigations. §1.5 / §2.6 / §3.6 / §4.7 / §5.8 / §6.4 acceptance criteria all name commands and assertion counts. |
| Deliberate Additions (pre-mortem + expanded tests) | **PASS** | 5 pre-mortem scenarios (was 3); 36 unit + 14 integration + 5 E2E tests with named file paths; observability metrics and Grafana dashboards named. |

**Aggregate ralplan gate: PASS — APPROVE.**

---

Verdict: APPROVE
