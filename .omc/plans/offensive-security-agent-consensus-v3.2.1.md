# OSA Platform v3.2.1 — Revised Consensus Plan (response to Architect SUPPORT-WITH-CHANGES + Critic ITERATE)

**Status:** APPROVED FOR EXECUTION via `/oh-my-claudecode:ralph` (sequential mode) — 2026-05-14
**Consensus reached:** 2026-05-14 (iteration 2 of 5 max). Architect verdict: SUPPORT-WITH-CHANGES (deferrable residuals). Critic verdict: APPROVE. 12 post-approval tickets captured for v3.2.2 / v3.3 (see Critic review §10).
**Execution path:** Ralph sequential phase-by-phase loop with verifier gate. Pre-P3 open question `INTENT_VOCABULARY` enum content (§9) must be resolved before P3 executor work begins.
**Mode:** `/ralplan --consensus --deliberate`
**Predecessors:**
- v2.1 (implemented baseline): `offensive-security-agent-consensus.md`
- v3.x patches (implemented): `offensive-security-agent-consensus-v3.md` → `v3.1.7.md`
- v3.2.0 (rejected at consensus, iteration 1): `offensive-security-agent-consensus-v3.2.0.md`
- v3.2.0 Architect review: `offensive-security-agent-consensus-v3.2.0.architect-review.md` (verdict: SUPPORT-WITH-CHANGES)
- v3.2.0 Critic review: `offensive-security-agent-consensus-v3.2.0.critic-review.md` (verdict: ITERATE — 1 BLOCKER, 7 MAJOR, 3 MINOR)

**Scope (unchanged from v3.2.0, three intertwined asks):**
1. **Tool catalog expansion** via migration of `elementalsouls/Claude-OSINT` assets (~5,500 lines of tradecraft, ~90 recon modules, regex/dork catalogs, read-only validators).
2. **Domain-based agent catalog** (Web/Network/Cloud[×3]/Mobile/API/OSINT).
3. **New Launch Pentest Session flow**: chat-with-model → AI drafts plan → AI interviews until ambiguity falls below threshold → user reviews/edits in structured editor → approved plan runs through the existing safety chain.

**Authoring intent (unchanged):** plans are *advisory until approved*. The orchestrator's safety chain (`whitelist → exploit_allowlist → risk_filter → egress_monitor → kill_switch`) is **invariant**. No execution path bypasses it.

**Diff vs v3.2.0 (high-level — full diff in §10):**
- Schema collapsed: `workflows`, `workflow_messages` extras, `domain_agents`, `domain_agent_tools`, `knowledge_packs` tables removed. Replaced by additive columns on `pentest_sessions` and an in-code registry.
- `paused_for_rescope` state + `RescopeApproval` audit trail added (resolves Critic D-1 BLOCKER).
- Single shared `osa-passive-recon` Docker image replaces `NativePassiveAdapter` (resolves Critic D-4, honors Principle 3 without carve-out).
- Deterministic 9-component ambiguity scorer replaced by model self-rating + thin sanity guard.
- Binary active/passive replaced by 4-tier risk taxonomy (`passive_no_target_contact`, `passive_low_touch`, `active_recon`, `active_exploit`).
- `ModelRouter` decomposed into `ModelSelector`, `BudgetGuard`, `Pricing`, `ModelClient`.
- 5 pre-mortem scenarios (added S4 API outage, S5 scorer-user disagreement).
- Test plan now lists exact test file paths.
- Open Q #1 resolved: model IDs committed.
- Three ADRs expanded with full Decision/Drivers/Alternatives/Why/Consequences/Follow-ups.

---

## §0. RALPLAN-DR Summary

### 0.1 Principles (5, revised)

1. **Safety chain invariant.** Every workflow step — old or new, OSINT or exploit — passes through `WhitelistValidator → filter_plan_steps → RiskFilter.filter_steps → EgressMonitor` before any container is started. No exceptions, no fast-paths. *(unchanged)*
2. **AI plans are advisory until user approves.** The chat→draft→interview→review flow produces a draft plan attached to a `PentestSession` that is *not executable* until an explicit `approved_at` transition by an authorized user. Approval is the first gate; **discovered-target re-scope is a second, equally explicit gate** handled via the `paused_for_rescope` state (see §5.1). *(clarified to remove the Principle 2 ↔ §5.1 contradiction the Critic flagged)*
3. **Tool wrappers must be sandboxed by default.** All recon/exploit code runs inside an `ExecutionBackend` (Docker) container with `--network osa_pentest_net` and existing memory/CPU/PID caps. The 7 read-only validators and `secret_scan` ship inside a single shared `osa-passive-recon:latest` image. **There is no native execution carve-out.** *(simplified; carve-out removed)*
4. **Risk is a 4-tier taxonomy, not a binary.** Replace the binary `active|passive` flag with `passive_no_target_contact`, `passive_low_touch`, `active_recon`, `active_exploit`. Each tier has a different scope, egress, and approval policy (see §0.5 and §5.2). `httpx` is `passive_low_touch`, not `passive`. *(replaces v3.2.0 Principle 4)*
5. **Adding a tool touches one file.** Dropping a Dockerfile under `docker/<tool>/` plus appending one entry to `backend/app/agents/registry.py` is the complete checklist for shipping a new tool. Domain-agent palettes are derived from `ToolEntry.applicable_domain_tags`, not stored separately. *(reworded after removing tables; honored end-to-end now)*

### 0.2 Decision Drivers (top 3, unchanged)

1. **Legal/scope risk dominates.** Active recon against out-of-scope assets is the single biggest blowup path. Every design choice trades complexity for *more* gating, not less.
2. **AI model cost is bounded by interview-loop length.** A naive "keep asking until perfect" loop is unbounded. We need a hard turn cap (default: 6) and a daily USD budget guard.
3. **Migration ROI of Claude-OSINT.** ~5,500 lines of markdown tradecraft is high-value *knowledge* but low-value *code*. Embed it as on-disk knowledge files (no DB rows); ship only executable code as Docker images.

### 0.3 Viable Options (revised — invalidation rationale strengthened)

#### (a) Claude-OSINT integration shape

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **A1. Port everything to Docker tools** | Uniform execution model; safety-chain coverage is automatic. | ~90 modules × Docker image overhead; most are documentation, not executable. 6–8 week effort for low-leverage migration. | **Reject** — wastes effort on non-executable content. |
| **A2. Embed as Claude system-prompt knowledge packs only** | Zero new images; AI gets richer planning context; cheap. | No reproducible execution; can't audit what was actually run; safety chain has nothing to filter against. | **Reject** — violates Principle 1 (safety-chain coverage). |
| **A3. Hybrid: knowledge files on disk + one shared passive image + selective active Docker wrappers** | Knowledge lives in `backend/app/knowledge/{web,network,cloud_aws,…}/SKILL.md`, loaded at startup and verified by SHA on boot. The 7 read-only validators + `secret_scan.py` ship inside one `osa-passive-recon:latest` image (multi-entrypoint, locked-down egress via `passive_egress_allowlist`). 5 high-value active recon modules (`subfinder`, `dnsx`, `httpx`, `cloudenum`, `wappalyzer`) ship as their own Docker images. | More moving parts than A2; need on-disk manifest + SHA verification at boot. | **Selected.** |

> **Why A1/A2 invalidated:** A1 mis-allocates effort (markdown ≠ code); A2 breaks Principle 1. A3 preserves safety-chain coverage *and* harvests methodology. **Compared to v3.2.0 A3:** this version drops the `NativePassiveAdapter` runtime entirely (Critic D-4) and drops the `knowledge_packs` DB table (Critic D-6 partial; data on disk).

#### (b) Agent catalog shape

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **B1. One mega-agent per domain** | Simple. | God-class; new tools force agent rewrites. | **Reject.** |
| **B2. Tiered: DomainAgent (planner-side) + SpecialistAdapter (tool-side), with DB tables for both** | Clean separation; auditable per row. | Violates Principle 5 (adding a tool touches 4 places); duplicates code metadata as schema rows. | **Reject in v3.2.1** — was the v3.2.0 selection; replaced. |
| **B3. Flat — no domains** | Simplest. | Doesn't satisfy market-segmentation ask. | **Reject.** |
| **B4. Tiered with in-code registry + tool-side metadata** | DomainAgents live as a dict in `backend/app/agents/domains/__init__.py`; tools gain `applicable_domain_tags: frozenset[str]`; palettes are derived (`[t for t in registry if t.applicable_domain_tags & agent.tool_tags]`). Adding a tool is exactly one file change. Zero new DB tables. | Two-layer mental model. Domain set is fixed at deploy time (config change → release). | **Selected.** |

> **Why B2 invalidated:** Architect §4.4 + Critic D-6 confirmed the tables encode code metadata, not data. B4 keeps the conceptual split (persona vs adapter) while honoring Principle 5.

#### (c) Workflow-draft UX

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **C1. Chat-only** | Minimal UI. | No structured editing → can't reorder, bound scope, diff. | **Reject.** |
| **C2. Chat + structured form editor with merged `pentest_sessions` schema** | Chat for ambiguity reduction; on each AI turn, the draft plan updates a structured editor (step list, per-step scope, per-step tool, per-step risk tier). User edits steps directly. Approval is a single explicit action. **Schema lives on `pentest_sessions`** (no separate `workflows` table) — status enum extended; new columns added; messages stored in `workflow_messages` keyed on `pentest_session_id`. | More frontend code; structured-editor state synchronization. | **Selected.** |
| **C3. Form-only Jira wizard** | Highly auditable. | Loses elicitation. | **Reject.** |

> **Why C2 invalidated in v3.2.0 form (separate table):** Architect §1.4 + Critic D-5 showed ~80% column overlap with `pentest_sessions`. The merged schema preserves Principle 2 (advisory until approved) without creating dual-identity rows.

### 0.4 Pre-Mortem (5 scenarios — was 3 in v3.2.0)

> **S1 — Legal/scope blowback from active recon (unchanged threat, strengthened mitigation).**
> Operator runs `web-app-agent` against `acme.com`. AI's knowledge includes subdomain bruteforce. Bruteforce hits `internal-acme.com` (out-of-scope sibling). Engagement contract is breached.
> **Mitigation:** (a) `whitelist_rules` JSONB distinguishes `passive_allowed`, `active_allowed`, `wildcard_block_regex`; (b) every `active_recon` and `active_exploit` step re-validates each *discovered* target against the whitelist; on rejection, the orchestrator transitions the session to `paused_for_rescope` (state machine in §5.1) and emits a Monitor-page modal; (c) `wildcard_block_regex` matched at validate-time before any probe; (d) `active_recon`/`active_exploit` tiers require explicit `approved_active_recon=true` and `approved_active_exploit=true` flags on the session draft.

