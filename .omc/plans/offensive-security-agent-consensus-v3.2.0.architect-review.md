# Architectural Review — `offensive-security-agent-consensus-v3.2.0`

**Reviewer:** Architect (consensus stage of `/ralplan --consensus --deliberate`)
**Plan under review:** `.omc/plans/offensive-security-agent-consensus-v3.2.0.md` (661 lines)
**Date:** 2026-05-12
**Mode:** deliberate (principle-violation flagging required)

This review is grounded in the actual repo state. Specific files cited from the live tree:
`backend/app/orchestrator/service.py`, `backend/app/orchestrator/planner.py`,
`backend/app/models/session.py`, `backend/app/safety/{whitelist,risk_filter,exploit_allowlist,egress_monitor}.py`,
`backend/app/agents/{registry,base,nmap,nuclei,metasploit,pyrit}.py`,
`backend/alembic/versions/{001_initial,002_rbac}.py`, `frontend/src/pages/*`.

---

## 1. Steelman Antithesis — "This plan is wrong"

A senior architect arguing against this plan would make the following case. It is strong enough that it must be answered, not dismissed.

### 1.1 The plan triples surface area to solve a prompt-engineering problem

The actual problem being addressed in §0 line 12 is: *"AI drafts a Workflow... interviews until ambiguity falls below threshold... user reviews/edits in structured editor."* That is a UX problem on top of `AttackPlanner` (planner.py:37–60, ~24 lines of code today). The plan responds with:

- a new `workflows` table with 14 columns (§1.1)
- a new `workflow_messages` table (§1.1)
- a new `domain_agents` + `domain_agent_tools` + `knowledge_packs` table set (§1.1)
- a new `ModelRouter` (§1.2)
- a new `NativePassiveAdapter` runtime (§2.2) parallel to the existing `AgentAdapter`
- a new `DomainAgentResolver` (§3.2)
- a new `workflow_service` + `ambiguity_scorer` + `workflow_prompts` trio (§4.2)
- 7 new REST endpoints (§4.1)
- 4 new frontend pages/components (§4.4)
- a deterministic 9-component ambiguity scorer (§4.3)
- 5 new Docker images (§2.2)
- a new `osint_allowlist` (§5.3) parallel to `exploit_allowlist`

The total is "~24 new files, ~12 edited files, 1 new Alembic migration, 5 new Docker images, 1 new native-Python runtime, 8 new domain agents, 7 new REST endpoints, 6 new frontend components/pages" (§10) — for one workflow: *"draft a plan, ask clarifying questions, let the user edit, then approve."*

The steelman: **the same outcome can be achieved by:**
1. Adding a `status` enum and `messages JSONB` column to `pentest_sessions` (one column each, no new table — `pentest_sessions` already has `prompt`, `plan_json`, `status`, `started_at`, `ended_at` per `models/session.py:11–34`),
2. Rewriting `AttackPlanner.create_plan` (`planner.py:41–60`) to accept the message history and return either a plan or a clarifying question — that is *one method signature change*,
3. Rendering `plan_json["steps"]` in a structured editor on the frontend (one page),
4. Gating execution on a new `approved_at` field.

Everything else — `domain_agents` table, `DomainAgentResolver`, knowledge-pack tables, ModelRouter — is **prompt engineering masquerading as schema**. The "8 domain agents" are 8 system prompts plus 8 different `available_agents` lists fed to Claude. They do not need their own database tables. They could live as a Python dict in `orchestrator/domain_prompts.py`.

### 1.2 The deterministic ambiguity scorer is false sophistication

§4.3 defines a 9-component weighted sum scorer with hand-tuned weights (0.20, 0.10, 0.20, 0.15, 0.10, 0.10, 0.05, 0.05, 0.05). It thresholds at 0.35 with a turn-over-turn delta requirement of 0.15.

