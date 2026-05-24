# Architectural Review — `offensive-security-agent-consensus-v3.2.1`

**Reviewer:** Architect (consensus stage of `/ralplan --consensus --deliberate`, iteration 2)
**Plan under review:** `.omc/plans/offensive-security-agent-consensus-v3.2.1.md`
**Predecessors consumed:** v3.2.0 plan; v3.2.0 architect review; v3.2.0 critic review (verdict ITERATE)
**Date:** 2026-05-12
**Mode:** deliberate

This review focuses on **what changed** vs. v3.2.0 and whether the v3.2.0 synthesis moves actually landed in the new plan, plus fresh failure surfaces that the revision created.

---

## 1. Delta Assessment — v3.2.0 Architect §4 Synthesis Moves

| Move (from v3.2.0 architect §4) | Status | v3.2.1 section that implements it | Notes |
|---|---|---|---|
| **Merge `workflows` into `pentest_sessions`** (§4.4 first half) | **ADOPTED** | §1.1 column-add table + §1.1 "What was removed vs v3.2.0" + §7 Migrations Summary | Single migration `003_session_workflow_columns.py`, additive columns + extended status enum. `workflows` and `workflow_messages` extras gone; `executed_session_id` forward pointer gone. Architect §1.4 / Critic D-5 cleared. |
| **Drop `domain_agents` + `domain_agent_tools` tables** (§4.4 second half) | **ADOPTED** | §1.1 removal list + §3.1 `DOMAIN_AGENTS` dict + §2.3 `ToolEntry.applicable_domain_tags` + §3.2 2-line `palette_for()` | Tool→domain metadata now lives on `ToolEntry`. `DomainAgentResolver` class collapses to a function. Adding a tool is one file (registry.py). Architect §3.4 / Critic D-6 cleared. |
| **Single shared `osint-passive` Docker image** (§4.2 + §4.7) | **ADOPTED** | §2.1 row "Entrypoints inside `osa-passive-recon:latest`"; §2.2 `docker/passive-recon/Dockerfile` with 8 entrypoints; §0.1 Principle 3 reworded ("There is no native execution carve-out") | `NativePassiveAdapter` removed entirely. Egress now Docker-netns + app-layer allowlist (defense in depth) instead of homegrown sandbox. Architect §3.2 / Critic D-4 cleared. |
| **`paused_for_rescope` state + endpoint** (§4.5) | **ADOPTED** | §0.1 Principle 2 rewrite ("rescope is a second, equally explicit gate"); §1.1 `paused_for_rescope_at` + `rescope_request_json` columns + new `rescope_approvals` table; §4.1 `POST /rescope` endpoint; §5.1 full state-machine prose with transition rules, operator endpoint behavior, timeout policy, multi-rescope concurrency rule | Most thoroughly implemented move in the revision. Architect §3.1 BLOCKER / Critic D-1 BLOCKER cleared. |
| **Model self-rated ambiguity** (§4.2 first item) | **ADOPTED** | §4.3 dropped the 9-component deterministic scorer; model returns `{ambiguity, blockers, reasoning, draft_plan_json}` envelope; `min_required_fields_present` sanity guard is the only deterministic floor; force-approve override path added | Deterministic scorer retained only as a description of what was dropped; not shipped behind a flag as Critic D-3 hedge suggested, but the sanity guard + force-approve + cost cap combination is acceptable. |

**Adoption score: 5/5 ADOPTED.** All five synthesis moves from the prior architect review landed in v3.2.1 with substantive implementation rather than cosmetic acknowledgment.

---

## 2. New Steelman Antithesis — Fresh Failure Surfaces Created by the Revision

Adopting the prior synthesis moves resolved old problems but created new ones. Probing each:

### 2.1 `paused_for_rescope` deadlock risk

§5.1 specifies: enter `paused_for_rescope` on rejection; exit on operator decision OR auto-drop after `rescope_decision_timeout_seconds` (default 300 s). Background job scans `WHERE status='pending' AND requested_at < now() - timeout` every 30 s.