> **S2 — AI hallucinates out-of-scope steps during interview loop.**
> User says "test my SSO." AI drafts a step targeting `login.microsoftonline.com`. User approves without reading carefully.
> **Mitigation:** (a) **Pre-approval whitelist preview**: before the approve button enables, frontend calls `GET /pentest-sessions/{id}/approval-preview` which runs `WhitelistValidator` server-side and returns red-highlighted out-of-scope hostnames; (b) backend re-validates on `POST /pentest-sessions/{id}/approve` and returns 409 with the violation list (defense in depth); (c) interview-loop system prompt enforces "every target IP/domain must come from the project's `whitelist_rules`, never invented."

> **S3 — Model-cost explosion from interview-loop churn.**
> User replies vaguely; AI keeps asking; budget burns.
> **Mitigation:** (a) Hard cap of **6 interview turns** (configurable per team); (b) **model self-rated ambiguity** (see §4.3) — each turn the model returns `{ambiguity: 0..1, blockers: [...], reasoning: "..."}`; threshold 0.35 transitions to `ready_for_review`; (c) per-user **daily prompt-cost budget** (default $5) enforced by `BudgetGuard` sidecar; (d) `claude-sonnet-4-6` is the default for all roles; `claude-opus-4-6` is admin-only and only for explicitly high-risk plans.

> **S4 — Claude API outage mid-interview (NEW — addresses Critic D-2 (a)).**
> User is mid-conversation; Anthropic API returns 5xx during `append_user_message`. `interview_turn_count` increment is mid-transaction; partial assistant content may be in-flight.
> **Mitigation:** (a) `ModelClient.send()` retries 3× with exponential backoff (200ms / 1s / 5s); (b) on persistent failure, transition session to `interview_paused` with audit `claude_api_unreachable`, preserve `draft_plan_json` and `workflow_messages` so user can resume; (c) `POST /pentest-sessions/{id}/resume-interview` retries the last user message after operator confirmation; (d) admin can fall back to "save draft + resume token" — the session keeps a `resume_token UUID` that survives process restart; (e) on resume, `interview_turn_count` is NOT auto-incremented for the retried turn (idempotent on assistant id).

> **S5 — Scorer/user disagreement (NEW — addresses Critic D-2 (b)).**
> The user thinks the plan is fully specified. The model self-rating returns `ambiguity=0.8` because it disagrees with the user's framing (e.g., user thinks "test the web app" is enough; model wants step-level intent). Loop demands more turns until the cap.
> **Mitigation:** (a) UI shows the *specific blockers the model named* in its self-rating reply, so the user sees *why* the loop continues; (b) **force-approve override** is available to any session creator — `POST /pentest-sessions/{id}/force-ready-for-review` requires `override_reason: str` (min 32 chars), logged as `ambiguity_override` audit action, sets `ambiguity_override_at`/`ambiguity_override_by`/`ambiguity_override_reason` columns. The session still has to pass the safety-chain validation on approve — override only escapes the *elicitation* loop, never the safety chain.

### 0.5 Expanded Test Plan (with named files)

**Unit (≥36 new tests, named)**
- `backend/tests/unit/test_session_state_machine.py` — exhaustive `pentest_sessions.status` transitions including `paused_for_rescope`, `interview_paused`, illegal transitions raise.
- `backend/tests/unit/test_rescope_state_machine.py` — rescope approve / reject / timeout outcomes; orchestrator emits Monitor event; on timeout, default safe-drop fires.
- `backend/tests/unit/test_ambiguity_self_rating.py` — model-self-rating contract: response must include `ambiguity`, `blockers`, `reasoning`; missing field falls back to sanity guard.
- `backend/tests/unit/test_ambiguity_sanity_guard.py` — `min_required_fields_present` check (target, intent per step, risk tier) overrides model rating only when fields are missing.
- `backend/tests/unit/test_risk_tier_assignment.py` — every tool slug maps to exactly one of the four tiers; tier→approval-flag map is exhaustive.
- `backend/tests/unit/test_domain_agent_palette.py` — `web-app-agent` palette excludes `metasploit/exploit/*`; `osint-agent` palette has only `passive_no_target_contact` and `passive_low_touch`.
- `backend/tests/unit/test_knowledge_loader.py` — boot loader rejects executable hooks; computes SHA256 per file; **hard-fails boot on SHA mismatch** with audit `knowledge_pack_sha_mismatch`.
- `backend/tests/unit/test_secret_scan_regex.py` — 48 patterns each have ≥1 positive + ≥1 negative fixture.
- `backend/tests/unit/test_discovered_target_revalidation.py` — newly discovered subdomain outside whitelist → orchestrator emits `rescope_required` event with payload schema match.
- `backend/tests/unit/test_force_approve_override.py` — `override_reason` < 32 chars → 400; ≥ 32 chars → state advances; safety chain still re-runs on subsequent approve.
- `backend/tests/unit/test_model_selector.py` — non-admin selecting `claude-opus-4-6` returns 403; admin allowed.
- `backend/tests/unit/test_budget_guard.py` — daily cap exhausted → 429; pricing computes deterministically; team-pool aggregate enforced (sum across users with `team_id`).
- `backend/tests/unit/test_pricing.py` — input/output USD per 1k matches Anthropic config; new tier changes are localized to `Pricing` module.
- `backend/tests/unit/test_model_client_retries.py` — 3 retries with exponential backoff on 5xx; persistent failure → `interview_paused`.

**Integration (≥14 new tests, named)**
- `backend/tests/integration/test_workflow_chat_flow.py` — `POST /pentest-sessions/{id}/messages` with model selector; mocked Anthropic; verifies `draft_plan_json` updates and `ambiguity` decreases.
- `backend/tests/integration/test_approval_flow.py` — approve fails (409) when any step targets out-of-scope; approve succeeds when all targets match; `approved_at`/`approved_by` set atomically.
- `backend/tests/integration/test_rescope_endpoint.py` — `POST /pentest-sessions/{id}/rescope` with `{accept: [...], reject: [...]}`; orchestrator resumes only with accepted set; rejected discoveries audit-logged.
- `backend/tests/integration/test_passive_recon_image.py` — invoke each entrypoint of `osa-passive-recon:latest`; verify locked-down egress (call to out-of-allowlist domain returns 403-equivalent inside container).
- `backend/tests/integration/test_domain_agent_dispatch.py` — `domain_agent_slug="web-app-agent"` resolves to expected adapter palette via `applicable_domain_tags`.
- `backend/tests/integration/test_rbac_on_approve.py` — admin demoted between draft and approval → approval rejected with 403; session lands `needs_human_review`. TOCTOU window held via `SELECT FOR UPDATE` on `users.role`.
- `backend/tests/integration/test_interview_paused_resume.py` — Anthropic API mocked to 5xx 3× → session in `interview_paused`; resume token round-trips; second attempt succeeds → state returns to `interviewing`.
- `backend/tests/integration/test_team_pool_budget.py` — two users in same `team_id`; combined daily spend exceeds team cap → second user 429.

**E2E (≥5 new Playwright tests, named)**
- `frontend/e2e/test_full_pentest_session.py` — chat → interview → edit → approve → execute → pause-for-rescope → operator accepts subset → continue → report. (single happy-path with rescope branch)
- `frontend/e2e/test_out_of_scope_block.py` — interview produces a step targeting out-of-scope host → approve button stays disabled with inline warning until step is edited or removed.
- `frontend/e2e/test_interview_cap_hit.py` — 6 turns without ambiguity drop → session lands `needs_human_review` with banner.
- `frontend/e2e/test_cost_budget_block.py` — user exceeds $5 cap → 429 on chat send; user-facing toast shows cap and reset time.
- `frontend/e2e/test_force_approve_override.py` — operator submits override reason; ambiguity gate skipped; safety chain still blocks out-of-scope on approve.

**Observability (Prometheus + Grafana)**
- Metrics (new): `osa_session_interview_turns_total{outcome}`, `osa_session_ambiguity_score{bucket}`, `osa_anthropic_tokens_total{model,phase}`, `osa_anthropic_usd_cost_total{model,team_id}`, `osa_domain_agent_dispatch_total{domain,result}`, `osa_rescope_events_total{action}`, `osa_active_recon_targets_total{result}`, `osa_session_time_to_ready_for_review_seconds` (UX-win metric).
- Grafana dashboards (JSON in `docs/observability/`): `workflow-flow.json` (state-machine traversal), `model-costs.json` (per-user/team spend), `safety-chain.json` (rescope events, rejected discoveries, force-approves).
- Audit log actions (new): `session_message_sent`, `draft_plan_updated`, `session_approved`, `session_rejected`, `paused_for_rescope`, `rescope_approved`, `rescope_rejected`, `rescope_auto_drop`, `ambiguity_override`, `claude_api_unreachable`, `knowledge_loaded`, `knowledge_pack_sha_mismatch`.
- Structured log fields on every Anthropic call: `model_id`, `prompt_tokens`, `completion_tokens`, `usd_cost_estimate`, `session_id`, `turn_index`, `team_id`.

### 0.6 Mode and gating

- Mode: **DELIBERATE** (carries over from v3.2.0). Pre-mortem expanded to 5; expanded test plan present with named files; ADR sub-decisions fully written.
- Gate criteria for the next consensus pass: zero BLOCKERs from Critic, zero unaddressed MAJORs, all five Architect §4 moves materialized in §1–§7.

---

## §1. Phase 0 — Foundations (data model, model components, settings)

**Goals.** Land the schema additions and the model-selection primitives. No user-visible change yet.

### 1.1 Data model changes (revised — additive on `pentest_sessions`)

**New migration:** `backend/alembic/versions/003_session_workflow_columns.py`

This migration is **additive** on the existing `pentest_sessions` table (per `backend/app/models/session.py:11-34`). **No new tables for `workflows`, `domain_agents`, `domain_agent_tools`, or `knowledge_packs`.** Only `workflow_messages` and `rescope_approvals` are new tables; both are simple child tables.

#### Columns added to `pentest_sessions`