These numbers are **completely made up**. There is no calibration data, no user study, no validation set. §8 ADR-v3.2.0.3 quietly admits this — "Tune `workflow_ambiguity_threshold` after first 50 real sessions." The senior architect says: if you're going to tune it on real data anyway, why ship the elaborate scaffolding now? Just ask the model: "Is this plan specific enough to execute, yes/no, with one sentence of reason?" The model is already capable of self-rating against a checklist embedded in its system prompt. The deterministic scorer:

- has weights that will be tuned post-hoc to fit whatever data shows up (overfitting in production),
- imposes a rigid structure that the model has to *fight against* when the real ambiguity is in a dimension the scorer doesn't measure,
- ties up engineering time that should go to safety hardening,
- has 9 `_is_satisfied` predicates that each need their own tests (§0.5 calls for monotonicity + determinism tests) — i.e., it manufactures its own test burden.

The Pre-Mortem S3 mitigation already includes a **hard turn cap (6)** and a **daily USD budget ($5)**. Those two controls alone solve the cost-explosion failure. The ambiguity scorer is over-engineering on top of already-sufficient guardrails.

### 1.3 The active/passive boundary will leak

§0.1 Principle 4 and §2.4 declare `active_recon` vs `passive_recon` as a first-class distinction. In practice the boundary is porous:

- `httpx` with `-status-code -title -tech-detect` (§5.3) sends real HTTP GETs to live hosts. That is **active probing** by any responsible-disclosure definition, but §3.1 lists `httpx (passive)` in the `osint-agent` palette.
- A DNS query against `dns.google` is "passive" to OSA but is logged by Google with the resolver's IP — engagement leaks.
- `cert_transparency` (`crt.sh` query) reveals to a third party the target the operator cares about *before any consent verification*.
- `subfinder -passive` still issues DNS queries; the `-passive` flag controls *which sources* it uses, not whether it touches the wire.

The plan codifies an oversimplified taxonomy. The risk-band table (`subfinder: 0.3, httpx: 0.45` etc., §2.4) is also hand-tuned. The senior architect's claim: **a binary active/passive flag is the wrong abstraction**. Real-world OSINT classification needs at least: (a) where data goes (target's wire vs. third-party intermediaries vs. archival), (b) attribution risk (does the probe carry the operator's IP), (c) rate envelope. Forcing this into one flag will produce false-safe configurations.

### 1.4 The `Workflow` table is a near-duplicate of `PentestSession`

Compare:

| `pentest_sessions` (live, `models/session.py:11–34`) | `workflows` (proposed, plan §1.1) |
|---|---|
| `id`, `project_id` | `id`, `project_id` |
| `prompt: Text` | `messages` (relationship to `workflow_messages`) |
| `plan_json: JSONB` | `draft_json: JSONB` |
| `status: String(50)` | `status: VARCHAR(32)` |
| `started_at`, `ended_at` | `approved_at`, `approved_by`, `executed_session_id` |
| (no model pin) | `model_id`, `cost_usd_accum`, `ambiguity_score`, `interview_turn_count` |

`workflow.executed_session_id` is a forward pointer to the `PentestSession` *that the workflow becomes*. This is a textbook case of **draft/published split applied to a model that already has a `status` machine.** Today `PentestSession.status` includes `pending` and `running` (per `service.py:93` and the literal usage in `service.py:171`). Adding `draft`, `interviewing`, `ready_for_review`, `approved`, `needs_human_review`, `rejected` to the existing enum and adding `model_id`, `cost_usd_accum`, `ambiguity_score`, `interview_turn_count`, `approved_at`, `approved_by` columns to `pentest_sessions` would have *the same expressive power* with one table instead of two.

The plan's response (§1.1 line: "old single-textarea path keeps working until §3 lands") implies the two tables exist for **migration safety**, not architectural cleanliness. The steelman: do the migration on `pentest_sessions` in one cut; don't carry a vestigial second table forever.

### 1.5 ModelRouter is a billing concern smuggled into the orchestrator

§1.2's `ModelRouter` has three responsibilities: model selection, RBAC gate (`requires_role`), and daily USD budget enforcement (`daily_budget_remaining`). The plan puts this in `backend/app/orchestrator/` (§1.2). But:

- **Model selection** is a planner concern (which model produces the plan).
- **RBAC** is an API-layer concern (handled today in `app/api/deps.py`, which is already modified in the working tree).
- **USD budget** is a billing/quota concern — orthogonal to attack planning. It needs its own ledger that survives orchestrator restarts, cross-references monthly usage, and is reportable to ops.

Bundling these creates a god-class. When billing logic changes (e.g., new pricing tier, monthly cap, team-pooled quota), the orchestrator gets churned. When orchestration changes, the billing accounting risks regression. The senior architect: **`ModelRouter` should be split into `ModelRegistry` (just the metadata dict, in `core/models.py`), `cost_quota` service (in `app/services/quota.py` or similar), and let `AttackPlanner` consume both.**

### 1.6 Discovered-target re-validation is a deadlock hazard

Pre-Mortem S1 mitigation (b) — "every active OSINT step re-validates each *discovered* target against whitelist before probing it, not just the seed" — is correct in spirit but ambiguous in implementation. In the interactive workflow:

- Operator approves a workflow with seed target `acme.com`.
- `subfinder` discovers `internal-acme.com` (not in whitelist).
- Plan §5.1 `validate_discovered_targets` returns it as `rejected`.
- **What happens next?** Plan does not say. Options:
  1. Silently drop and continue — operator's mental model breaks (the assistant said it would enumerate, then didn't).
  2. Halt the step and ask for re-approval — needs a *re-interrupt UX* not described anywhere in §4. Does the workflow go back to `interviewing`? `needs_human_review`? Does the existing `PentestSession` it spawned get paused?
  3. Auto-add to whitelist if the parent domain matches — silently expands scope, defeating the principle.