**The deadlock surface that survives:**
- Multi-rescope concurrency rule (§5.1 final paragraph): "While `status='pending'`, the session stays in `paused_for_rescope`. Only when *all pending rows* are decided/timed-out does the session leave."
- This means **any** single never-timed-out row blocks the whole session. The 30 s scan is correct, but: what if the timeout job itself is paused (deploy, restart, lag)? `osa_rescope_pending_age_seconds > 90` alerts at 90 s — that's helpful for operators, but not a circuit breaker.
- §1.1 has no `rescope_approvals.deadline_at` column. Timeout is computed by `requested_at + setting`. If `rescope_decision_timeout_seconds` is changed at runtime (config reload), in-flight rows silently move their deadlines — the operator's mental model of "I have 5 minutes" breaks.
- Adapter task awaits resolution "via redis/event" (§5.1 line 17). If the adapter process dies after registering its wait but before the resume event fires, who garbage-collects? `rescope_approvals.status='approved'` is set, but the adapter never resumed; the session sits in `executing` per the state machine while no work is happening.
- Approver identity ambiguity: §4.1 lists `POST /rescope` without naming required role. Operator? Admin? Original creator? If it's "any session member," then any low-privilege user can approve rescope into adjacent infrastructure. If it's admin-only, then a session that has multiple rescope events during off-hours stalls. **The plan does not specify.**