| column | type | default | purpose |
|---|---|---|---|
| `domain_agent_slug` | `VARCHAR(64) NULL` | `NULL` | which domain-agent persona drafted this plan (e.g., `web-app-agent`) |
| `model_id` | `VARCHAR(64) NOT NULL` | `'claude-sonnet-4-6'` | pinned per-session at creation; see §1.2 |
| `draft_plan_json` | `JSONB NOT NULL` | `'{}'` | live AI-drafted plan; replaces transient drafting in `AttackPlanner` |
| `interview_state` | `VARCHAR(32) NOT NULL` | `'not_started'` | one of `not_started, interviewing, ready_for_review, needs_human_review, interview_paused` (sub-state to `status`) |
| `interview_turn_count` | `INT NOT NULL` | `0` | hard-cap enforced at 6 |
| `ambiguity_score` | `NUMERIC(4,3) NOT NULL` | `1.000` | last model self-rated score |
| `ambiguity_override_at` | `TIMESTAMPTZ NULL` | `NULL` | set when operator force-approves; see S5 |
| `ambiguity_override_by` | `UUID FK -> users.id NULL` | `NULL` | who force-approved |
| `ambiguity_override_reason` | `TEXT NULL` | `NULL` | min 32 chars enforced at API layer |
| `approved_at` | `TIMESTAMPTZ NULL` | `NULL` | gate transition to `approved`/`executing` |
| `approved_by` | `UUID FK -> users.id NULL` | `NULL` | who approved |
| `cost_usd_accum` | `NUMERIC(8,4) NOT NULL` | `0` | accumulator for `BudgetGuard` |
| `paused_for_rescope_at` | `TIMESTAMPTZ NULL` | `NULL` | timestamp of `paused_for_rescope` transition; used by timeout |
| `rescope_request_json` | `JSONB NULL` | `NULL` | current rescope payload: `{discovered_targets: [...], accepted: [...], rejected: [...], requested_by_step_id: ..., requested_at: ...}` |
| `resume_token` | `UUID NULL` | `NULL` | survives process restart; user-facing handle for `interview_paused` recovery |
| `team_id` | `UUID FK -> teams.id NULL` | `NULL` | for team-pool budget aggregation; nullable until teams ship |

#### `status` enum extension on `pentest_sessions`

Current enum (per `service.py`): `pending | running | completed | failed`.
Added: `draft | interviewing | ready_for_review | approved | executing | needs_human_review | rejected | paused_for_rescope`.
CHECK constraint enforces enum membership.

State transitions (authoritative diagram — full text in §5.1):

```
draft → interviewing
interviewing → ready_for_review (when ambiguity ≤ 0.35 OR force-approve)
interviewing → needs_human_review (when turn_count ≥ 6 without ambiguity ≤ 0.35)
interviewing → interview_paused (Anthropic 5xx persistent)
interview_paused → interviewing (resume token used)
ready_for_review → approved → executing
executing → paused_for_rescope (validate_discovered_targets returns non-empty rejected)
paused_for_rescope → executing (rescope approved) | killed (rescope rejected) | executing (auto-drop after timeout)
executing → completed | failed
ready_for_review → rejected (final)
```

#### New table — `workflow_messages` (kept; trimmed)

```
id                   UUID PK
pentest_session_id   UUID FK -> pentest_sessions.id ON DELETE CASCADE
role                 VARCHAR(16) NOT NULL  -- system | user | assistant
content              TEXT NOT NULL
turn_index           INT NOT NULL
ambiguity_after      NUMERIC(4,3) NULL  -- assistant turns only
blockers_json        JSONB NULL         -- assistant turns: list of named unsatisfied predicates
tokens_in            INT NULL
tokens_out           INT NULL
usd_cost             NUMERIC(8,5) NULL
created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
UNIQUE(pentest_session_id, turn_index, role)
```

#### New table — `rescope_approvals` (NEW — resolves Critic D-1)

```
id                       UUID PK
pentest_session_id       UUID FK -> pentest_sessions.id ON DELETE CASCADE
requested_at             TIMESTAMPTZ NOT NULL DEFAULT now()
discovered_targets       JSONB NOT NULL        -- list of hostnames/IPs surfaced by the active step
requesting_step_id       VARCHAR(64) NOT NULL  -- step inside draft_plan_json that triggered rescope
status                   VARCHAR(16) NOT NULL  -- pending | approved | rejected | timed_out
decided_at               TIMESTAMPTZ NULL
decided_by               UUID FK -> users.id NULL
accepted_targets         JSONB NULL            -- subset operator allowed
rejected_targets         JSONB NULL            -- subset operator denied
decision_reason          TEXT NULL
CHECK (status = 'pending' OR decided_at IS NOT NULL)
```

Indexes: `(pentest_session_id, status)` for the resume query.

#### Documentation-only changes to `targets.whitelist_rules` JSONB

(no migration — schema is declarative)

```jsonc
{
  "ip_ranges": [...],
  "domains": [...],
  "passive_allowed":   [...],   // tiers 1 + 2 may touch
  "active_allowed":    [...],   // tier 3 requires this list
  "exploit_allowed":   [...],   // tier 4 requires this list
  "wildcard_block_regex": [...] // hard-blocks discovered hosts that match
}
```

#### What was removed vs v3.2.0

- `workflows` table — collapsed into `pentest_sessions`.
- `domain_agents` table — replaced by `backend/app/agents/domains/__init__.py` dict.
- `domain_agent_tools` table — replaced by `ToolEntry.applicable_domain_tags`.
- `knowledge_packs` table — replaced by on-disk `MANIFEST.yaml` + boot-time SHA verification.
- `workflows.executed_session_id` forward pointer — no longer needed.

### 1.2 Model-selection primitives (decomposed — was `ModelRouter`)

Replaces the single `ModelRouter` god-class (Critic D-8) with four focused units:

**File:** `backend/app/orchestrator/model_selector.py`

```python
class ModelSelector:
    """Resolves model_id from request, enforces RBAC. Stateless."""
    def resolve(self, requested_model_id: str, user: User) -> ModelId:
        """Return validated ModelId; raise HTTPException(403) if user lacks role."""
```

**File:** `backend/app/services/pricing.py`

```python
class Pricing:
    """Per-model input/output USD per 1k tokens. Single source of truth."""
    RATES = {
        "claude-sonnet-4-6": Rate(input_per_1k=Decimal("0.003"), output_per_1k=Decimal("0.015")),
        "claude-opus-4-6":   Rate(input_per_1k=Decimal("0.015"), output_per_1k=Decimal("0.075")),
    }
    def cost(self, model_id: str, tokens_in: int, tokens_out: int) -> Decimal: ...
```

**File:** `backend/app/services/budget_guard.py`

```python
class BudgetGuard:
    """Daily USD cap per user, optional team-pool aggregation. Consulted by orchestrator; not embedded in it."""
    async def check(self, db, user: User) -> BudgetCheckResult:
        """Returns remaining USD; raises 429 if exhausted. Team-pool: sum across users.team_id."""
    async def record(self, db, user: User, usd: Decimal, session_id: UUID) -> None: ...
```

**File:** `backend/app/orchestrator/model_client.py`

```python
class ModelClient:
    """Anthropic SDK wrapper. Retries 3× with exponential backoff. No other concerns."""
    async def send(self, model_id: str, messages: list[Message], system: str) -> Response:
        """Returns Response; on persistent 5xx, raises ModelUnreachable so caller can transition state."""
```

`AttackPlanner` (`backend/app/orchestrator/planner.py`) is refactored to accept a `ModelClient` + `ModelId` instead of constructing `anthropic.Anthropic` itself. `BudgetGuard` is consulted by the workflow service before each `ModelClient.send()`, not embedded in the planner.

### 1.3 Settings additions

**Edit:** `backend/app/core/config.py`

```python
# Anthropic models (Open Q #1 resolved — see §9)
anthropic_default_model: str = "claude-sonnet-4-6"
anthropic_admin_model:   str = "claude-opus-4-6"
anthropic_default_model_anthropic_id: str = "claude-sonnet-4-6-20250514"  # confirmed alias
anthropic_admin_model_anthropic_id:   str = "claude-opus-4-6-20250514"    # confirmed alias

# Interview loop
workflow_max_interview_turns: int = 6
workflow_ambiguity_threshold: float = 0.35
workflow_force_approve_min_reason_chars: int = 32
workflow_opus_requires_admin: bool = True

# Budget
workflow_daily_usd_budget_default: Decimal = Decimal("5.00")
workflow_team_pool_budget_enabled: bool = True

# Rescope
rescope_decision_timeout_seconds: int = 300  # 5 min; on timeout → auto-drop rejected; safety-favoring default

# Model client
anthropic_retry_max_attempts: int = 3
anthropic_retry_backoff_seconds: list[float] = [0.2, 1.0, 5.0]

# Knowledge (on-disk only — no DB)
knowledge_dir: str = "/app/backend/app/knowledge"
knowledge_required_sha256_path: str = "/app/backend/app/knowledge/MANIFEST.yaml"  # boot loader hard-fails on mismatch

# Passive recon shared image
passive_recon_image: str = "osa-passive-recon:latest"
passive_egress_allowlist: list[str] = [
    "crt.sh", "*.haveibeenpwned.com", "api.github.com", "*.shodan.io",
    "viewdns.info", "dns.google", "cloudflare-dns.com",
]

# Active tiers — explicit approval flags
active_recon_requires_explicit_approval:   bool = True
active_exploit_requires_explicit_approval: bool = True
```

### 1.4 Risks and rollback

- **Risk:** schema additions break existing tests. **Mitigation:** every column is nullable or has a default; existing rows keep their `status` from the legacy four-value enum. **Rollback:** `003_session_workflow_columns.py` `downgrade()` drops new columns + `workflow_messages` + `rescope_approvals`.
- **Risk:** `pentest_sessions.status` enum extension collides with code paths that switch on the four old values. **Mitigation:** existing `service.py` switches default to `failed`; new states are unreachable from legacy creation path. Migration adds the CHECK constraint last.

### 1.5 Acceptance criteria (revised — objectively testable)

- `alembic upgrade head` runs cleanly on a v3.1.7 baseline DB and prints `MIGRATION 003 OK`.
- `pytest backend/tests/unit/test_model_selector.py backend/tests/unit/test_budget_guard.py backend/tests/unit/test_pricing.py backend/tests/unit/test_model_client_retries.py` returns exit 0 with ≥ 4 passing files.
- `curl -s http://localhost:8000/api/v1/healthz` returns `{"status":"ok","migrations":"003"}` (new field reports highest applied migration).
- All existing tests (`pytest backend/tests`) still pass — zero regressions.
- `python -c "from app.services.pricing import Pricing; print(Pricing().cost('claude-sonnet-4-6', 1000, 1000))"` prints `0.018`.

---

## §2. Phase 1 — Tool Catalog (revised: knowledge on disk, passive in single shared image)

**Goals.** Land knowledge files on disk, the single shared passive recon Docker image, and 5 new active recon Docker adapters. Refactor the registry to carry tier + domain metadata.

### 2.1 Hybrid integration map (revised)