§5 does not specify the re-approval state-machine transition. The steelman: **this is the single most legally consequential code path in the whole plan, and it's a one-line bullet with no flow diagram.**

### 1.7 Knowledge packs as DB rows is over-modeled

§1.1's `knowledge_packs` table has `id, slug, version, source_url, sha256, loaded_at`. §2.2 says the loader "computes SHA256, refuses YAML/MD with executable hooks, populates `knowledge_packs` table." But:

- The packs live on disk (`backend/knowledge_packs/`) at known paths.
- The SHA-256 verification can be done at boot without persisting.
- The `domain_agents.knowledge_pack_id` is described as "FK-like to filesystem packs" — i.e., the plan itself admits this isn't really a FK.

Why does this need a database table? The architect's answer: **it doesn't.** A `knowledge_packs.yaml` manifest on disk + boot-time hash check + an in-memory dict is equivalent. The DB table adds migration cost, write paths during boot (race-prone if multiple workers come up at once), and a "loaded_at" column that gives false confidence (it tells you when the row was inserted, not whether the content matches what the running planner is seeing).

### 1.8 Verdict of the steelman

The plan correctly identifies the safety surfaces that matter (active/passive, discovered-target re-validation, model cost), but **wraps those genuinely needed controls in a layer of database tables, services, and abstractions that triple the implementation cost without commensurate safety gain.** A plan that lands the safety controls and defers the abstraction layer would be smaller, faster, and easier to audit — which is itself a safety property.

---

## 2. Tradeoff Tensions

Three concrete tensions where the plan over- or under-rotates.

### 2.1 Tension A — Tiered domain agents vs. better prompting (OVER-ROTATED)

**The plan's claim** (§0.3 Option B2, §3.1, ADR-v3.2.0.2): a `DomainAgent` row + `DomainAgentTools` palette + `DomainAgentResolver` gives "tool-add velocity" and "clean separation of planning persona vs. execution adapter."