**Severity:** MEDIUM. The auto-drop default is safety-favoring (drops rejected, doesn't auto-approve), so worst case is wasted work, not scope expansion — but the *adapter death after approval* path can lose state silently.

**Recommendation:** add `rescope_approvals.deadline_at` (denormalized), name the approver role on `POST /rescope`, and add a "stuck executing" janitor that detects sessions in `executing` with no recent adapter heartbeat after a rescope decision.

### 2.2 Fat `pentest_sessions` table after schema merge

§1.1 adds **15 columns** to `pentest_sessions`. The merged status enum has **12 states** (`pending|running|completed|failed|draft|interviewing|ready_for_review|approved|executing|needs_human_review|rejected|paused_for_rescope`). The table now carries:

- workflow-draft state (`draft_plan_json`, `interview_state`, `interview_turn_count`, `ambiguity_score`)
- approval/audit state (`approved_at`, `approved_by`, `ambiguity_override_*`)
- billing state (`cost_usd_accum`, `model_id`)
- execution recovery state (`resume_token`, `paused_for_rescope_at`, `rescope_request_json`)
- team-pool state (`team_id`)
- plus pre-existing `prompt`, `plan_json`, `status`, `started_at`, `ended_at`

**The antithesis:** this is now a 25-column god-table with three orthogonal lifecycles (draft → approval → execution + rescope) crammed into one `status` enum. The earlier critique of `ModelRouter` as a god-class (Critic D-8, addressed by decomposition into four classes) applies to *this row* now. Every endpoint that touches a session has to be careful about which lifecycle phase the row is in. State transition validation logic (mentioned in §1.5 `test_session_state_machine.py`) has 12 × 12 = 144 transition cells to audit (most illegal, but each must be tested).

**Is the merge cheaper than two tables, all in?** Probably yes — joins avoided, FK chain avoided. But:
- `draft_plan_json` and `plan_json` (the pre-existing column) coexist. §1.1 says `draft_plan_json` "replaces transient drafting in `AttackPlanner`." So what's the relationship? When does `plan_json` get populated — on approve? Plan doesn't say.
- `interview_state` is "sub-state to `status`" (§1.1 row). That's a second state machine inside the first. Now there are two enums to keep coherent (`status='interviewing'` ⊕ `interview_state='interviewing'`).

**Severity:** LOW-MEDIUM. Real maintenance smell but not a safety regression.

**Recommendation:** explicitly document the `plan_json` vs `draft_plan_json` relationship in §1.1 (proposal: `plan_json` is set on `approved_at` as a snapshot of `draft_plan_json`, then frozen). Remove `interview_state` sub-enum — fold its values into the top-level `status` enum (it's already there: `interviewing`, `needs_human_review`, `ready_for_review`, `interview_paused`).

### 2.3 4-tier risk taxonomy: is `passive_low_touch` meaningfully different from `active_recon`?

§0.1 Principle 4 and §5.2 define four tiers:

| tier | wire to target | example tools |
|---|---|---|
| `passive_no_target_contact` | none | `dns_resolver`, `cert_transparency`, `mx_spf_dmarc`, `cert_chain` |
| `passive_low_touch` | some | `httpx`, `robots_sitemap`, `well_known`, `securitytxt`, `wappalyzer`, `secret_scan` |
| `active_recon` | enumeration | `subfinder`, `dnsx`, `cloudenum`, `nmap`, `nuclei` |
| `active_exploit` | exploit | `metasploit`, `pyrit` |

**The antithesis:**
- `httpx -status-code -title -tech-detect` (tier 2) sends a real GET to the target. `subfinder -active` (tier 3) does DNS queries and HTTP requests through projectdiscovery infrastructure. From the target's WAF perspective, both leave footprints. The wire-activity boundary between tiers 2 and 3 is **operationally fuzzy**.
- `TIER_BASE_RISK` weights (§5.2) are 0.05 / 0.30 / 0.55 / 0.85 — **a 25-point gap between tier 2 and tier 3, but only 5-point gap between tier 1 and... wait, 25-point gap between tier 1 and tier 2**. The numbers are even more hand-tuned than v3.2.0's binary, because there are now 4 tunable values instead of 1 threshold.
- `passive_low_touch` and `active_recon` differ on the *approval flag*, not on what reaches the target's wire. So functionally, the 4 tiers reduce to: "needs flag" vs. "doesn't need flag" (binary), plus admin-only for `active_exploit` (a role check that could live on the tool, not the tier).
- The naming `passive_low_touch` itself betrays the difficulty: "passive but touches stuff" — exactly what v3.2.0's prior architect review §3.3 called out as the *failure of a binary label*. The plan moved from a binary to a 4-tier but kept the linguistic contradiction.

**Severity:** LOW. The tiers do useful work (single source of truth for risk, approval flag, role), but the *number* of tiers is over-fitted to the current tool list. A 3-tier model (passive / narrow_active / exploit) recommended in the v3.2.0 review would have been simpler and arguably more honest.

**Recommendation:** keep 4 tiers (already in the plan), but document in §5.2 *why* `passive_low_touch` ≠ `active_recon` operationally (it's the approval-flag boundary, not the wire-activity boundary), and add a tier-rationale doc (`docs/risk-tiers.md` is in §6.3 — make sure it explains the operational meaning of each tier, not just the cell values).

### 2.4 Model self-rating: same model drafts AND scores its own work — confound

§4.3 has the drafting model return `{ambiguity, blockers, reasoning, draft_plan_json}` in one envelope. Loop terminates at `ambiguity ≤ 0.35` or `turn_count ≥ 6`.

**The antithesis:**
- The model has a **direct incentive** to under-rate its own ambiguity to terminate the loop and avoid more turns. It is not an adversarial evaluator; it is the *same* model that drafted the plan, told its own draft is ambiguous, and asked to fix it. Then asked to grade itself.
- LLMs are known to exhibit sycophancy and self-confirmation bias in this exact setup ("rate your own answer"). Self-rated ambiguity will trend **downward over turns** by construction, regardless of the actual specificity gain.
- The threshold (0.35) is a number the model has to *internalize* — it is hand-tuned the same way the v3.2.0 weights were. ADR-v3.2.1.C2 follow-up admits: "Tune ambiguity threshold (0.35) after first 50 sessions." Same post-hoc tuning, fewer knobs.
- The thin sanity guard (`min_required_fields_present`) checks `target`, `intent`, `tier` — three fields. A plan can pass these three checks while being completely under-specified on scope, timing, or exploitation depth.
- §0.5's test `test_ambiguity_self_rating.py` says: "model-self-rating contract: response must include `ambiguity`, `blockers`, `reasoning`". The contract is **format**, not **calibration**. Nothing tests that the model's rating *agrees* with a human rater on a fixture set.

**Severity:** MEDIUM. Cost cap (6 turns, $5/day) bounds the failure mode. But user-perceived quality regresses if the model under-rates ambiguity and terminates prematurely.

**Recommendation:** ship a small held-out fixture set of ~20 hand-labeled "draft + human ambiguity score" examples; add a CI test that the model's rating correlates ≥ 0.6 with human labels. The deterministic scorer wasn't kept as fallback — that was Critic D-3's hedge — so add this calibration test as the equivalent guardrail. Track in observability: `osa_session_ambiguity_score` distribution; if it bimodally collapses to ≤ 0.35 within 2 turns on every session, we have evidence of model self-favorable bias.

### 2.5 Force-approve override breaks the gate it was meant to guard

§4.1 lists `POST /pentest-sessions/{id}/force-ready-for-review` with `override_reason: str (≥ 32 chars)`. §0.4 S5 mitigation: "the session still has to pass the safety-chain validation on approve — override only escapes the *elicitation* loop, never the safety chain."

**The antithesis:**
- Principle 2 says approval is the gate; the ambiguity loop is intended to *prevent under-specified plans from reaching approval*. Force-approve **collapses the elicitation loop into a single click + 32 chars of justification text**. Any user who finds the loop annoying will reliably force-approve.
- The 32-char minimum is trivially defeated ("we are time constrained today okay" = 32 chars). It is a friction floor, not a quality floor.
- §4.1 says `POST /force-ready-for-review` is available to any session creator (RBAC: not explicit; row "Operator override of ambiguity gate" doesn't name a role). If any creator can override, then the elicitation loop is **operator-discretionary**, not principle-enforced.
- The safety chain absolutely *does* still run on approve — that is preserved. So the override doesn't enable scope blowback. But it **does** enable approval of plans whose ambiguity remains high, which is exactly what the elicitation loop was meant to prevent (per S3 mitigation).
- §0.4 S5 invented this mitigation to address the *user-vs-scorer disagreement* failure mode. But the user-vs-scorer disagreement only happens when the model rates ambiguity high *and the user disagrees*. The force-approve is therefore an **abdication** of the model's judgment — the very judgment the architecture is built on. If we trust the model enough to draft plans and rate them, we should not give the user a one-click override of the model's rating.

**Severity:** LOW-MEDIUM. Audit log captures the action (`ambiguity_override`), so abuse is visible — but visible-after-the-fact is weaker than not-allowed.

**Recommendation:** either (a) require admin role for force-approve (not just any creator), OR (b) rate-limit overrides per user per day (≤ 1 override / user / day), OR (c) display the override count on the admin dashboard with the audit log. Choose at least one; the current plan has none of the three explicitly.

### 2.6 Decomposed `ModelSelector` / `BudgetGuard` / `Pricing` / `ModelClient` — four classes vs. one

§1.2 splits the v3.2.0 `ModelRouter` god-class into four focused units across three modules:
- `backend/app/orchestrator/model_selector.py`
- `backend/app/services/pricing.py`
- `backend/app/services/budget_guard.py`
- `backend/app/orchestrator/model_client.py`

**The antithesis:**
- Decomposition is correct in principle (Critic D-8 demanded it), but the boundaries cross three packages (`orchestrator`, `services`, `services` again). Why does `ModelClient` live in `orchestrator/` while `BudgetGuard` lives in `services/`? Both are infrastructure-level concerns.
- `ModelSelector.resolve()` "raises `HTTPException(403)`" — that's an API-layer exception inside an orchestrator module. RBAC was meant to stay at the API layer (`app/api/deps.py`); now it leaks into the orchestrator.
- `BudgetGuard.check()` is called by `workflow_service.append_user_message` (§4.2). `Pricing.cost()` is called by `BudgetGuard` (to estimate). `ModelClient.send()` is called by `workflow_service`. Each call site has to wire up three of the four classes. Constructor injection vs. global instances is unspecified.
- The split is right; the *packaging* recreates Critic D-8's coupling problem in a different shape. A god-class became four classes that are 1:1 coupled — only the file boundaries changed.

**Severity:** LOW. Code smell, not a safety or correctness issue.

**Recommendation:** put all four under `backend/app/services/model/` (`selector.py`, `pricing.py`, `budget_guard.py`, `client.py`). Move RBAC from `ModelSelector.resolve` to a thin wrapper in the API layer (the `deps.py` already does `require_role`). Document the call-graph in `docs/model-service.md`.

### 2.7 Boot-time SHA hard-fail for knowledge packs — restart brittleness

§2.5 risks list: "boot fails if knowledge MANIFEST is missing or hashes mismatch. **Mitigation:** `knowledge_loader` hard-fails with structured error pointing at the failing path." Test in §1.5: "Booting with a tampered MANIFEST returns exit 78 with `knowledge_pack_sha_mismatch`."

**The antithesis:**
- Hard-fail on boot is correct for *supply-chain integrity* (a tampered methodology file should never load). But operationally:
- In a Kubernetes deployment, a knowledge file change pushed via a bad ConfigMap will **crash-loop the pod** until the manifest is regenerated. The blast radius is "API is fully down" for a *methodology content* drift. That's a high-severity outage for a low-severity bug.
- During development, every knowledge edit requires `python -m app.agents.knowledge_loader --regenerate-manifest && commit` — a two-step ceremony that will be skipped, then crash the next CI build.
- No graceful-degradation path: if `knowledge/cloud_aws/SKILL.md` is corrupt but `knowledge/web/SKILL.md` is fine, the whole platform is down — even sessions that have nothing to do with cloud-aws.
- §1.5 acceptance criterion says boot returns exit 78 on mismatch. But the broader implication — *every* pod restart, on a fresh image, must successfully verify the manifest — is not mentioned. If the manifest is shipped *with* the image (it should be), then drift is impossible at runtime — meaning the hard-fail only fires during development/build, never in production. So why is it a boot-time concern at all?

**Severity:** LOW. The risk is operational toil, not safety.

**Recommendation:** clarify in §2.5 that SHA verification fires at **image build time** (`docker build` stage), not at every container start. Production runtime should trust the immutable image. Alternatively, segregate fatal-vs-warning: missing manifest = fatal; SHA mismatch on a single file = log + degrade (don't load that domain agent's palette). Either path avoids whole-platform crash-loop on a single-file drift.

---

## 3. One New Tradeoff Tension (not in v3.2.0 review)

### Tension D — Multi-rescope concurrency vs. operator cognitive load (UNDER-ROTATED)

**The plan's claim** (§5.1 final paragraph): "A session may surface multiple rescope requests across its lifetime (different active-recon steps). Each is its own `rescope_approvals` row. While `status='pending'`, the session stays in `paused_for_rescope`. Only when all pending rows are decided/timed-out does the session leave."

**The under-rotation:**
- An active engagement against `acme.com` runs `subfinder`, `dnsx`, `cloudenum`, and `nuclei` (four `active_recon` tools per §2.3). Each can independently discover out-of-scope hostnames. In a realistic large-scope engagement, **5–15 rescope events per session is plausible**.
- Operators will see this as: open the Monitor page → 5–15 modals queue up → each requires accept/reject decisions on 1–N hostnames → 32-char reason for each.
- Decision fatigue is a known security risk: operators rubber-stamp the 10th, 11th, 12th modal as "accept all" to clear the queue.
- The alternative — batching rescope decisions across discovered targets within a time window — is *not in the plan*. There is no "batch rescope" endpoint, no aggregation view.
- The auto-drop timeout (300 s default) is per-row. If 10 rescope events arrive in 30 seconds and the operator is in a meeting for 6 minutes, all 10 auto-drop simultaneously. The session continues with 0 of the 10 discovered subdomains probed — operator returns to find the engagement effectively skipped half the recon surface.
- The plan correctly favored safety (auto-drop drops the rejected targets), but the **operator-experience cost is steep enough that operators will work around it** — most likely by pre-staging massive `passive_allowed` / `active_allowed` lists at project setup, defeating the granularity the rescope flow was designed for.

**The tension:**
- **Safety side** wants: every discovered hostname re-validated, every rescope an explicit decision with audit reason.
- **Usability side** wants: batched decisions, defaults that reduce per-event friction, summary review at session end rather than mid-flight modals.

These are in direct opposition. The plan picks the safety side without acknowledging the operator-experience pressure that will eventually erode the safety side from the other direction (broad pre-approval lists).

**Verdict:** the plan **under-rotates** on the operator-experience side. The principle is correct; the implementation pattern (one modal per rescope event, no batching) will produce broad upfront whitelisting in practice, which is the exact failure mode the rescope flow was designed to prevent.

**Recommendation:**
- Add a "rescope review queue" UX: discovered targets are queued, modal opens once N targets are queued or T seconds have passed; operator decides in batch.
- Add an aggregate audit metric: `osa_session_rescope_pending_count` per session; alert at > 5.
- Document in `docs/rescope-flow.md` (§6.3) the *expected* per-session rescope-event count for typical engagements, so operators set their `passive_allowed` / `active_allowed` lists thoughtfully without over-broadening.

---

## 4. Principle Violations Check (re-audit)

Auditing each of the 5 principles in §0.1 of v3.2.1 against the implementation in §1–§7:

### Principle 1 — Safety chain invariant
**Status: HONORED.** §0.1 unchanged; §2 / §5 wire every new tool through `WhitelistValidator → filter_plan_steps → RiskFilter → EgressMonitor`. The shared `osa-passive-recon` Docker image runs inside `ExecutionBackend`, so `egress_monitor` covers it. Force-approve override (§0.4 S5) is explicit that "override only escapes the elicitation loop, never the safety chain" — re-validation on approve is preserved. **Strongest principle in the plan, same as v3.2.0.**

### Principle 2 — AI plans are advisory until user approves
**Status: HONORED (after watering-down).** §0.1 was rewritten in v3.2.1 to explicitly acknowledge the second gate: "Approval is the first gate; discovered-target re-scope is a second, equally explicit gate." This **resolves the v3.2.0 contradiction** (where Principle 2 said "single gate" but §5.1 introduced a second). The principle is now *honest* about two gates rather than contradictorily claiming one.

**However**, the principle wording itself is **softened** — "the first gate" implies a series, which weakens "advisory until approved." The plan is now: "advisory until approved, then advisory again at each rescope event." That's defensible, but the principle's name no longer captures the full lifecycle. **Flag:** the principle was reworded to match the implementation (rather than the implementation being constrained to match the principle). Watered-down language: "first gate" vs. v3.2.0's "explicit approval [single]."

**Verdict: HONORED but Principle 2 was edited to fit the design; not the other way around.**

### Principle 3 — Tool wrappers must be sandboxed by default
**Status: HONORED.** §0.1 Principle 3 in v3.2.1 reads: "There is no native execution carve-out." This is a **strict improvement** over v3.2.0 where the principle had a self-immunizing carve-out for `NativePassiveAdapter`. The shared `osa-passive-recon:latest` image hosts all 7 validators + `secret_scan` (§2.2). Uniform isolation restored. **Strongest improvement in the revision.**

### Principle 4 — Risk is a 4-tier taxonomy
**Status: WATERED-DOWN (Principle redefined to match plan).** §0.1 in v3.2.0 said "active vs. passive is a first-class distinction." That was a clean binary. The v3.2.0 architect review §3.3 noted this binary was wrong (mislabeled `httpx`). The honest fix would be a 3-tier taxonomy (`passive` / `narrow_active` / `active`).

**Instead, v3.2.1 expanded to a 4-tier taxonomy** (`passive_no_target_contact`, `passive_low_touch`, `active_recon`, `active_exploit`). This is more granular but reintroduces hand-tuned tier weights (5/30/55/85) — the **same calibration problem** that the prior architect review called out for the v3.2.0 binary-and-risk-band-table. The plan replaced "one binary + hand-tuned per-tool risk" with "four-tier + hand-tuned per-tier risk." Numerically smoother, conceptually equivalent.

§2.3 (Tension 3) above shows that `passive_low_touch` and `active_recon` differ on the *approval flag*, not on what the target sees — meaning the *operational* taxonomy is closer to 2-tier (needs-flag vs. doesn't), with `active_exploit` as an admin-gate role check. The 4-tier model is over-fitted to the current tool list.

**Flag:** Principle 4 was rewritten *to match a more elaborate taxonomy* rather than the taxonomy being constrained to match the principle's spirit ("first-class distinction" between active and passive). The Architect's prior recommendation was 3-tier; the plan went to 4 instead. **Severity: LOW** — not a safety regression, but the principle was expanded to accommodate implementation choices.

### Principle 5 — Adding a tool touches one file
**Status: HONORED.** §0.1 wording: "Dropping a Dockerfile under `docker/<tool>/` plus appending one entry to `backend/app/agents/registry.py` is the complete checklist." §2.3 implementation: `ToolEntry` carries `applicable_domain_tags`, palette is derived. §3.2 collapsed to a 2-line function. **One-file-change is now true in code, not just aspirational.** Strong improvement over v3.2.0's 4-touch-point reality.

---

**Summary table:**

| # | Principle | v3.2.0 status | v3.2.1 status | Notes |
|---|---|---|---|---|
| 1 | Safety chain invariant | HONORED | HONORED | unchanged; strongest |
| 2 | AI plans advisory until approved | CONTRADICTED by §5.1 | HONORED (after wording-fit) | resolved via `paused_for_rescope`; principle text softened to "first gate" |
| 3 | Tool wrappers sandboxed by default | VIOLATED (carve-out) | HONORED | shared Docker image restored uniform isolation |
| 4 | Active/passive first-class distinction | VIOLATED (binary mislabeled `httpx`) | WATERED-DOWN | 4-tier taxonomy is a redefinition, not a stricter binary; hand-tuned weights |
| 5 | One file change to add a tool | VIOLATED (4 touch points) | HONORED | in-code registry + tool-side metadata |

**Net: 3 principles cleanly honored, 1 honored-with-textual-softening (P2), 1 watered-down via expansion (P4).** No outright violations remain. The plan is closer to its own principles than v3.2.0 was, with two principles bent to fit the implementation rather than the reverse.

---

## 5. Synthesis — KEEP / DROP / DEFER / MERGE moves for v3.2.1

The plan is close to acceptable. The remaining moves are calibration and edge-case clarifications.

### 5.1 KEEP (don't change)
- §1.1 schema merge (15 additive columns + `workflow_messages` + `rescope_approvals`).
- §1.2 four-class decomposition (`ModelSelector` / `Pricing` / `BudgetGuard` / `ModelClient`).
- §2 shared `osa-passive-recon` Docker image — uniform isolation.
- §3 in-code `DOMAIN_AGENTS` dict and `applicable_domain_tags`.
- §4.3 model self-rating + `min_required_fields_present` sanity guard.
- §5.1 rescope state machine — most thorough section of the plan.
- §0.4 5-scenario pre-mortem (S4 + S5 added).

### 5.2 DROP / TIGHTEN
- **`interview_state` sub-enum (§1.1).** Fold its values into the top-level `status` enum (they already exist there). Two coherent enums on one row is one too many.
- **`workflow_use_deterministic_scorer` feature flag** — not in v3.2.1 (the plan dropped the deterministic scorer entirely rather than feature-flagging it). This is fine in principle but means there is **no fallback** if model self-rating turns out to be miscalibrated in production. See 2.4 above.

### 5.3 DEFER
- **`team_id` column** (§1.1) and team-pool budget aggregation. Useful but adds another moving piece; the principal-budget-per-user already bounds cost. Defer to v3.3.
- **Closed `INTENT_VOCABULARY` enum (§4.3 / Critic minor #12).** Plan added it, but its exact contents are not enumerated. Defer to v3.3 with a starter set + open enum (model can extend with `intent_unknown:freeform` for one release).

### 5.4 MERGE / ADD
- **Add `rescope_approvals.deadline_at`** (denormalized from `requested_at + timeout`) so config-reload mid-flight doesn't move deadlines silently.
- **Specify approver role for `POST /pentest-sessions/{id}/rescope`** and `POST /force-ready-for-review`. §4.1 leaves both ambiguous. Recommendation: `rescope` is any project member; `force-ready-for-review` is admin-only OR rate-limited to 1/user/day.
- **Document `plan_json` vs `draft_plan_json` lifecycle** in §1.1: `plan_json` is a frozen snapshot of `draft_plan_json` set at `approved_at`.
- **Add a held-out ambiguity-rating calibration test** (§2.4 above): CI test that the model's self-rated ambiguity correlates ≥ 0.6 with a small (~20-example) hand-labeled fixture set.
- **Clarify boot-time SHA hard-fail scope** (§2.7 above): fires at image build, not on every container restart in production. Alternatively, degrade-per-file instead of crash-whole-platform.
- **Add a "rescope review queue" UX pattern** for multi-rescope sessions (Tension D above) — batch decisions to avoid operator decision fatigue.

---

## 6. Consensus Addendum

- **Antithesis (steelman):** the prior synthesis moves were adopted cleanly, but adoption created a 25-column god-row, a 4-tier taxonomy whose tiers operationally collapse to a 2-way flag check, a self-rated ambiguity loop with a sycophancy confound, and a force-approve override that lets the operator skip the elicitation gate with a 32-char excuse. The plan is **architecturally cleaner than v3.2.0** but has shifted its failure modes from "missing state machine + carve-outs" (v3.2.0) to "fat row + unverified model judgment + operator-discretionary loop bypass" (v3.2.1).

- **Tradeoff tension (Tension D):** the rescope state machine is safety-correct per discovery event but produces operator decision fatigue at the realistic 5–15 events / session rate. Operators will compensate by pre-approving broader `passive_allowed` / `active_allowed` lists at project setup, defeating the rescope granularity. The plan addresses the safety side and leaves the usability counter-pressure unaddressed; the equilibrium will erode toward broader pre-approval.

- **Synthesis (if viable):** add a "rescope review queue" UX (batch decisions within a 30 s window or N events), enforce admin-only or rate-limited force-approve, add a held-out calibration test for self-rated ambiguity. These three together preserve the prior synthesis wins while closing the new failure surfaces.

- **Principle violations (deliberate mode):**
  - P1 HONORED.
  - P2 HONORED but wording softened to "first gate" — flag this as **wording-fit, not violation.**
  - P3 HONORED (improvement from v3.2.0 carve-out).
  - P4 WATERED-DOWN: principle text expanded to 4-tier with hand-tuned weights; tiers operationally collapse to a flag check. **Severity: LOW.**
  - P5 HONORED (improvement from v3.2.0 4-touch-point reality).
  - No outright violations. P4 is the only flag and is low-severity.

---

## 7. References (v3.2.1 sections)

- §0.1 — revised principles (P3 carve-out removed; P4 4-tier; P2 dual-gate wording).
- §0.4 — pre-mortem S4 (API outage) + S5 (scorer-user disagreement) added.
- §1.1 — pentest_sessions schema additions; `workflow_messages` + `rescope_approvals` tables; removal list.
- §1.2 — `ModelSelector` / `Pricing` / `BudgetGuard` / `ModelClient` decomposition.
- §2.1 / §2.2 — shared `osa-passive-recon` image; on-disk knowledge tree.
- §2.3 — `ToolEntry.applicable_domain_tags`; `palette_for_domain`.
- §2.4 / §5.2 — `TIER_BASE_RISK`, `TIER_REQUIRES_FLAG`, `TIER_REQUIRES_ROLE`.
- §3.1 / §3.2 — in-code `DOMAIN_AGENTS` dict; 2-line palette resolver.
- §4.1 — endpoint list including `/rescope`, `/force-ready-for-review`, `/resume-interview`, `/approval-preview`.
- §4.3 — model self-rating envelope + `min_required_fields_present` sanity guard.
- §5.1 — rescope state machine (the most thoroughly specified section).
- §7 — single migration summary.
- §8 — three ADRs (A3, B4, C2) with full structure.

---

Verdict: SUPPORT-WITH-CHANGES

The plan adopted all five v3.2.0 architect synthesis moves substantively and resolved the BLOCKER (Critic D-1) plus the v3.2.0 Principle 2/3/5 violations. It is architecturally cleaner and the rescope state machine is well-specified. The remaining issues — fat `pentest_sessions` row with two coherent enums, 4-tier taxonomy that operationally collapses to a flag check, self-rated ambiguity without calibration test, force-approve override without admin-gate or rate-limit, multi-rescope operator decision fatigue, boot-time SHA hard-fail scope — are calibration and edge-case clarifications, not blockers. v3.2.1 can ship after addressing items in §5.4 (Merge/Add list), most of which are documentation or single-config-flag changes; principled rework is not required.