| Claude-OSINT asset | OSA destination | Type |
|---|---|---|
| `skills/osint-methodology/*.md` | `backend/app/knowledge/methodology/SKILL.md` + `MANIFEST.yaml` | On-disk knowledge file (markdown) |
| `skills/offensive-osint/*.md` (90 modules across 12 domains) | `backend/app/knowledge/{web,network,cloud_aws,cloud_azure,cloud_gcp,mobile,api,osint,…}/SKILL.md` + per-domain `MANIFEST.yaml` | On-disk knowledge file (markdown) |
| `stdlib/secret_scan.py` (48 regex patterns) | Entrypoint `secret_scan` inside `osa-passive-recon:latest` image | Docker tool (`tier=passive_low_touch` — file content scanning of cloned repos, no network) |
| 7 read-only validators (DNS resolver, CT logs, MX/SPF/DMARC, robots/sitemap, .well-known, security.txt, certificate) | Entrypoints `dns_resolver, cert_transparency, mx_spf_dmarc, robots_sitemap, well_known, securitytxt, cert_chain` inside `osa-passive-recon:latest` image | Docker tool (`tier=passive_no_target_contact` or `passive_low_touch`) |
| Subdomain enumeration | New Docker adapter `subfinder` (`projectdiscovery/subfinder`) | Docker tool (`tier=active_recon`) |
| DNS active recon | New Docker adapter `dnsx` (`projectdiscovery/dnsx`) | Docker tool (`tier=active_recon`) |
| Web surface mapping | New Docker adapter `httpx` (`projectdiscovery/httpx`) | Docker tool (`tier=passive_low_touch` — restricted flag set) |
| Cloud bucket enumeration | New Docker adapter `cloudenum` | Docker tool (`tier=active_recon`) |
| Vendor fingerprint / tech stack | New Docker adapter `wappalyzer-cli` | Docker tool (`tier=passive_low_touch`) |
| 90-module dork/regex catalogs | `backend/app/knowledge/dorks/{github,google,shodan}.yaml` | On-disk knowledge file (data) |

> **Why this split (vs v3.2.0):** Everything executable is in Docker — uniform isolation, no `NativePassiveAdapter`. Markdown stays on disk as planning context with SHA verification at boot. **`httpx` is reclassified from `passive` to `passive_low_touch`** (Critic D-7) because it sends real HTTP GETs.

### 2.2 New files (revised)

**Knowledge (on-disk; loaded at startup; SHA-verified):**