**The counter-evidence in this repo:**
- `backend/app/agents/registry.py` is already the source of truth for what tools exist.
- `backend/app/orchestrator/planner.py:19` literally hardcodes the available agents into the system prompt: `"Available agents: nmap, nuclei, metasploit, pyrit"`. Replacing that with a per-domain-agent system prompt is **one Python dict and one template substitution**.
- The "palette" is functionally equivalent to filtering `registry.list_tool_entries()` by a tag. No table needed.

**What's actually different between `web-app-agent` and `network-agent` in §3.1?** Two columns: their tool list (which is metadata that belongs on the tool, not the agent) and their `default_risk_band`. Everything else (`display_name`, `description`, `requires_role`, `knowledge_pack_id`, `is_active`) is configuration that could live in a YAML.

**The tension:** the plan optimizes for "tool-add velocity" (a change-management concern) by introducing schema rigidity (a runtime-cost concern). In an early-stage product where the tool palette is still being designed, the inverse trade is correct: keep the palette in code (cheap to refactor), and put the schema in place only after the palette has stabilized across 3+ releases.

**Verdict:** the plan **over-rotates** toward database modeling. Recommendation in §4 of this review.

### 2.2 Tension B — Hybrid OSINT migration boundary (UNDER-ROTATED on leakage)

**The plan's claim** (§2.1, ADR-v3.2.0.1): 3 knowledge packs (markdown) + 7 native validators (passive Python, no Docker) + 5 active OSINT Docker tools. The split is "natural" and the safety chain "covers each layer differently."

**The counter-evidence:**
- The native passive runtime (§2.2 `NativePassiveAdapter`) bypasses the **Docker isolation** that Principle 3 declares. Plan §0.1 Principle 3 says "Bare-metal Python execution is reserved for *passive-only* validators." But the safety chain in `service.py:75–87` (whitelist), `service.py:127–133` (exploit_allowlist + risk_filter), and `service.py:151–159` (PlanExecutor, which is the thing that actually invokes Docker) is designed around the assumption that *execution happens in a container*. The `egress_monitor` (mentioned in §0.1) lives in `backend/app/safety/egress_monitor.py` and watches Docker network namespaces.
- Plan §5.4 says "for adapters with `safety_profile=passive`, allow domain-based egress (not just IP) against `settings.passive_egress_allowlist`." That is a **second egress enforcement code path** that does not share code with the existing IP-based Docker network monitor. Two enforcement paths = two opportunities for divergent behavior.
- §2.5's mitigation: "`NativePassiveAdapter.execute()` enforces `settings.passive_egress_allowlist` via a single `httpx.AsyncClient(transport=AllowlistTransport)`; reject-by-default; per-call audit log; bounded request rate; no shell." This is **a homegrown sandbox**. The OS-level sandboxing (cgroups, network namespaces, no-new-privs, read-only FS) that Docker provides for free is now the developer's responsibility to replicate at the HTTP-client layer. That's a strict downgrade in defense-in-depth.

**The tension:** the plan trades **uniform isolation** (everything in Docker, even cheap things) for **execution efficiency** (skip container startup for 200-LOC scripts). The efficiency gain is real (saves ~500ms/scan), but the safety asymmetry is permanent. Native passive code paths will accumulate over releases, and each one is an exception that has to be re-audited every time `egress_monitor` changes.

**Verdict:** the plan **under-rotates** toward the cost of bifurcating the execution model. Open Q #8 hints the planner sensed this ("Do we want a Docker image for `secret_scan` too?") but resolved it for engineering convenience, not safety posture. The right answer is probably: **all passive validators in a single shared Docker image** (one image, 7 entrypoints, ~30s build) — preserves uniform isolation and is cheap.

### 2.3 Tension C — Workflow approval gate vs. discovered-target re-validation (CONTRADICTORY)