- `backend/app/knowledge/MANIFEST.yaml` — top-level manifest mapping domain slug → relative path + SHA256.
- `backend/app/knowledge/methodology/SKILL.md`
- `backend/app/knowledge/web/SKILL.md`
- `backend/app/knowledge/network/SKILL.md`
- `backend/app/knowledge/cloud_aws/SKILL.md`
- `backend/app/knowledge/cloud_azure/SKILL.md`
- `backend/app/knowledge/cloud_gcp/SKILL.md`
- `backend/app/knowledge/mobile/SKILL.md`
- `backend/app/knowledge/api/SKILL.md`
- `backend/app/knowledge/osint/SKILL.md`
- `backend/app/knowledge/dorks/{github,google,shodan}.yaml`
- `backend/app/agents/knowledge_loader.py` — boot-time loader. **Hard-fails boot on SHA mismatch** (Critic risk #5). Refuses YAML/MD with executable hooks. Populates in-memory dict; no DB writes.

**Passive recon Docker image (single shared; Critic D-4):**

- `docker/passive-recon/Dockerfile` — multi-entrypoint Python 3.12 slim base; locks egress via `iptables` rules at container start + `httpx` allowlist transport at app level.
- `docker/passive-recon/entrypoints/secret_scan.py`
- `docker/passive-recon/entrypoints/dns_resolver.py`
- `docker/passive-recon/entrypoints/cert_transparency.py`
- `docker/passive-recon/entrypoints/mx_spf_dmarc.py`
- `docker/passive-recon/entrypoints/robots_sitemap.py`
- `docker/passive-recon/entrypoints/well_known.py`
- `docker/passive-recon/entrypoints/securitytxt.py`
- `docker/passive-recon/entrypoints/cert_chain.py`
- `docker/passive-recon/lib/allowlist_transport.py` — shared `httpx.AsyncClient(transport=AllowlistTransport)`.
- `docker/passive-recon/lib/secret_patterns.yaml` — 48 regex patterns.
- `backend/app/agents/passive_recon.py` — `PassiveReconAdapter` (subclass of existing `AgentAdapter`); runs the shared image with `--entrypoint <name>` and a JSON args payload.

**Active recon Docker images (5 new):**

- `docker/agents/Dockerfile.subfinder`
- `docker/agents/Dockerfile.dnsx`
- `docker/agents/Dockerfile.httpx`
- `docker/agents/Dockerfile.cloudenum`
- `docker/agents/Dockerfile.wappalyzer`
- `backend/app/agents/subfinder.py`
- `backend/app/agents/dnsx.py`
- `backend/app/agents/httpx_tool.py`
- `backend/app/agents/cloudenum.py`
- `backend/app/agents/wappalyzer.py`

**In-code domain registry (Critic D-6):**

- `backend/app/agents/domains/__init__.py` — `DOMAIN_AGENTS: dict[str, DomainAgent]` with 8 personas (see §3.1).

### 2.3 Registry refactor (revised)

**Edit:** `backend/app/agents/registry.py`

```python
@dataclass(frozen=True)
class ToolEntry:
    slug: str
    adapter_cls: type[AgentAdapter]
    docker_image: str                          # always Docker now — no None
    tier: Literal[
        "passive_no_target_contact",
        "passive_low_touch",
        "active_recon",
        "active_exploit",
    ]
    capabilities: tuple[str, ...]
    applicable_domain_tags: frozenset[str]     # used to derive domain-agent palettes
    default_risk_band: RiskLevel               # derived from tier; can be overridden
    is_destructive_capable: bool

_REGISTRY: dict[str, ToolEntry] = {
    # passive_no_target_contact
    "dns_resolver":      ToolEntry(..., tier="passive_no_target_contact", applicable_domain_tags=frozenset({"osint","web","network"})),
    "cert_transparency": ToolEntry(..., tier="passive_no_target_contact", applicable_domain_tags=frozenset({"osint","web"})),
    "mx_spf_dmarc":      ToolEntry(..., tier="passive_no_target_contact", applicable_domain_tags=frozenset({"osint","email"})),
    "cert_chain":        ToolEntry(..., tier="passive_no_target_contact", applicable_domain_tags=frozenset({"osint","web"})),
    # passive_low_touch
    "robots_sitemap":    ToolEntry(..., tier="passive_low_touch", applicable_domain_tags=frozenset({"web","osint"})),
    "well_known":        ToolEntry(..., tier="passive_low_touch", applicable_domain_tags=frozenset({"web","osint"})),
    "securitytxt":       ToolEntry(..., tier="passive_low_touch", applicable_domain_tags=frozenset({"web","osint"})),
    "httpx":             ToolEntry(..., tier="passive_low_touch", applicable_domain_tags=frozenset({"web","api","cloud_aws","cloud_azure","cloud_gcp"})),
    "wappalyzer":        ToolEntry(..., tier="passive_low_touch", applicable_domain_tags=frozenset({"web","api"})),
    "secret_scan":       ToolEntry(..., tier="passive_low_touch", applicable_domain_tags=frozenset({"osint","cloud_aws","cloud_azure","cloud_gcp"})),
    # active_recon
    "subfinder":         ToolEntry(..., tier="active_recon", applicable_domain_tags=frozenset({"web","osint","network"})),
    "dnsx":              ToolEntry(..., tier="active_recon", applicable_domain_tags=frozenset({"network","osint"})),
    "cloudenum":         ToolEntry(..., tier="active_recon", applicable_domain_tags=frozenset({"cloud_aws","cloud_azure","cloud_gcp"})),
    "nmap":              ToolEntry(..., tier="active_recon", applicable_domain_tags=frozenset({"network","web"})),
    "nuclei":            ToolEntry(..., tier="active_recon", applicable_domain_tags=frozenset({"web","api","network"})),
    # active_exploit
    "metasploit":        ToolEntry(..., tier="active_exploit", applicable_domain_tags=frozenset({"network","web"})),
    "pyrit":             ToolEntry(..., tier="active_exploit", applicable_domain_tags=frozenset({"ai"})),
}

def get_adapter(slug: str) -> AgentAdapter: ...
def list_tool_entries() -> list[ToolEntry]: ...
def palette_for_domain(domain_tags: frozenset[str]) -> list[ToolEntry]:
    return [t for t in _REGISTRY.values() if t.applicable_domain_tags & domain_tags]
```

### 2.4 Safety integration for new tools (revised — tier-derived)

- **Tier → approval flag map** (single source of truth in `backend/app/safety/risk_filter.py`):
  - `passive_no_target_contact` → no approval flag; egress restricted to `passive_egress_allowlist`.
  - `passive_low_touch` → no approval flag; targets must be in `passive_allowed` or `active_allowed`.
  - `active_recon` → requires `approved_active_recon=true` on session; targets must be in `active_allowed`.
  - `active_exploit` → requires `approved_active_exploit=true` on session AND admin role; targets must be in `exploit_allowed`.
- **Risk filter** (`backend/app/safety/risk_filter.py`): `_AGENT_BASE_RISK` is **derived** from tier, not hand-tuned:
  ```python
  TIER_RISK = {
      "passive_no_target_contact": 0.05,
      "passive_low_touch":         0.30,
      "active_recon":              0.55,
      "active_exploit":            0.85,
  }
  def base_risk(slug: str) -> float:
      return TIER_RISK[get_tier(slug)]
  ```
- **Exploit/OSINT allowlist** (`backend/app/safety/exploit_allowlist.py` extended): `filter_plan_steps` consults tier → required-flag map; any step whose tier is `active_recon` without `approved_active_recon=true` is dropped with audit `active_flag_missing`.

### 2.5 Risks and rollback

- **Risk:** boot fails if knowledge MANIFEST is missing or hashes mismatch. **Mitigation:** `knowledge_loader` hard-fails with structured error pointing at the failing path. **Rollback:** revert `knowledge_dir` path or restore previous MANIFEST. CI builds run loader as part of image build (`docker run osa-backend python -m app.agents.knowledge_loader --verify`).
- **Risk:** single shared passive image becomes a bottleneck. **Mitigation:** multi-entrypoint pattern means each invocation is short-lived (≤ 30 s). Image rebuild on patterns/validator change is one Dockerfile, ~30 s.
- **Rollback:** disable new tool slugs via feature flag `settings.enable_new_tools` (default true).

### 2.6 Acceptance criteria (revised — objectively testable)

- `docker build -t osa-passive-recon:latest -f docker/passive-recon/Dockerfile .` exits 0; resulting image size ≤ 250 MB.
- `docker run --rm osa-passive-recon:latest --entrypoint dns_resolver --target example.com` returns a JSON document matching the schema `{"resolver":"...","records":{...}}`.
- `docker run --rm --network none osa-passive-recon:latest --entrypoint securitytxt --target example.com` fails with `egress_blocked` (proving the network lockdown).
- `pytest backend/tests/unit/test_secret_scan_regex.py` passes with `>= 96 assertions` (48 patterns × 2).
- `pytest backend/tests/integration/test_passive_recon_image.py` passes.
- `python -m app.agents.knowledge_loader --verify` exits 0 and prints `KNOWLEDGE OK <N> packs, SHA verified`.
- Booting with a tampered MANIFEST returns exit 78 with `knowledge_pack_sha_mismatch`.

---

## §3. Phase 2 — Domain-Agent Catalog (revised: in-code registry, zero DB tables)

**Goals.** Make `web-app-agent`, `network-agent`, `cloud-aws-agent`, `cloud-azure-agent`, `cloud-gcp-agent`, `mobile-agent`, `api-security-agent`, `osint-agent` first-class entities — but as **Python data, not DB rows**.

### 3.1 Domain agent definitions (in-code)

**File:** `backend/app/agents/domains/__init__.py`

```python
@dataclass(frozen=True)
class DomainAgent:
    slug: str
    display_name: str
    description: str
    knowledge_path: str               # e.g. "knowledge/web/SKILL.md"
    tool_tags: frozenset[str]         # used by registry.palette_for_domain
    default_risk_band: RiskLevel
    requires_role: str                # "member" | "admin"
    system_prompt_template: str       # path under backend/app/orchestrator/prompts/

DOMAIN_AGENTS: dict[str, DomainAgent] = {
    "osint-agent":         DomainAgent(slug="osint-agent",       display_name="OSINT / Recon",     knowledge_path="knowledge/osint/SKILL.md",      tool_tags=frozenset({"osint","email"}),          default_risk_band=RiskLevel.LOW,    requires_role="member", system_prompt_template="prompts/osint.md", description="..."),
    "web-app-agent":       DomainAgent(slug="web-app-agent",     display_name="Web Application",   knowledge_path="knowledge/web/SKILL.md",        tool_tags=frozenset({"web"}),                   default_risk_band=RiskLevel.MEDIUM, requires_role="member", system_prompt_template="prompts/web.md", description="..."),
    "network-agent":       DomainAgent(slug="network-agent",     display_name="Network",           knowledge_path="knowledge/network/SKILL.md",    tool_tags=frozenset({"network"}),               default_risk_band=RiskLevel.MEDIUM, requires_role="member", system_prompt_template="prompts/network.md", description="..."),
    "cloud-aws-agent":     DomainAgent(slug="cloud-aws-agent",   display_name="Cloud — AWS",       knowledge_path="knowledge/cloud_aws/SKILL.md",  tool_tags=frozenset({"cloud_aws"}),             default_risk_band=RiskLevel.MEDIUM, requires_role="member", system_prompt_template="prompts/cloud_aws.md", description="..."),
    "cloud-azure-agent":   DomainAgent(slug="cloud-azure-agent", display_name="Cloud — Azure",     knowledge_path="knowledge/cloud_azure/SKILL.md",tool_tags=frozenset({"cloud_azure"}),           default_risk_band=RiskLevel.MEDIUM, requires_role="member", system_prompt_template="prompts/cloud_azure.md", description="..."),
    "cloud-gcp-agent":     DomainAgent(slug="cloud-gcp-agent",   display_name="Cloud — GCP",       knowledge_path="knowledge/cloud_gcp/SKILL.md",  tool_tags=frozenset({"cloud_gcp"}),             default_risk_band=RiskLevel.MEDIUM, requires_role="member", system_prompt_template="prompts/cloud_gcp.md", description="..."),
    "mobile-agent":        DomainAgent(slug="mobile-agent",      display_name="Mobile (static)",   knowledge_path="knowledge/mobile/SKILL.md",     tool_tags=frozenset({"mobile"}),                default_risk_band=RiskLevel.LOW,    requires_role="member", system_prompt_template="prompts/mobile.md", description="static-only MVP"),
    "api-security-agent":  DomainAgent(slug="api-security-agent",display_name="API Security",      knowledge_path="knowledge/api/SKILL.md",        tool_tags=frozenset({"api","web"}),             default_risk_band=RiskLevel.MEDIUM, requires_role="member", system_prompt_template="prompts/api.md", description="..."),
}
```

**Optional agents** (`identity-agent`, `container-k8s-agent`) deferred to v3.3 per Critic recommendation.

### 3.2 Palette resolution (no DB, no resolver service)

```python
# backend/app/orchestrator/domain_resolver.py
def palette_for(slug: str) -> list[ToolEntry]:
    agent = DOMAIN_AGENTS[slug]
    return [t for t in registry.list_tool_entries() if t.applicable_domain_tags & agent.tool_tags]
```

This collapses the previous v3.2.0 `DomainAgentResolver` class to a 2-line function. Tool→domain mapping lives entirely on `ToolEntry.applicable_domain_tags` — adding a tool is one file change (Principle 5 honored).

### 3.3 RBAC enforcement (unchanged location — `app/api/deps.py`)

- `User.role` is matched against `DomainAgent.requires_role` at session-create time and **re-checked at approve time** using `SELECT FOR UPDATE` on `users.role` to close the TOCTOU window (Critic risk #9).
- New endpoints (RBAC-filtered):
  - `GET /api/v1/domain-agents/` → list visible agents (filtered by `current_user.role`)
  - `GET /api/v1/domain-agents/{slug}` → details (palette derived live)

### 3.4 Frontend additions

- `frontend/src/api/client.ts`: `listDomainAgents()`, `getDomainAgent(slug)`.
- `frontend/src/components/DomainAgentPicker.tsx` — used in §4 chat header.

### 3.5 Risks and rollback

- **Risk:** dict edits ship as code changes (release-coupled). **Mitigation:** acceptable for v3.2.x stability — domain set is expected to be stable. Future v3.3 can introduce a YAML overlay if dynamic addition is needed.
- **Rollback:** flip `settings.domain_agents_enabled = False` to fall back to flat planner mode.

### 3.6 Acceptance criteria (revised — objectively testable)

- `curl -H "Authorization: Bearer <admin>" http://localhost:8000/api/v1/domain-agents/` returns a JSON list of exactly 8 entries (no opt-ins in v3.2.x).
- `curl -H "Authorization: Bearer <member>" http://localhost:8000/api/v1/domain-agents/cloud-aws-agent` returns 200 with `{"palette": [...]}` containing only `member`-allowed tools.
- `pytest backend/tests/unit/test_domain_agent_palette.py` passes with `>= 8 assertions` (one per agent).
- `pytest backend/tests/integration/test_domain_agent_dispatch.py` passes.

---

## §4. Phase 3 — Workflow-Draft UX (revised: merged schema, self-rating, force-approve)

**Goals.** Replace the legacy `<textarea> → POST /pentest-sessions/` launcher with the chat→draft→interview→review→approve flow. **All state lives on the existing `pentest_sessions` row** (Critic D-5).

### 4.1 Backend endpoints

**New file:** `backend/app/api/v1/sessions_workflow.py` (alongside existing `sessions.py`)

| Method | Path | Purpose | Status transitions |
|---|---|---|---|
| `POST` | `/api/v1/pentest-sessions/` (extended body) | Create session in `draft`; body: `project_id`, `domain_agent_slug`, `model_id`, optional `title` | → `draft` |
| `GET` | `/api/v1/pentest-sessions/{id}` (extended response) | Includes `draft_plan_json`, `messages`, `ambiguity_score`, `interview_state` | — |
| `POST` | `/api/v1/pentest-sessions/{id}/messages` | Send user message; `ModelClient` responds; update `draft_plan_json` + `ambiguity_score`. | `draft` → `interviewing` → `ready_for_review` (when `ambiguity ≤ 0.35`) or `needs_human_review` (cap hit) or `interview_paused` (API outage) |
| `PATCH` | `/api/v1/pentest-sessions/{id}/draft` | User edits the structured draft (reorder steps, edit scope, toggle tools). | `ready_for_review` (idempotent) |
| `POST` | `/api/v1/pentest-sessions/{id}/force-ready-for-review` | Operator override of ambiguity gate; body `{override_reason: str (≥ 32 chars)}`. | `interviewing` → `ready_for_review` (with `ambiguity_override_*` set) |
| `POST` | `/api/v1/pentest-sessions/{id}/resume-interview` | After `interview_paused`, retry last user turn using `resume_token`. | `interview_paused` → `interviewing` |
| `GET`  | `/api/v1/pentest-sessions/{id}/approval-preview` | Returns whitelist violations against current `draft_plan_json`. Used by frontend red-highlight UX. | — |
| `POST` | `/api/v1/pentest-sessions/{id}/approve` | Approve: run all four safety layers + RBAC re-check (`SELECT FOR UPDATE`). On pass, set `approved_at`, transition to `executing`, kick orchestrator. | `ready_for_review` → `approved` → `executing` |
| `POST` | `/api/v1/pentest-sessions/{id}/reject` | Reject; final state. | → `rejected` |
| `POST` | `/api/v1/pentest-sessions/{id}/rescope` | Operator decision on discovered targets; body `{accept: [hostnames], reject: [hostnames], reason?: str}`. Writes a `rescope_approvals` row. | `paused_for_rescope` → `executing` (if accept non-empty) or `killed` (if all rejected) |

### 4.2 New service modules

- `backend/app/orchestrator/workflow_service.py`
  - `create_session(project, user, domain_agent_slug, model_id) -> PentestSession`
  - `append_user_message(session, content) -> AssistantTurn` — calls `BudgetGuard.check`, then `ModelClient.send`, updates `draft_plan_json` + `ambiguity_score` + `blockers`, persists `workflow_messages`.
  - `update_draft(session, patch) -> PentestSession` — server-side schema validation.
  - `force_ready_for_review(session, user, reason) -> PentestSession` — sets `ambiguity_override_*`.
  - `approve(session, user) -> PentestSession` — final safety validation + RBAC TOCTOU-safe re-check + kick orchestrator.
- `backend/app/orchestrator/ambiguity_self_rating.py` — see §4.3.
- `backend/app/orchestrator/prompts/` — per-domain-agent Jinja templates rendering the agent's knowledge file + project whitelist + tier policy.

### 4.3 Ambiguity scoring (revised — model self-rating + sanity guard)

**Drop the deterministic 9-component scorer.** The drafting model returns, on every assistant turn, a JSON envelope:

```json
{
  "ambiguity": 0.42,
  "blockers": ["per_step_intent_missing", "no_engagement_window"],
  "reasoning": "Two steps lack explicit intent strings; engagement window not specified.",
  "draft_plan_json": { ... }
}
```

Threshold remains **0.35**; turn cap remains **6**. Loop terminates when `ambiguity ≤ 0.35` or `turn_count ≥ 6`. The `delta` heuristic from v3.2.0 is dropped (it depended on the deterministic scorer's stability).

**Thin sanity guard** (does not replace model rating, just gates obvious gaps):

```python
def min_required_fields_present(draft: dict) -> tuple[bool, list[str]]:
    missing = []
    if not draft.get("target"): missing.append("target")
    for i, step in enumerate(draft.get("steps", [])):
        if not step.get("intent"): missing.append(f"steps[{i}].intent")
        if not step.get("tier"):   missing.append(f"steps[{i}].tier")
    return (len(missing) == 0, missing)
```

If `min_required_fields_present` returns `False`, the session cannot transition to `ready_for_review` **regardless of model rating**. This is the only deterministic floor.

**Closed `intent` vocabulary** (Critic minor #12): intents are validated against an enum `INTENT_VOCABULARY` (e.g., `enumerate_subdomains`, `fingerprint_tech_stack`, `scan_open_ports`, ...). Unknown intents → 422 with an "unknown intent" error; the model re-prompts.

### 4.4 Frontend pages and components

- `frontend/src/pages/SessionChat.tsx` — chat UI; sidebar shows live `draft_plan_json` rendered as structured editor; model selector pinned at top; ambiguity progress bar; "Review & Approve" CTA enabled only when `interview_state = ready_for_review` (or force-approved).
- `frontend/src/pages/SessionReview.tsx` — structured editor (drag-to-reorder via `@dnd-kit/sortable`), per-step scope chips, per-step tier badge (with the new 4-tier taxonomy), per-step tool select (constrained by `palette_for(domain_agent_slug)`). Out-of-scope hostnames highlighted red via `GET /pentest-sessions/{id}/approval-preview` (server-side, never reimplemented in TS).
- `frontend/src/components/AmbiguityMeter.tsx` — shows score + named blockers from the model's reply.
- `frontend/src/components/ForceApproveDialog.tsx` — modal requiring `≥ 32 char` reason; submits to `/force-ready-for-review`.
- `frontend/src/components/RescopeModal.tsx` — Monitor page modal when session is `paused_for_rescope`; lists discovered targets with accept/reject checkboxes + reason field.
- `frontend/src/components/ModelSelector.tsx` (sonnet-4-6 / opus-4-6; opus disabled for non-admin).
- `frontend/src/components/StructuredStepEditor.tsx`.
- `frontend/src/api/client.ts`: `createSession`, `getSession`, `listSessions`, `sendSessionMessage`, `updateSessionDraft`, `approveSession`, `rejectSession`, `forceReadyForReview`, `resumeInterview`, `rescopeSession`, `getApprovalPreview`.

### 4.5 Existing pages

- `frontend/src/pages/ProjectDetail.tsx` — rewritten to offer the new guided flow; legacy single-textarea launcher kept behind `settings.legacy_launcher_enabled` (default `False`) — removed in v3.3.

### 4.6 Risks and rollback

- **Risk:** model returns malformed JSON envelope. **Mitigation:** `ambiguity_self_rating.parse` returns a fallback `(ambiguity=1.0, blockers=["model_parse_error"])` and emits audit `model_parse_error`; the session stays in `interviewing` until next turn succeeds. **Rollback:** feature flag `workflow_ui_enabled` (default true).
- **Risk:** force-approve abuse. **Mitigation:** override action is audit-logged with reason text; admin reports can filter on `ambiguity_override` events.

### 4.7 Acceptance criteria (revised — objectively testable)

- `POST /api/v1/pentest-sessions/{id}/messages` with a mocked Anthropic response yields a session whose `draft_plan_json` matches the assistant's `draft_plan_json` field; `interview_turn_count` increments by 1; `ambiguity_score` matches the model's `ambiguity` value.
- `POST /api/v1/pentest-sessions/{id}/approve` against a session with out-of-scope step returns 409 with body schema `{"violations": [{"hostname": "...", "rule": "..."}]}`.
- `POST /api/v1/pentest-sessions/{id}/force-ready-for-review` with `override_reason` length 31 returns 400; length 32 returns 200 and sets `ambiguity_override_at`.
- `frontend/e2e/test_full_pentest_session.py` passes end-to-end.
- `pytest backend/tests/unit/test_ambiguity_self_rating.py` passes with `>= 8 assertions`.

---

## §5. Phase 4 — Safety Integration (revised: rescope state machine, 4-tier taxonomy)

**Goals.** Land the `paused_for_rescope` state machine (resolves Critic D-1 BLOCKER), wire the 4-tier risk taxonomy into existing safety layers, and tighten egress for the shared passive image.

### 5.1 Rescope state machine (NEW — replaces vague v3.2.0 §5.1)

**Trigger.** Every adapter in tier `active_recon` or `active_exploit` calls `validate_discovered_targets(discoveries, whitelist_rules)` after its enumeration phase and before any probe of the discovered hosts. The validator returns `(accepted: list[str], rejected: list[str])`.

**Transitions and behavior.**

```
state: executing
   |
   |  adapter.discovers(["a.acme.com", "internal-acme.com"])
   |  validate_discovered_targets() -> accepted=["a.acme.com"], rejected=["internal-acme.com"]
   v
   if rejected == [] AND accepted == discoveries:
       continue executing  (no transition; adapter probes accepted set)
   elif rejected != []:
       transition: executing -> paused_for_rescope
       set paused_for_rescope_at = now()
       set rescope_request_json = {discovered_targets, accepted, rejected, requesting_step_id, requested_at}
       INSERT INTO rescope_approvals (status='pending', ...)
       emit event_bus message "rescope_required" {session_id, payload}
       frontend Monitor.tsx surfaces RescopeModal
       (adapter task awaits resolution via redis/event)
```

**Operator decision via `POST /pentest-sessions/{id}/rescope`:**

```
case body.accept == [] (operator rejects all):
    transition: paused_for_rescope -> killed
    UPDATE rescope_approvals SET status='rejected', accepted_targets=[], rejected_targets=discovered_targets, decided_at=now(), decided_by=user.id, decision_reason=body.reason
    audit: rescope_rejected
    adapter receives "abort"; session ends with status=killed
case body.accept != []:
    re-run validate_discovered_targets on body.accept to ensure no whitelist drift
    if any of body.accept is NOT in whitelist after re-check: return 409 with violations
    transition: paused_for_rescope -> executing
    UPDATE rescope_approvals SET status='approved', accepted_targets=body.accept, rejected_targets=body.reject, decided_at=now(), decided_by=user.id, decision_reason=body.reason
    audit: rescope_approved
    adapter receives "continue" with accepted set; resumes probing
```

**Timeout policy if user is offline.**

A background job (every 30 s) scans `rescope_approvals WHERE status='pending' AND requested_at < now() - settings.rescope_decision_timeout_seconds`. For each timed-out row:

```
transition: paused_for_rescope -> executing
UPDATE rescope_approvals SET status='timed_out', accepted_targets=[], rejected_targets=discovered_targets, decided_at=now(), decision_reason='auto_drop_after_timeout'
audit: rescope_auto_drop
adapter receives "continue" with EMPTY accepted set
```

**Default favors safety** (drop the rejected hosts; don't probe). The original session continues with the already-accepted (whitelisted-at-seed) set only.

**Concurrent rescope requests.** A session may surface multiple rescope requests across its lifetime (different active-recon steps). Each is its own `rescope_approvals` row. While `status='pending'`, the session stays in `paused_for_rescope`. Only when all pending rows are decided/timed-out does the session leave `paused_for_rescope`.

### 5.2 Risk filter — 4-tier taxonomy

**Edit:** `backend/app/safety/risk_filter.py`

```python
TIER_BASE_RISK = {
    "passive_no_target_contact": 0.05,
    "passive_low_touch":         0.30,
    "active_recon":              0.55,
    "active_exploit":            0.85,
}
TIER_REQUIRES_FLAG = {
    "passive_no_target_contact": None,
    "passive_low_touch":         None,
    "active_recon":              "approved_active_recon",
    "active_exploit":            "approved_active_exploit",
}
TIER_REQUIRES_ROLE = {
    "passive_no_target_contact": "member",
    "passive_low_touch":         "member",
    "active_recon":              "member",
    "active_exploit":            "admin",
}
```

`assess_step` consults `step.tier`; if `TIER_REQUIRES_FLAG[tier]` is set and the session draft lacks the flag, the step is dropped with audit `active_flag_missing`.

### 5.3 Whitelist extensions

**Edit:** `backend/app/safety/whitelist.py`

```python
def validate_target(target: str, tier: str, rules: dict) -> tuple[bool, list[str]]:
    """tier-aware validation; consults passive_allowed / active_allowed / exploit_allowed lists."""

def validate_discovered_targets(
    discoveries: list[str], rules: dict, tier: str
) -> tuple[list[str], list[str]]:
    """returns (accepted, rejected); applies wildcard_block_regex first; called by every active tier adapter."""
```

### 5.4 Egress monitor

**Edit:** `backend/app/safety/egress_monitor.py`

- Existing IP-based monitor on Docker network namespaces is **unchanged** (passive recon runs in Docker, same monitor applies — Critic D-11 obsoleted by D-4 fix).
- `osa-passive-recon:latest` image **additionally** enforces egress at the application layer via the `AllowlistTransport` against `settings.passive_egress_allowlist`. Defense-in-depth: container-level + app-level.

### 5.5 Exploit / OSINT allowlist

**Edit:** `backend/app/safety/exploit_allowlist.py`

- New `tier_dispatch` function: for `active_recon` and `active_exploit` tiers, consult flag-allowlists per tool (e.g., `subfinder` may run with `-passive`, `-silent`, `-all`; `-active` requires admin and `approved_active_recon=true`).
- `ACTIVE_RECON_ALLOWED_FLAGS` constant replaces the v3.2.0 `ACTIVE_OSINT_ALLOWED_FLAGS`.

### 5.6 Audit log additions (revised)

`session_message_sent`, `draft_plan_updated`, `session_approved`, `session_rejected`, `paused_for_rescope`, `rescope_approved`, `rescope_rejected`, `rescope_auto_drop`, `ambiguity_override`, `claude_api_unreachable`, `knowledge_loaded`, `knowledge_pack_sha_mismatch`, `active_flag_missing`, `active_recon_target_validated`, `active_recon_target_rejected`.

### 5.7 Risks and rollback

- **Risk:** rescope-timeout job lags → session stuck. **Mitigation:** job is scheduled every 30 s; metric `osa_rescope_pending_age_seconds` alerts at 90 s. **Rollback:** disable rescope auto-drop via `settings.rescope_auto_drop_enabled = False` (operator must decide manually).

### 5.8 Acceptance criteria (revised — objectively testable)

- `POST /api/v1/pentest-sessions/{id}/approve` against a draft with `tier="active_recon"` step but no `approved_active_recon=true` flag returns 409 with body `{"reason":"active_flag_missing","step_id":"..."}`.
- `POST /api/v1/pentest-sessions/{id}/rescope` with `{accept:["a.acme.com"], reject:["b.acme.com"]}` writes a `rescope_approvals` row with `status='approved'` and transitions session from `paused_for_rescope` to `executing`.
- Triggering rescope and waiting `> rescope_decision_timeout_seconds` results in a `status='timed_out'` row and the session continuing with empty accepted set.
- `pytest backend/tests/unit/test_rescope_state_machine.py backend/tests/integration/test_rescope_endpoint.py backend/tests/unit/test_risk_tier_assignment.py` all pass.

---

## §6. Phase 5 — Tests, Observability, Docs

### 6.1 Tests

(See §0.5 for the full file-by-file list — 36 unit + 14 integration + 5 E2E.) Each Phase has its own subset in its acceptance criteria.

### 6.2 Observability

- Metrics endpoint `/metrics` (existing) gains the new series listed in §0.5.
- Grafana dashboards: `docs/observability/workflow-flow.json`, `docs/observability/model-costs.json`, `docs/observability/safety-chain.json`.
- New alert rules in `docs/observability/alerts.yaml`: `osa_rescope_pending_age_seconds > 90`, `osa_anthropic_usd_cost_total > daily_team_budget * 0.8`.

### 6.3 Docs

- `docs/workflow-flow.md` — sequence diagram + state machine (including `paused_for_rescope`).
- `docs/domain-agents.md` — catalog reference (regenerated from `DOMAIN_AGENTS` dict).
- `docs/knowledge-files.md` — how to add/update; SHA pinning; boot loader behavior.
- `docs/risk-tiers.md` — 4-tier taxonomy with examples per tool.
- `docs/rescope-flow.md` — operator-facing description of paused_for_rescope UX.
- Update `README.md` with v3.2 highlights.

### 6.4 Acceptance criteria

- All tests in §0.5 pass in CI.
- `curl -s http://localhost:8000/metrics | grep -c osa_session_time_to_ready_for_review_seconds` returns `>= 1`.
- `docker compose -f docker-compose.dev.yml up` succeeds and Grafana dashboards render with data after one workflow run.
- `mkdocs build` (or equivalent) exits 0 with no broken links.

---

## §7. Migrations Summary

**Single migration file:** `backend/alembic/versions/003_session_workflow_columns.py`

- **No new tables for** `domain_agents`, `domain_agent_tools`, `knowledge_packs`, `workflows`.
- **Additive columns on** `pentest_sessions` (see §1.1).
- **Two new tables:** `workflow_messages` (chat history, keyed on `pentest_session_id`), `rescope_approvals` (rescope audit trail).
- **Status enum extension** on `pentest_sessions` with CHECK constraint.
- **Indexes:** `(pentest_session_id, turn_index)` on `workflow_messages`, `(pentest_session_id, status)` on `rescope_approvals`.
- **Downgrade:** drops new columns and the two new tables atomically.

This is the single smallest possible migration that supports the new flow while honoring Critic D-5 / D-6 / D-9.

---

## §8. ADR — Architecture Decision Record (expanded per Critic #14)

### ADR-v3.2.1.A3 — Hybrid Claude-OSINT integration (knowledge on disk + single shared passive Docker image + selective active Docker tools)

- **Decision.** Adopt option A3 (revised). Knowledge is on disk; passive validators ship in a single shared `osa-passive-recon` Docker image; 5 active recon tools ship as individual Docker images.
- **Drivers.**
  1. Safety-chain coverage invariant (Principle 1) — all executable code must run inside `ExecutionBackend`.
  2. Uniform isolation (Principle 3 honored without carve-out) — no native execution path.
  3. ROI of Claude-OSINT migration is dominated by methodology content, not code.
  4. Operational simplicity — one Dockerfile for all passive validators, ~30 s build, multi-entrypoint.
- **Alternatives considered.**
  - **A1 (port everything to Docker tools, 90+ images).** Rejected: wastes effort on non-executable markdown; bloats image count without leverage; 6–8 week effort for low value.
  - **A2 (knowledge-only, no executors).** Rejected: violates Principle 1 (no executable surface for safety chain to govern); produces unreproducible "what was actually run" gaps.
  - **A3-v3.2.0 (knowledge packs in DB table + native passive runtime + 5 active Docker images).** Rejected by Critic D-4 and D-6: native runtime weakens Principle 3 by carve-out; DB table for knowledge is over-modeling (the plan itself admitted the FK was "FK-like"); two egress enforcement paths (Docker netns + homegrown HTTPX transport) create divergence risk.
- **Why chosen.**
  A3 (revised) is the only option that delivers (a) safety-chain coverage for every executable path, (b) uniform isolation, (c) high methodology ROI, (d) one-file-change tool addition. The shared passive image preserves the cost savings of a single base layer while retaining Docker's syscall/FS/PID isolation.
- **Consequences.**
  - New on-disk `knowledge/` tree with `MANIFEST.yaml` + boot-time SHA verification; boot hard-fails on mismatch.
  - One new Docker image (`osa-passive-recon:latest`) with multi-entrypoint pattern.
  - Five new active recon Docker images (`subfinder`, `dnsx`, `httpx`, `cloudenum`, `wappalyzer`).
  - `egress_monitor` continues to govern all execution (no new code path to audit).
  - Adding a new validator now requires editing the shared Dockerfile, adding an entrypoint, and a registry row. Adding a new active tool requires a new Dockerfile + a registry row.
- **Follow-ups.**
  - Quarterly resync of knowledge files against upstream `elementalsouls/Claude-OSINT`; SHA recomputation; secret-pattern regression suite.
  - Operator-facing `docs/knowledge-files.md` describing the SHA-pinning model and the hard-fail behavior.
  - v3.3 consideration: dynamic knowledge overlay if customers want to ship private methodology.

### ADR-v3.2.1.B4 — Tiered domain-agent model with in-code registry (DomainAgent dict + tool-side metadata)

- **Decision.** Adopt option B4. `DOMAIN_AGENTS` lives as a Python dict in `backend/app/agents/domains/__init__.py`. `ToolEntry` gains `applicable_domain_tags: frozenset[str]`. Domain palettes are derived in-process.
- **Drivers.**
  1. Principle 5 honored end-to-end — adding a tool is one file change.
  2. Avoid DB tables that encode code metadata.
  3. RBAC stays at the API layer (re-uses existing `app/api/deps.py`).
  4. Tool-to-domain mapping lives on the tool (right side of the join) — additions don't churn the domain catalog.
- **Alternatives considered.**
  - **B1 (mega-agent per domain).** Rejected: god-class growth path; new tools force agent rewrites.
  - **B2 (DB tables for `domain_agents` + `domain_agent_tools`, was the v3.2.0 choice).** Rejected by Critic D-6: adding a tool now requires 4 touch points (registry, table row, knowledge update, capability map). Tables encode code metadata, not data.
  - **B3 (flat, no domains).** Rejected: doesn't satisfy market segmentation; loses persona-level planning context.
- **Why chosen.**
  B4 keeps the conceptual separation (persona vs adapter) without paying the schema tax. Adding a tool is one file edit (`registry.py`); adding a domain is one dict entry. RBAC, knowledge linkage, and palette derivation all flow from in-process data — no migration friction.
- **Consequences.**
  - Domain set is fixed at deploy time (release cadence couples to domain catalog edits) — acceptable for v3.2.x.
  - `DomainAgentResolver` class collapses to a 2-line `palette_for()` function.
  - The earlier `domain_agents` / `domain_agent_tools` tables and seed migrations are not built; one Alembic migration shorter.
- **Follow-ups.**
  - v3.3: introduce YAML overlay if customers need dynamic domains.
  - Track tool addition velocity for one quarter; if hot-add becomes a real need, reconsider schema.

### ADR-v3.2.1.C2 — Chat + structured editor workflow UX on merged `pentest_sessions` schema with model self-rated ambiguity

- **Decision.** Adopt option C2 (revised). Schema is merged onto existing `pentest_sessions` table. Ambiguity is model self-rated each turn with a `min_required_fields_present` sanity guard. Operator can force-approve through ambiguity with audit reason. Discovered-target re-scope has an explicit `paused_for_rescope` state and `POST /rescope` endpoint.
- **Drivers.**
  1. Principle 2 honored — approval is the gate, rescope is its own explicit gate with the same audit weight.
  2. Eliminate `workflows` ↔ `pentest_sessions` duplication (Critic D-5, Architect §1.4).
  3. Avoid uncalibrated deterministic scorer shipping as production default (Critic D-3).
  4. Cost guardrails (turn cap + USD budget) bound failure modes from a misbehaving model.
- **Alternatives considered.**
  - **C1 (chat-only).** Rejected: no structured editing; can't reorder, bound scope, diff.
  - **C2-v3.2.0 (separate `workflows` table + deterministic 9-component scorer).** Rejected: table duplicates `pentest_sessions` ~80%; scorer is hand-tuned with admitted post-hoc calibration; no `paused_for_rescope` state → Principle 2 contradiction.
  - **C3 (form-only Jira wizard).** Rejected: loses elicitation; UX regression.
- **Why chosen.**
  Merged schema collapses three concepts (draft, session, execution) into one row with a richer state enum. Model self-rating uses the same intelligence that drafts the plan, which is cheaper than building a separate scorer and tuning its weights. Force-approve override resolves the scorer-disagreement failure mode (S5). `paused_for_rescope` resolves the BLOCKER from v3.2.0.
- **Consequences.**
  - `pentest_sessions` gains 15 additive columns + a status enum extension. One migration.
  - `workflow_messages` table exists (history) but `workflows` does not.
  - `ambiguity_score` is whatever the model returned last turn; sanity guard prevents trivially under-specified sessions from advancing.
  - Force-approve creates an audit trail with operator-supplied reason ≥ 32 chars.
  - Frontend uses `GET /approval-preview` for whitelist red-highlighting (server is source of truth; no Python→TS reimplementation).
- **Follow-ups.**
  - Tune ambiguity threshold (0.35) after first 50 sessions — single number, not 9 weights.
  - v3.3: consider per-domain-agent custom prompt rubrics if the same threshold doesn't fit all domains.
  - Track `osa_session_time_to_ready_for_review_seconds` as the UX-success metric.

---

## §9. Open Questions (updated per Critic #15)

> Persisted into `.omc/plans/open-questions.md` per Planner protocol; items resolved by this revision are checked off below.

### Resolved in v3.2.1

- [x] **#1 — Exact Anthropic model IDs.** Resolved: `claude-sonnet-4-6` (alias `claude-sonnet-4-6-20250514`) as the default for all roles; `claude-opus-4-6` (alias `claude-opus-4-6-20250514`) admin-only for explicitly high-risk plans. Pricing locked in `Pricing` module (input/output USD per 1k). Pre-deploy smoke test (`backend/tests/smoke/test_anthropic_models.py`) calls each configured model with a 1-token prompt before P0 ships.
- [x] **#8 — Native vs. Docker for `secret_scan`.** Resolved: Docker. `secret_scan` ships as an entrypoint inside `osa-passive-recon:latest`. No native runtime.

### Remaining (owner + due-by-iteration)

- [ ] **#2 — Ambiguity threshold (0.35) and turn cap (6).** Owner: Planner. Due: post-launch tuning after first 50 sessions; track via `osa_session_ambiguity_score` histogram. Not blocking v3.2.1.
- [ ] **#3 — Optional agents (`identity-agent`, `container-k8s-agent`) — defer to v3.3.** Owner: Architect. Due: v3.3 planning. Deferred by Critic recommendation.
- [ ] **#4 — `mobile-agent` MVP scope (static-only).** Owner: Executor. Due: v3.2.1 P2. Confirm static-only is acceptable (no Frida/MobSF in v3.2.x).
- [ ] **#5 — Legacy single-textarea path.** Owner: Planner. Due: v3.2.1 P3. Default OFF (`settings.legacy_launcher_enabled=False`); remove entirely in v3.3.
- [ ] **#6 — Daily USD budget default ($5/user, team-pool aggregate).** Owner: Critic. Due: post-launch with usage telemetry. Not blocking v3.2.1.
- [ ] **#7 — Knowledge vendoring strategy** (vendored snapshot vs git submodule). Owner: Architect. Due: v3.2.1 P1. Plan currently uses vendored snapshot with SHA pinning.
- [ ] **#9 — `wildcard_block_regex` UI location.** Owner: Executor. Due: v3.2.1 P3. Plan keeps it inside `targets.whitelist_rules` JSONB; Admin.tsx will get a JSON editor in v3.3 if usage proves it.

---

## §10. Diff vs v3.2.0 (line-by-line summary)

The table below maps each Critic / Architect finding to the section of v3.2.1 that addresses it.

| Critic ID | Severity | Change in v3.2.1 | Section |
|---|---|---|---|
| D-1 | BLOCKER | Added `paused_for_rescope` status, `rescope_approvals` table, `POST /rescope` endpoint, default safe-drop on timeout (5 min). Full state machine in §5.1. | §1.1, §4.1, §5.1, §5.8 |
| D-2 | MAJOR | Added pre-mortem S4 (Anthropic API outage → `interview_paused` + resume token) and S5 (scorer/user disagreement → force-approve override with audit reason). | §0.4, §4.1, §4.3 |
| D-3 | MAJOR | Dropped 9-component deterministic scorer. Model returns `{ambiguity, blockers, reasoning}` per turn. `min_required_fields_present` is the only deterministic floor. | §4.3 |
| D-4 | MAJOR | Removed `NativePassiveAdapter`. All passive validators + `secret_scan` ship in a single shared `osa-passive-recon` Docker image with locked-down egress. Principle 3 honored without carve-out. | §0.1 (P3), §2.1, §2.2 |
| D-5 | MAJOR | Dropped `workflows` and `workflow_messages` (workflow) tables. All workflow state lives on `pentest_sessions` (additive columns). `workflow_messages` remains as a chat-history child table keyed on `pentest_session_id`. | §1.1, §7 |
| D-6 | MAJOR | Dropped `domain_agents` and `domain_agent_tools` tables. `DOMAIN_AGENTS` is an in-code dict; tools gain `applicable_domain_tags`. | §1.1, §3.1, §3.2 |
| D-7 | MAJOR | Replaced binary active/passive with 4-tier taxonomy: `passive_no_target_contact`, `passive_low_touch`, `active_recon`, `active_exploit`. `httpx` re-labeled to `passive_low_touch`. | §0.1 (P4), §0.5, §2.3, §5.2 |
| D-8 | MAJOR | Decomposed `ModelRouter` into `ModelSelector`, `Pricing`, `BudgetGuard`, `ModelClient`. Budget is a sidecar; orchestrator consults it. | §1.2 |
| D-9 | MINOR | `executed_session_id` forward pointer eliminated (subsumed by D-5 merge). | §1.1 |
| D-10 | MINOR | Open Q #1 resolved: `claude-sonnet-4-6` default, `claude-opus-4-6` admin-only. Pricing locked in `Pricing` module. Pre-deploy smoke test added. | §1.3, §9 |
| D-11 | MINOR | Obsoleted by D-4 — passive runs in Docker, existing `egress_monitor` covers it. No native sandbox tests needed. Test plan replaces those entries with `test_passive_recon_image.py`. | §0.5, §2.6 |
| Architect §4 (1) | — | Merge `workflows` into `pentest_sessions`. | §1.1 |
| Architect §4 (2) | — | Drop `domain_agents`/`domain_agent_tools` tables. | §1.1, §3.1 |
| Architect §4 (3) | — | Single shared Docker image for passive validators. | §2.1, §2.2 |
| Architect §4 (4) | — | `paused_for_rescope` state + endpoint. | §5.1 |
| Architect §4 (5) | — | Model self-rated ambiguity replaces deterministic scorer. | §4.3 |
| Critic #12 (minor) | — | Observability for native runtime obsoleted by D-4; replaced with shared-image tests. | §0.5, §2.6 |
| Critic #13 (minor) | — | Principle 5 reworked: "adding a tool touches one file" — Dockerfile under `docker/<tool>/` + one entry in `agents/registry.py`. | §0.1 (P5), §2.3 |
| Critic #14 (minor) | — | Three ADRs fully expanded per sub-decision (A3, B4, C2). | §8 |
| Critic #15 (minor) | — | Open questions updated: #1 + #8 resolved; remaining items tagged with owner + due-by-iteration. | §9 |
| Critic team-pool risk #7 | — | `team_id` on `pentest_sessions`; `BudgetGuard` aggregates across team; `settings.workflow_team_pool_budget_enabled`. | §1.1, §1.2, §1.3 |
| Critic TOCTOU risk #9 | — | RBAC re-check on approve uses `SELECT FOR UPDATE` on `users.role` in same transaction. | §3.3, §4.1 |
| Critic Ambiguity #5 item 3 | — | `last_two_turns_delta` heuristic dropped along with deterministic scorer; cap-only termination. | §4.3 |
| Critic Ambiguity #5 item 4 | — | `intent` vocabulary is closed enum `INTENT_VOCABULARY`; unknown intent → 422 + model re-prompt. | §4.3 |
| Critic Ambiguity #5 item 5 | — | Whitelist preview is server-side (`GET /approval-preview`); no TS reimplementation. | §4.1, §4.4 |
| Critic missing #5 (SHA mismatch) | — | `knowledge_loader` hard-fails boot on SHA mismatch with audit `knowledge_pack_sha_mismatch`. | §1.3, §2.1, §2.6 |
| Critic missing UX metric | — | Added `osa_session_time_to_ready_for_review_seconds`. | §0.5, §6.2 |
| Critic Q-3 (workflow_id nullable concern) | — | Moot — `workflow_id` column does not exist after the merge. | §1.1 |
| Critic Q-4 (legacy → workflow upgrade path) | — | Legacy path default OFF; no upgrade migration needed. Removed in v3.3. | §4.5 |

### Architect Tension responses (full)

- **Tension A (over-rotated tiered domain agents).** Resolved by B4 (in-code dict, tool-side metadata). Adding a tool is one file change.
- **Tension B (under-rotated isolation cost).** Resolved by D-4 (single shared passive image; no native runtime; uniform Docker isolation).
- **Tension C (single approval gate vs discovered re-validation contradiction).** Resolved by §5.1 (`paused_for_rescope` is an explicit, audited second gate; Principle 2 reworded to acknowledge it as co-equal).

### Phase day-count comparison

| Phase | v3.2.0 days | v3.2.1 days | Delta |
|---|---|---|---|
| P0 Foundations | 3 | 3 | 0 |
| P1 Tools | 7 | 5 | -2 (shared image, no native runtime) |
| P2 Domain agents | 4 | 2 | -2 (in-code dict) |
| P3 Workflow UX | 8 | 7 | -1 (no deterministic scorer code) |
| P4 Safety | 3 | 4 | +1 (rescope state machine) |
| P5 Tests + obs + docs | 4 | 4 | 0 |
| **Total** | **29** | **25** | **-4** |

Net: ~14% reduction in dev-days, -3 tables, -1 native runtime, -1 scorer, +1 state machine.

---

## §11. Plan Summary (for confirmation)

**Plan saved to:** `.omc/plans/offensive-security-agent-consensus-v3.2.1.md`

**Scope.**
- 6 phases (P0–P5)
- 1 new Alembic migration (additive on `pentest_sessions`; 2 new child tables)
- 6 new Docker images (1 shared passive + 5 active recon)
- ~22 new files, ~10 edited files
- 8 domain agents (in-code; no opt-ins in v3.2.x)
- 9 new REST endpoints (including `/rescope`, `/force-ready-for-review`, `/resume-interview`, `/approval-preview`)
- 7 new frontend components/pages (including RescopeModal, ForceApproveDialog)
- ≥ 55 new tests (36 unit + 14 integration + 5 E2E)
- Estimated complexity: **HIGH** (unchanged), dev-days: **~25** (down from ~29)

**Key deliverables.**
1. Additive migration `003_session_workflow_columns.py` extending `pentest_sessions` + adding `workflow_messages` and `rescope_approvals`.
2. Four decomposed model components: `ModelSelector`, `Pricing`, `BudgetGuard`, `ModelClient` with team-pool budget aggregation.
3. Single shared `osa-passive-recon` Docker image (8 entrypoints) + 5 active recon Docker images.
4. 8 in-code `DOMAIN_AGENTS` with palettes derived via `applicable_domain_tags`.
5. Chat-driven UX with model self-rated ambiguity, force-approve override, structured editor, server-side approval preview.
6. `paused_for_rescope` state machine with 5-minute safe-drop default and operator decision endpoint.
7. Tier-derived risk filter (4 tiers) + tier-gated approval flags.
8. On-disk knowledge with boot-time SHA verification (hard-fail on mismatch).
9. UX-success metric `osa_session_time_to_ready_for_review_seconds`.

**Does this plan capture the response to Architect / Critic feedback?**
- `proceed to consensus` — submit v3.2.1 for next Architect + Critic review pass.
- `adjust [X]` — modify the named section before submission.
- `restart` — discard and re-interview.