**The plan's claim** (§0.1 Principle 2, §4.1): the `Workflow` is *advisory until approved*. Approval is "a single explicit action" (§0.3 C2).

**The contradiction** (§5.1, §0.4 S1): every active OSINT step re-validates *discovered* targets against the whitelist. This means **execution can encounter scope decisions that were not present at approval time**. So approval is *not* the single decision point — it is the *first* decision point, and re-validation can produce three outcomes (silent-drop / halt-for-re-approval / silent-expand) that the plan does not disambiguate.

**The tension:** Principle 2 says approval is the gate. Pre-Mortem S1 says discovered targets are a new gate. Both cannot be the "single explicit approval" — the workflow either has *one* approval point (and discovered out-of-scope is dropped) or it has *many* (and the UX needs an interrupt-resume model). The plan ships both as principles without resolving the contradiction.

**Verdict:** the plan **contradicts itself** between §0.1 Principle 2 and §5.1. This must be resolved before execution — see §3.1 below.

---

## 3. Principle Violations (deliberate-mode audit)

The plan declares 5 principles in §0.1. Audit:

### 3.1 Principle 2 violation — "AI plans are advisory until user approves"

- **Violator:** §5.1's `validate_discovered_targets` and §0.4 S1 mitigation (b).
- **Severity:** HIGH.
- **Why:** when `subfinder` discovers `internal-acme.com` mid-execution, the orchestrator either (a) silently drops it (degrading the operator's mental model of what's running) or (b) executes it (violating approval gate) or (c) halts for re-approval (state not modeled in §4.1's status transitions). The plan does not specify which.
- **Required fix:** §4.1 must add states `paused_for_rescope` (or equivalent) and the corresponding endpoint (`POST /workflows/{id}/rescope` with discovered targets to accept/reject). The workflow state machine in §4.3 must list these transitions.

### 3.2 Principle 3 violation — "Tool wrappers must be sandboxed by default"

- **Violator:** §2.2's `NativePassiveAdapter` family (7 validators + `secret_scan.py` = 8 native paths).
- **Severity:** MEDIUM (mitigated but not eliminated).
- **Why:** Principle 3 says "Bare-metal Python execution is reserved for *passive-only* validators... and is opt-in via a `safety_profile` flag." That is a carve-out *written into the principle to justify the violation*. It is a self-immunizing principle. The Docker isolation is replaced by an HTTPX `AllowlistTransport` (§2.5), which is fundamentally weaker — no syscall isolation, no FS isolation, no PID isolation, no cgroups. A bug in `secret_scan.py` running native will execute in the FastAPI process; a bug in the same script running in Docker is contained.
- **Required fix:** either (a) move all passive validators into a single shared Docker image (one Dockerfile, multiple entrypoints) — uniform isolation, minor cost, OR (b) tighten the carve-out to *only* HTTP/DNS query operations and explicitly prohibit any FS or subprocess operation in native passive code.

### 3.3 Principle 4 violation — "Active vs. passive is a first-class distinction"

- **Violator:** §3.1's palette table, which lists `httpx (passive)` and `subfinder (passive)` for `osint-agent`.
- **Severity:** LOW-MEDIUM.
- **Why:** `httpx` issuing GET to `https://target.example/` *is* an active probe by any operational definition — the target sees the request. Tagging it "passive" because the flag set is restrictive (§5.3 `ACTIVE_OSINT_ALLOWED_FLAGS["httpx"] = {"-silent", "-status-code", "-title", "-tech-detect"}`) confuses "narrow active" with "passive." This will mislead operators reading the audit log.
- **Required fix:** introduce a three-tier classification: `passive` (no target-side wire activity — DNS, CT logs, archive lookups), `narrow_active` (single-request fingerprinting, restricted method set), `active` (enumeration, fuzzing). The risk band table in §2.4 should be re-derived from this taxonomy.

### 3.4 Principle 5 violation — "Domain agents are composers, not monoliths"

- **Violator:** §1.1's `domain_agents` table + §3.2's `DomainAgentResolver`.
- **Severity:** LOW (architectural smell, not safety).
- **Why:** Principle 5 says "Adding a tool is a registry change, not an agent rewrite." But adding a tool now requires: (1) registry change in `agents/registry.py`, (2) a `domain_agent_tools` row insertion (data migration or admin UI), (3) potentially a knowledge-pack update, (4) sometimes a `DomainAgentResolver.resolve_tool` capability-mapping update. That is **four touch points**, not one. The principle is honored in spirit but lost in implementation.
- **Required fix:** make tool-to-domain mapping live entirely on the tool side (`ToolEntry.applicable_domains: frozenset[str]`) — adding a tool is then exactly one file change.

### 3.5 Principle 1 violation — none found

The plan honors the safety-chain-invariant principle: every new endpoint, every new tool, every new code path is described as passing through `WhitelistValidator → filter_plan_steps → RiskFilter → EgressMonitor`. The principle is concretely supported by §5's safety integration. **This principle is the strongest part of the plan.**

---

## 4. Synthesis — A Better-Balanced Approach

The plan has correct instincts on safety but expensive instincts on schema. Here is a re-scoped version. Keep / Drop / Defer / Merge calls below.

### 4.1 KEEP (high value, low cost)

1. **§0.1 Principle 1 (safety chain invariant)** — keep verbatim.
2. **§0.4 S1 mitigation (a) + (c)** — `passive_allowed` / `active_allowed` split in `whitelist_rules`, plus `wildcard_block_regex` per project. The JSONB schema extension in §1.1 (no migration needed) is the cheapest possible delivery.
3. **§4.1's `POST /workflows/{id}/approve` returns 409 with violations** — the pre-approval whitelist preview UX from S2 mitigation. This is the single highest-value safety UX in the whole plan.
4. **§5.3's `ACTIVE_OSINT_ALLOWED_FLAGS`** — flag-level allowlisting per tool. Cheap, mechanical, audit-friendly.
5. **§0.4 S3's hard interview turn cap + daily USD budget** — keep both. Drop the deterministic scorer (see below).
6. **5 active OSINT Docker images** (`subfinder`, `dnsx`, `httpx`, `cloudenum`, `wappalyzer` per §2.2) — these are real tools that real operators want.

### 4.2 DROP (false sophistication)

1. **Deterministic 9-component ambiguity scorer (§4.3).** Replace with: ask the model directly, in its system prompt, "rate this plan from 0.0 (vague) to 1.0 (specific) and return JSON with the score plus the single most underspecified field." Cap at 6 turns regardless. Tune via system prompt edits, not weight tweaks.
2. **`knowledge_packs` DB table (§1.1).** Replace with on-disk `MANIFEST.yaml` + boot-time SHA verification + in-memory cache. No persisted rows.
3. **`domain_agents` + `domain_agent_tools` DB tables (§1.1).** Replace with `backend/app/orchestrator/domain_agents.yaml` (or a Python module) listing the 8 personas + their tool tags. RBAC stays at the API layer using existing role check (the working tree already has `002_rbac.py`).
4. **Separate `workflows` + `workflow_messages` tables (§1.1).** Merge into `pentest_sessions` (see §4.4 below).
5. **`identity-agent` and `container-k8s-agent` opt-ins (§3.1).** Drop from v3.2.0 scope. They're feature-flagged off anyway; defer to v3.3.

### 4.3 DEFER (correct direction, premature)

1. **`ModelRouter` USD-budget enforcement (§1.2 `daily_budget_remaining`).** The model registry + admin-only opus gate should ship in v3.2.0. USD budget enforcement is a separate concern — defer to v3.2.1 when there's billing telemetry to calibrate it.
2. **Per-domain-agent knowledge packs (§3.1).** Land *one* shared OSINT knowledge pack in v3.2.0. The per-domain split should come after operator usage data shows which domains benefit.
3. **5 Docker images all in one phase.** Ship 2 (`subfinder`, `httpx`) in v3.2.0, the other 3 in v3.2.1 once the registry refactor has lived in production for a release.

### 4.4 MERGE (eliminate duplication)

**`workflows` table → extend `pentest_sessions`**

Add to `pentest_sessions` (the live table in `models/session.py:11–34`):

- `status` enum gains: `draft`, `interviewing`, `ready_for_review`, `approved`, `needs_human_review`, `rejected` (currently has `pending`, `running`, `completed`, `failed` per `service.py`).
- `messages: JSONB` (the message history — same content as `workflow_messages` rows, denormalized).
- `model_id: VARCHAR(64)`, `approved_at: TIMESTAMPTZ NULL`, `approved_by: UUID NULL`, `cost_usd_accum: NUMERIC(8,4)`, `interview_turn_count: INT`, `domain_agent_slug: VARCHAR(64) NULL`.
- The `prompt: Text` column becomes the *initial* user message (already-present, no migration needed; new messages append to `messages` JSONB).

Result: **one table instead of three, no FK chain, no `executed_session_id` forward pointer.** The state machine lives entirely in `status`. The `PentestSession` rows that pre-date v3.2 keep working unchanged (their `status` stays in the old four-value set).

**`domain_agents` table → in-code dict + tool-side metadata**

```python
# backend/app/orchestrator/domain_agents.py
DOMAIN_AGENTS: dict[str, DomainAgent] = {
    "web-app-agent": DomainAgent(
        slug="web-app-agent",
        display_name="Web Application",
        tool_tags=frozenset({"web", "http"}),
        default_risk_band=RiskLevel.MEDIUM,
        requires_role="member",
        system_prompt_template="prompts/web-app.md",
    ),
    # ...
}
```

`ToolEntry` (already proposed in §2.3) gains `applicable_domain_tags: frozenset[str]`. Mapping is computed: `palette = [t for t in registry if t.applicable_domain_tags & agent.tool_tags]`. Zero database round-trips.

### 4.5 Resolve the discovered-target re-validation flow (currently underspecified)

Add to §4.1's state machine:

- New status: `paused_for_rescope`.
- New endpoint: `POST /workflows/{id}/rescope` body `{accept: [hostnames], reject: [hostnames]}`.
- Transition: `executing` → `paused_for_rescope` when `validate_discovered_targets` returns non-empty rejected set; orchestrator emits `event_bus` "rescope_required" with the list; frontend Monitor page surfaces a modal; operator decides; orchestrator resumes.
- Default if operator does not respond within `settings.rescope_decision_timeout_seconds` (default 300): orchestrator drops the rejected targets, audit-logs `rescope_auto_drop`, and continues. (This default favors safety over completeness.)

This **resolves the §3.1 contradiction**.

### 4.6 Three-tier active/passive classification

Replace the binary in §0.1 Principle 4 with:

| tier | wire activity to target | examples |
|---|---|---|
| `passive` | none | DNS resolver, CT logs, archive.org, GitHub API |
| `narrow_active` | single fingerprint request, restricted methods | `httpx -status-code -title`, robots.txt fetch |
| `active` | enumeration, fuzzing, repeated probing | `subfinder -active`, `nuclei`, `nmap -sV` |

Risk band table in §2.4 becomes derivable from tier + tool, not a hand-tuned dict.

### 4.7 Re-scoped phases

- **P0 (3 days → unchanged):** `pentest_sessions` extension (drop the `workflows` table). `ModelRegistry` (no USD budget yet). Settings additions.
- **P1 (7 days → 5 days):** 2 Docker images (`subfinder`, `httpx`) + 1 shared "passive-osint" Docker image hosting all 7 validators + `secret_scan` (uniform isolation, honors Principle 3). Knowledge packs as on-disk manifest. Registry refactor.
- **P2 (4 days → 2 days):** 8 domain agents as in-code dict; new endpoint `GET /api/v1/domain-agents/`. No DB tables.
- **P3 (8 days → 7 days):** Chat + structured editor frontend. Approve endpoint with whitelist preview. Drop deterministic ambiguity scorer; use model self-rating.
- **P4 (3 days → 4 days):** Safety integration including the *resolved* rescope flow.
- **P5 (4 days → unchanged):** Tests, observability, docs.

**Total: ~25 dev-days vs. ~29 in the plan. More importantly: -3 tables, -1 native runtime, -1 deterministic scorer.**

---

## 5. Verdict

**SUPPORT-WITH-CHANGES**

The plan correctly identifies the threat model (active-recon scope blowback, model-cost explosion, approval-gate bypass) and lands strong controls (Principle 1 invariance, S1/S2/S3 pre-mortems, exploit/osint allowlists, RBAC re-check on approval). However, it over-models the supporting infrastructure: three new tables that mostly duplicate `pentest_sessions`, a deterministic ambiguity scorer that admits it will need post-hoc tuning, and a native-Python runtime that weakens Principle 3 by carving an exception into the principle itself. The §3.1 contradiction between "single approval gate" and "discovered-target re-validation" must be resolved before execution begins — that is the only **blocking** issue. The over-modeling is a complexity tax, not a safety regression, and the planner can de-scope it in the next consensus pass without losing the safety win.

Recommend: planner returns to consensus with (a) merged `pentest_sessions` schema (drop `workflows` table), (b) in-code domain agents (drop two tables), (c) shared passive-OSINT Docker image (honor Principle 3 without carve-out), (d) explicit `paused_for_rescope` state + endpoint, (e) model self-rated ambiguity in place of the deterministic scorer. Phases P0–P5 stay; per-phase scope shrinks ~15%.

---

## 6. References

- `/Users/chrisjung/myproject/offensive-security/backend/app/orchestrator/service.py:40-201` — current orchestrator pipeline; shows the 4-layer safety chain the plan must extend.
- `/Users/chrisjung/myproject/offensive-security/backend/app/orchestrator/planner.py:10-60` — current `AttackPlanner`; ~50 lines that the plan refactors into a `ModelRouter` + `workflow_service` + `ambiguity_scorer` triad.
- `/Users/chrisjung/myproject/offensive-security/backend/app/models/session.py:11-34` — `PentestSession` columns; ~80% overlap with the proposed `workflows` table.
- `/Users/chrisjung/myproject/offensive-security/backend/app/safety/whitelist.py` — extension point for §5.1 `validate_discovered_targets`.
- `/Users/chrisjung/myproject/offensive-security/backend/app/safety/risk_filter.py` — extension point for §2.4 `_AGENT_BASE_RISK` updates.
- `/Users/chrisjung/myproject/offensive-security/backend/app/safety/exploit_allowlist.py` — extension point for §5.3 `osint_allowlist` integration.
- `/Users/chrisjung/myproject/offensive-security/backend/app/safety/egress_monitor.py` — Docker-network monitor that the plan's native passive runtime will *not* share code with.
- `/Users/chrisjung/myproject/offensive-security/backend/app/agents/registry.py` — current flat registry; refactor target for §2.3.
- `/Users/chrisjung/myproject/offensive-security/backend/alembic/versions/002_rbac.py` — last migration on disk; the plan's `003_workflows_and_domain_agents.py` is the proposed next.
- `/Users/chrisjung/myproject/offensive-security/frontend/src/pages/ProjectDetail.tsx` — single-textarea launcher that §4.5 rewrites.
- `/Users/chrisjung/myproject/offensive-security/.omc/plans/open-questions.md:8-18` — 9 unresolved decisions; Q1 (model IDs), Q2 (thresholds), Q8 (native vs Docker for `secret_scan`) are the ones most likely to flip the synthesis recommendations above.
