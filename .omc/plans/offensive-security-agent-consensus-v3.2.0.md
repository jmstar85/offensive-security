# OSA Platform v3.2.0 — Tool Catalog Expansion, Domain Agents, Workflow-Draft UX

**Status:** pending approval (Planner draft)
**Mode:** `/ralplan --consensus --deliberate`
**Predecessors (locked baselines):**
- v2.1 (implemented): `offensive-security-agent-consensus.md`
- v3.x patches: `offensive-security-agent-consensus-v3.md` → `v3.1.7.md`

**Scope (this iteration, three intertwined asks):**
1. **Tool catalog expansion** via migration of `elementalsouls/Claude-OSINT` assets (~5,500 lines of tradecraft, ~90 recon modules, regex/dork catalogs, read-only validators).
2. **Domain-based agent catalog** (Web/Network/Cloud[×3]/Mobile/API/OSINT[+optional Identity, Container/K8s]).
3. **New Launch Pentest Session flow**: chat-with-model → AI drafts Workflow → AI interviews until ambiguity falls below threshold → user reviews/edits in structured editor → approved workflow runs through existing safety chain.

**Authoring intent:** this plan is *advisory until approved*. The orchestrator's safety chain (`whitelist → exploit_allowlist → risk_filter → egress_monitor → kill_switch`) is **invariant**. No execution path bypasses it.

---

## §0. RALPLAN-DR Summary

### 0.1 Principles (5)

1. **Safety chain invariant.** Every workflow step — old or new, OSINT or exploit — passes through `WhitelistValidator → filter_plan_steps → RiskFilter.filter_steps → EgressMonitor` before any Docker container is started. No exceptions, no fast-paths.
2. **AI plans are advisory until user approves.** The new chat→draft→interview→review flow produces a `Workflow` artifact that is *not executable* until an explicit `approved_at` transition by an authorized user. The current "background-task on session create" autorun is replaced.
3. **Tool wrappers must be sandboxed by default.** New OSINT scripts run inside the same `ExecutionBackend` (Docker) abstraction as nmap/nuclei, with `--network osa_pentest_net` and existing memory/CPU/PID caps. Bare-metal Python execution is reserved for *passive-only* validators (read-only HTTP HEAD/GET, DNS, certificate transparency) and is opt-in via a `safety_profile` flag.
4. **Active vs. passive is a first-class distinction.** OSINT splits into `passive` (DNS, CT logs, public APIs, archived data) and `active` (live HTTP probes, port-touching, brute-prone enumeration). Risk filter must distinguish; whitelist rules must support a `passive_allowed` toggle separate from `active_allowed`.
5. **Domain agents are composers, not monoliths.** A domain agent (e.g., `web-app-agent`) does not embed scanner logic — it selects from a curated tool palette via capability metadata. Adding a tool is a registry change, not an agent rewrite.

### 0.2 Decision Drivers (top 3)

1. **Legal/scope risk dominates.** Active recon (subdomain bruteforce, port-touching, SSO enumeration) against out-of-scope assets is the single biggest blowup path. Every design choice trades complexity for *more* gating, not less.
2. **AI model cost is bounded by interview-loop length.** A naive "keep asking until perfect" loop on `claude-opus-4-6` can spend $5–$15 per session in API calls alone. We need a deterministic ambiguity scorer with a hard cap (default: 6 turns), not vibes-based termination.
3. **Migration ROI of Claude-OSINT.** ~5,500 lines of markdown tradecraft is high-value *knowledge* but low-value *code*. Porting it to Docker images is mostly waste; embedding it as system-prompt context packs + a small validator subset is high-leverage.

### 0.3 Viable Options

#### (a) Claude-OSINT integration shape

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **A1. Port everything to Docker tools** | Uniform execution model; safety chain coverage is automatic. | ~90 modules × Docker image overhead; most are documentation/tradecraft, not executable code; 6–8 week effort. | **Reject** — bloats image count, low leverage on markdown content. |
| **A2. Embed as Claude system-prompt knowledge packs only** | Zero new images; AI gets richer planning context; cheap. | No reproducible execution; can't audit what was actually run; safety chain has nothing to filter against. | **Reject** — violates Principle 1 (safety chain coverage). |
| **A3. Hybrid: knowledge packs + validator subset + selective Docker wrappers** | High leverage. Markdown lives in `agents/knowledge_packs/`. The 9 read-only validators + `secret_scan.py` (regex catalog of 48 patterns) ship as native Python with `safety_profile=passive`. ~6 high-value active modules (subdomain enum, web surface, DNS recon, CT log mining, cloud bucket enum, vendor fingerprint) get full Docker adapters. | More moving parts; need new `KnowledgePack` concept; passive-Python execution path is a new code path that needs its own audit. | **Selected.** |

> **Why A1/A2 invalidated:** A1 wastes effort on non-executable content; A2 breaks the safety-chain coverage invariant.

#### (b) Agent catalog shape

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **B1. One mega-agent per domain** (e.g., single `web-app-agent` that internally branches across nuclei/nikto/zap/sqlmap/etc.) | Simple registry; fewer rows. | Agent code becomes a god-class; new tools force agent rewrites; bad fit for capability metadata. | **Reject.** |
| **B2. Tiered: DomainAgent (planner-side) → SpecialistAdapter (tool-side)** | DomainAgent is a planning persona with a curated tool palette + knowledge pack; SpecialistAdapter is the existing `AgentAdapter` (nmap, nuclei, …) unchanged. Clean separation: domain-agent decides *what*; specialist executes *how*. Tools added without touching DomainAgents. | Two-layer mental model; needs new `domain_agents` table and `agent_palette` mapping. | **Selected.** |
| **B3. Flat — drop domains entirely** | Simplest. | Doesn't satisfy market-segmentation ask; user explicitly requested domain reorg. | **Reject.** |

#### (c) Workflow-draft UX

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **C1. Chat-only (transcript becomes the plan)** | Minimal UI work. | No structured editing → user can't reorder steps, can't bound scope per step, hard to diff. | **Reject.** |
| **C2. Chat + structured form editor** | Chat for ambiguity reduction; on each AI turn, the draft Workflow JSON updates a structured editor (step list, per-step scope, per-step tool, per-step risk band). User edits steps directly. Approval is a single explicit action. | More frontend code; requires draft persistence & optimistic updates. | **Selected.** |
| **C3. Form-only (Jira-style wizard)** | Highly auditable. | Loses the AI's ability to elicit nuance; UX regression vs. current freeform. | **Reject.** |

### 0.4 Pre-Mortem (3 realistic failure scenarios)

> **S1 — Legal/scope blowback from active OSINT.**
> An operator runs the new "web-app-agent" against `acme.com`. AI's knowledge pack includes subdomain bruteforce. Bruteforce hits `internal-acme.com` (out-of-scope sibling domain owned by Acme but not in whitelist). Engagement contract is breached.
> **Mitigation:** (a) Whitelist now distinguishes `passive_allowed` (broad) from `active_allowed` (narrow); (b) every active OSINT step re-validates each *discovered* target against whitelist before probing it, not just the seed; (c) new `wildcard_block_regex` per project blocks sibling-domain patterns; (d) risk_filter assigns `active_osint` a default `MEDIUM` band requiring explicit `approved_active_recon=true` on the Workflow.

> **S2 — AI hallucinates out-of-scope steps during interview loop.**
> User says "test my SSO." AI drafts a step targeting `login.microsoftonline.com` (out of every customer's whitelist). User approves without reading carefully.
> **Mitigation:** (a) **Pre-approval whitelist preview**: before the approve button enables, frontend runs `WhitelistValidator` client-side and shows red highlights on out-of-scope hostnames; (b) backend re-validates on `POST /workflows/{id}/approve` and returns 409 with violations; (c) interview loop's system prompt enforces "every target IP/domain must come from the project's `whitelist_rules`, never invented."

> **S3 — Model-cost explosion from interview-loop churn.**
> User keeps replying vaguely; AI keeps asking; opus-4-6 burns through $20 of API budget per session.
> **Mitigation:** (a) Hard cap of **6 interview turns** (configurable per team); (b) **ambiguity score** is computed deterministically (see §3.4) — if it doesn't drop by ≥0.15 between consecutive turns, the loop exits with `status=needs_human_review`; (c) per-user **daily prompt-cost budget** (default $5) enforced by `OrchestratorService._check_rate_limit` extension; (d) model selector defaults to `sonnet-4-6`; `opus-4-6` requires admin role.

### 0.5 Expanded Test Plan

- **Unit (≥30 new tests)**
  - `tests/unit/test_workflow_state_machine.py` — draft → interviewing → ready_for_review → approved → executing → completed/failed transitions; illegal transitions raise.
  - `tests/unit/test_ambiguity_scorer.py` — deterministic scorer returns same value for same inputs; monotone decreases as fields fill.
  - `tests/unit/test_domain_agent_palette.py` — `web-app-agent` palette excludes `metasploit/exploit/*`; `osint-agent` palette is passive-only by default.
  - `tests/unit/test_knowledge_pack_loader.py` — loader rejects YAML with executable hooks; markdown only.
  - `tests/unit/test_safety_profile_passive.py` — `safety_profile=passive` validator can hit allowlisted CT logs; cannot hit arbitrary HTTP.
  - `tests/unit/test_secret_scan_regex.py` — 48 patterns each have at least one positive + one negative test fixture.
  - `tests/unit/test_active_recon_target_revalidation.py` — newly *discovered* subdomain that falls outside whitelist is dropped before probe.
- **Integration (≥12 new tests)**
  - `tests/integration/test_workflow_chat_endpoint.py` — `POST /workflows/{id}/messages` with model selector; mocked Anthropic response; verifies draft JSON updates.
  - `tests/integration/test_workflow_approval_flow.py` — approve fails when any step targets out-of-scope domain.
  - `tests/integration/test_domain_agent_dispatch.py` — `domain_agent="web-app-agent"` resolves to expected adapter chain.
  - `tests/integration/test_passive_validator_egress.py` — passive HTTP validator's egress is logged + bounded.
- **E2E (≥4 new tests, Playwright)**
  - `e2e/launch_pentest_session_flow.spec.ts` — user starts chat → picks `sonnet-4-6` → answers 3 questions → ambiguity falls under threshold → review screen shows 5 steps → user reorders 2 steps → approves → execution starts and Monitor page shows progress.
  - `e2e/out_of_scope_block.spec.ts` — interview produces a step targeting out-of-scope host → approve button stays disabled with inline warning.
  - `e2e/interview_cap_hit.spec.ts` — 6 interview turns without ambiguity drop → workflow lands in `needs_human_review`.
  - `e2e/cost_budget_block.spec.ts` — user with $5 daily cap exceeded sees 429 on chat send.
- **Observability**
  - New Prometheus metrics: `osa_workflow_interview_turns_total{outcome}`, `osa_workflow_ambiguity_score`, `osa_anthropic_tokens_total{model,phase}`, `osa_domain_agent_dispatch_total{domain,result}`, `osa_active_osint_targets_total{result}`.
  - New audit log actions: `workflow_created`, `workflow_message_sent`, `workflow_draft_updated`, `workflow_approved`, `workflow_rejected`, `active_osint_target_validated`, `knowledge_pack_loaded`.
  - Structured log fields on every Anthropic call: `model_id`, `prompt_tokens`, `completion_tokens`, `usd_cost_estimate`, `workflow_id`, `turn_index`.

---

## §1. Phase 0 — Foundations (data model, model router, settings)

**Goals.** Land the schema, settings, and model-routing primitives that every later phase depends on. No user-visible change yet.

### 1.1 Data model changes

**New migration:** `backend/alembic/versions/003_workflows_and_domain_agents.py`

Tables:

- `workflows`
  - `id UUID PK`
  - `project_id UUID FK -> projects.id NOT NULL`
  - `created_by UUID FK -> users.id NOT NULL`
  - `title VARCHAR(255) NOT NULL`
  - `status VARCHAR(32) NOT NULL` — one of `draft | interviewing | ready_for_review | approved | executing | completed | failed | rejected | needs_human_review` (CHECK constraint)
  - `model_id VARCHAR(64) NOT NULL` — pinned per-workflow at creation
  - `ambiguity_score NUMERIC(4,3) NOT NULL DEFAULT 1.000`
  - `interview_turn_count INT NOT NULL DEFAULT 0`
  - `draft_json JSONB NOT NULL DEFAULT '{}'` — current Workflow draft (steps, scope, etc.)
  - `approved_at TIMESTAMPTZ NULL`
  - `approved_by UUID FK -> users.id NULL`
  - `executed_session_id UUID FK -> pentest_sessions.id NULL` — populated on approve→execute
  - `cost_usd_accum NUMERIC(8,4) NOT NULL DEFAULT 0`
  - timestamps mixin
  - CHECK: `approved_at IS NULL OR approved_by IS NOT NULL`
- `workflow_messages`
  - `id UUID PK`
  - `workflow_id UUID FK -> workflows.id ON DELETE CASCADE`
  - `role VARCHAR(16) NOT NULL` — `system | user | assistant`
  - `content TEXT NOT NULL`
  - `turn_index INT NOT NULL`
  - `ambiguity_score_after NUMERIC(4,3) NULL` — assistant turns only
  - `tokens_in INT NULL`, `tokens_out INT NULL`, `usd_cost NUMERIC(8,5) NULL`
  - timestamps mixin
  - UNIQUE `(workflow_id, turn_index, role)`
- `domain_agents`
  - `id UUID PK`
  - `slug VARCHAR(64) UNIQUE NOT NULL` — e.g. `web-app-agent`, `osint-agent`, `cloud-aws-agent`
  - `display_name VARCHAR(128) NOT NULL`
  - `description TEXT NOT NULL`
  - `knowledge_pack_id VARCHAR(128) NULL` — FK-like to filesystem packs (validated at boot)
  - `default_risk_band VARCHAR(16) NOT NULL` — `low | medium | high`
  - `requires_role VARCHAR(32) NOT NULL DEFAULT 'member'`
  - `is_active BOOLEAN NOT NULL DEFAULT TRUE`
- `domain_agent_tools`
  - `domain_agent_id UUID FK -> domain_agents.id ON DELETE CASCADE`
  - `tool_slug VARCHAR(64) NOT NULL` — references `agent_registry` slug (nmap, nuclei, subfinder, …)
  - `default_safety_profile VARCHAR(16) NOT NULL DEFAULT 'sandboxed'` — `sandboxed | passive`
  - `enabled_by_default BOOLEAN NOT NULL DEFAULT TRUE`
  - PK `(domain_agent_id, tool_slug)`
- `knowledge_packs` (lightweight; mostly cached from filesystem)
  - `id UUID PK`
  - `slug VARCHAR(128) UNIQUE NOT NULL`
  - `version VARCHAR(32) NOT NULL`
  - `source_url TEXT NULL`
  - `sha256 CHAR(64) NOT NULL`
  - `loaded_at TIMESTAMPTZ NOT NULL`

Alterations:
- `pentest_sessions`: add nullable `workflow_id UUID FK -> workflows.id`. Old single-textarea path keeps working until §3 lands; new path *requires* a workflow.
- `targets.whitelist_rules` JSONB schema extended (no migration, just doc):
  - `{ ip_ranges: [...], domains: [...], passive_allowed: [...], wildcard_block_regex: [...], active_allowed: [...] }`

### 1.2 Model router

**New file:** `backend/app/orchestrator/model_router.py`

```python
class ModelRouter:
    """Resolve model_id from request + RBAC, enforce cost budget, return Anthropic client wrapper."""
    SUPPORTED_MODELS = {
        "claude-sonnet-4-6": {
            "anthropic_id": "claude-sonnet-4-6-20250514",  # placeholder, see Open Q #1
            "input_usd_per_1k": 0.003,
            "output_usd_per_1k": 0.015,
            "requires_role": "member",
        },
        "claude-opus-4-6": {
            "anthropic_id": "claude-opus-4-6-20250514",  # placeholder, see Open Q #1
            "input_usd_per_1k": 0.015,
            "output_usd_per_1k": 0.075,
            "requires_role": "admin",
        },
    }
    def resolve(self, model_id: str, user: User) -> ModelHandle: ...
    def estimate_cost(self, tokens_in: int, tokens_out: int, model_id: str) -> Decimal: ...
    async def daily_budget_remaining(self, db, user_id) -> Decimal: ...
```

`AttackPlanner` (`backend/app/orchestrator/planner.py`) is refactored to accept a `ModelHandle` instead of constructing `anthropic.Anthropic` itself.

### 1.3 Settings additions

**Edit:** `backend/app/core/config.py`

```python
# Workflow + chat
workflow_max_interview_turns: int = 6
workflow_ambiguity_threshold: float = 0.35    # below this → ready_for_review
workflow_min_ambiguity_delta: float = 0.15    # if turn-over-turn drop < this → needs_human_review
workflow_default_model_id: str = "claude-sonnet-4-6"
workflow_daily_usd_budget_default: Decimal = Decimal("5.00")
workflow_opus_requires_admin: bool = True

# Knowledge packs
knowledge_packs_dir: str = "/app/knowledge_packs"   # mounted volume

# OSINT safety
passive_egress_allowlist: list[str] = [
    "crt.sh", "*.haveibeenpwned.com", "api.github.com", "*.shodan.io",
    "viewdns.info", "dns.google", "cloudflare-dns.com",
]
active_osint_requires_explicit_approval: bool = True
```

### 1.4 Risks and rollback

- **Risk:** schema sprawl breaks existing tests.
  **Mitigation:** migration is additive (no column drops); `pentest_sessions.workflow_id` is nullable.
  **Rollback:** `003_workflows_and_domain_agents.py` `downgrade()` drops new tables + the FK column.

### 1.5 Acceptance criteria

- `alembic upgrade head` clean on a v3.1.7 DB.
- `ModelRouter.resolve` returns the right model and enforces admin gate on opus.
- All existing tests (`pytest backend/tests`) still pass.

---

## §2. Phase 1 — Tool Catalog Expansion (Claude-OSINT migration)

**Goals.** Land knowledge packs, the passive-validator runtime, and ~6 new Docker tool adapters. Refactor the registry to support capability metadata.

### 2.1 Hybrid integration map (Claude-OSINT → OSA)

| Claude-OSINT asset | OSA destination | Type |
|---|---|---|
| `skills/osint-methodology/*.md` (methodology) | `backend/knowledge_packs/osint-methodology/v1.0/` | Knowledge pack (markdown only) |
| `skills/offensive-osint/*.md` (90 modules across 12 domains) | `backend/knowledge_packs/offensive-osint/v1.0/` | Knowledge pack (markdown only) |
| `stdlib/secret_scan.py` (48 regex patterns) | `backend/app/agents/native/secret_scan.py` + `backend/app/agents/native/secret_patterns.yaml` | Native Python tool (`safety_profile=passive`) |
| 9 read-only validators (DNS, CT, MX, SPF/DKIM/DMARC, robots, sitemap, certificate, security.txt, .well-known) | `backend/app/agents/native/passive_validators/*.py` | Native Python (`safety_profile=passive`) |
| Subdomain enumeration tradecraft | New Docker adapter `subfinder` (`projectdiscovery/subfinder`) | Docker tool |
| DNS recon (active) | New Docker adapter `dnsx` (`projectdiscovery/dnsx`) | Docker tool |
| Web surface mapping | New Docker adapter `httpx` (`projectdiscovery/httpx`) | Docker tool |
| Cloud bucket enumeration | New Docker adapter `cloudenum` (`initstring/cloud_enum`) | Docker tool |
| Vendor fingerprint / tech stack | New Docker adapter `wappalyzer-cli` | Docker tool |
| 90-module dork/regex catalogs | `backend/knowledge_packs/dorks/` (YAML + markdown) | Knowledge pack (data) |

> **Why this split:** Markdown methodology is *planning context for the AI* — it shapes which tools the AI picks, not what executes. Active probing must execute in Docker (Principle 3). Passive validators (read-only HTTP/DNS) are low enough risk to run native, but only against an allowlist (`settings.passive_egress_allowlist`).

### 2.2 New files

- `backend/app/agents/native/__init__.py`
- `backend/app/agents/native/base.py` — `NativePassiveAdapter` (analogue of `AgentAdapter` but executes in-process via `httpx`/`aiohttp`/`dnspython`; emits same `AgentEvent` stream; respects `settings.passive_egress_allowlist`).
- `backend/app/agents/native/secret_scan.py`
- `backend/app/agents/native/secret_patterns.yaml`
- `backend/app/agents/native/passive_validators/dns_resolver.py`
- `backend/app/agents/native/passive_validators/cert_transparency.py` (queries `crt.sh`)
- `backend/app/agents/native/passive_validators/mx_spf_dmarc.py`
- `backend/app/agents/native/passive_validators/robots_sitemap.py`
- `backend/app/agents/native/passive_validators/well_known.py`
- `backend/app/agents/native/passive_validators/securitytxt.py`
- `backend/app/agents/native/passive_validators/__init__.py`
- `backend/app/agents/subfinder.py`
- `backend/app/agents/dnsx.py`
- `backend/app/agents/httpx_tool.py`
- `backend/app/agents/cloudenum.py`
- `backend/app/agents/wappalyzer.py`
- `backend/knowledge_packs/osint-methodology/v1.0/{README.md, modules/*.md, MANIFEST.yaml}`
- `backend/knowledge_packs/offensive-osint/v1.0/{README.md, modules/*.md, MANIFEST.yaml}`
- `backend/knowledge_packs/dorks/v1.0/{github.yaml, google.yaml, shodan.yaml, MANIFEST.yaml}`
- `backend/app/agents/knowledge_pack_loader.py` — boot-time loader, computes SHA256, refuses YAML/MD with executable hooks, populates `knowledge_packs` table.
- `docker/agents/Dockerfile.subfinder`
- `docker/agents/Dockerfile.dnsx`
- `docker/agents/Dockerfile.httpx`
- `docker/agents/Dockerfile.cloudenum`
- `docker/agents/Dockerfile.wappalyzer`

### 2.3 Registry refactor

**Edit:** `backend/app/agents/registry.py`

Replace the flat dict with a dataclass-backed registry that carries capability metadata. Backwards-compatible `get_adapter(slug)` is preserved.

```python
@dataclass(frozen=True)
class ToolEntry:
    slug: str
    adapter_cls: type[AgentAdapter] | type[NativePassiveAdapter]
    backend_kind: Literal["docker", "native_passive"]
    capabilities: tuple[str, ...]
    default_risk_band: RiskLevel
    is_active_recon: bool          # see Principle 4
    is_destructive_capable: bool
    docker_image: str | None       # None for native

_REGISTRY: dict[str, ToolEntry] = { ... }
def get_adapter(slug: str) -> AgentAdapter | NativePassiveAdapter: ...
def list_tool_entries() -> list[ToolEntry]: ...
def lookup_by_capability(cap: str) -> list[ToolEntry]: ...
```

### 2.4 Safety integration for new tools

- **Active OSINT tools** (`subfinder`, `dnsx`, `httpx`, `cloudenum`, `wappalyzer`) are added to `BLOCKED_AUTO_SEVERITIES`-style review by extending `exploit_allowlist.py`:
  - New module `backend/app/safety/osint_allowlist.py` with `ACTIVE_OSINT_ALLOWED_FLAGS` per tool (e.g., `subfinder` may run with `-passive`, may NOT run with `-active` unless workflow's `approved_active_recon=true`).
  - `filter_plan_steps` extended to consult `osint_allowlist` when `step.agent` is an OSINT tool.
- **Passive native tools** run only when their target IP/domain is in `passive_allowed` (or unset → fall back to `whitelist_rules.domains`). Their network calls go through an HTTPX client preconfigured with `settings.passive_egress_allowlist`.
- **Risk filter** (`backend/app/safety/risk_filter.py`): extend `_AGENT_BASE_RISK`:
  ```python
  _AGENT_BASE_RISK |= {
      "subfinder": 0.3, "dnsx": 0.3, "httpx": 0.45,
      "cloudenum": 0.5, "wappalyzer": 0.35,
      "secret_scan": 0.1, "dns_resolver": 0.05, "cert_transparency": 0.05,
      "mx_spf_dmarc": 0.05, "robots_sitemap": 0.1, "well_known": 0.1, "securitytxt": 0.05,
  }
  ```

### 2.5 Risks and rollback

- **Risk:** native passive runtime introduces a non-Docker execution path; could regress security posture.
  **Mitigation:** `NativePassiveAdapter.execute()` enforces `settings.passive_egress_allowlist` via a single `httpx.AsyncClient(transport=AllowlistTransport)`; reject-by-default; per-call audit log; bounded request rate; no shell.
- **Risk:** knowledge pack content drift (upstream Claude-OSINT changes).
  **Mitigation:** vendored at a pinned commit; SHA256 in `knowledge_packs` table; loader refuses to start if hash mismatch.
- **Rollback:** disable new tool slugs via `domain_agent_tools.enabled_by_default=false`; remove knowledge packs from `domain_agents.knowledge_pack_id`.

### 2.6 Acceptance criteria

- `python -m app.agents.knowledge_pack_loader --verify` exits 0 and prints SHA256s.
- New Docker images build (`docker compose -f docker-compose.yml -f docker-compose.agents.yml build`).
- `pytest backend/tests/unit/test_secret_scan_regex.py` green with ≥48×2 fixtures.
- `pytest backend/tests/integration/test_passive_validator_egress.py` green; out-of-allowlist call returns 403-equivalent and is audit-logged.

---

## §3. Phase 2 — Domain-Agent Catalog

**Goals.** Make `web-app-agent`, `network-agent`, `cloud-aws-agent`, `cloud-azure-agent`, `cloud-gcp-agent`, `mobile-agent`, `api-security-agent`, `osint-agent` first-class entities. Optional (toggle): `identity-agent`, `container-k8s-agent`.

### 3.1 Domain agent definitions (seed migration data)

Seeded via `backend/alembic/versions/003_workflows_and_domain_agents.py` `data_upgrade()`:

| slug | display name | knowledge pack | default risk band | requires role | core tool palette |
|---|---|---|---|---|---|
| `osint-agent` | OSINT / Recon | `offensive-osint/v1.0` | low | member | `secret_scan`, `dns_resolver`, `cert_transparency`, `mx_spf_dmarc`, `robots_sitemap`, `well_known`, `securitytxt`, `subfinder` (passive), `dnsx` (passive), `httpx` (passive) |
| `web-app-agent` | Web Application | `offensive-osint/v1.0` (web-surface modules) | medium | member | `nuclei`, `httpx`, `wappalyzer`, `subfinder`, `dnsx`, `nmap` |
| `network-agent` | Network | none (uses nmap defaults) | medium | member | `nmap`, `nuclei`, `dnsx` |
| `cloud-aws-agent` | Cloud — AWS | `offensive-osint/v1.0` (cloud-modules) | medium | member | `cloudenum`, `nuclei` (cloud templates), `httpx` |
| `cloud-azure-agent` | Cloud — Azure | same | medium | member | same with Azure-only configs |
| `cloud-gcp-agent` | Cloud — GCP | same | medium | member | same with GCP-only configs |
| `mobile-agent` | Mobile (static-only MVP) | none yet | low | member | `secret_scan`, `nuclei` (mobile templates) — see Open Q #4 |
| `api-security-agent` | API Security | `offensive-osint/v1.0` (api modules) | medium | member | `nuclei` (api templates), `httpx`, `wappalyzer` |
| `identity-agent` (opt) | Identity / SSO | `offensive-osint/v1.0` (sso modules) | high | admin | `httpx` (passive), `dnsx`, `nuclei` (auth templates) — defaults to passive-only |
| `container-k8s-agent` (opt) | Container / K8s | TBD | medium | admin | `nuclei` (k8s templates), `nmap` — passive-only MVP |

### 3.2 Autonomous tool selection

**New file:** `backend/app/orchestrator/domain_agent.py`

```python
class DomainAgentResolver:
    """Given a DomainAgent and a workflow draft step, pick the best tool from its palette."""
    def resolve_tool(self, domain_agent_slug: str, step_intent: dict,
                     safety_profile: str) -> ToolEntry: ...
    def expand_step_to_executions(self, step: dict, target: dict) -> list[dict]: ...
```

The AI planner emits Workflow steps with `domain_agent` + `intent` (e.g., `intent="enumerate_subdomains"`); the resolver maps `intent` → concrete tool via `lookup_by_capability` filtered by the agent's palette.

### 3.3 RBAC: which agents/tools a user can launch

**Edit:** `backend/app/api/deps.py` and add `backend/app/api/v1/domain_agents.py`.

Rule: `User.role` is matched against `domain_agents.requires_role`. Workflow creation rejects (`409`) if the selected `domain_agent` requires admin and the actor is not admin. Same rule applies on workflow approval (re-checked, since roles can change between draft and approval).

New endpoints:
- `GET /api/v1/domain-agents/` → list agents visible to current user (filtered by RBAC)
- `GET /api/v1/domain-agents/{slug}` → details (palette, knowledge pack, default risk band)

### 3.4 Frontend additions for domain selection

- `frontend/src/api/client.ts`: `listDomainAgents()`, `getDomainAgent(slug)`
- New component `frontend/src/components/DomainAgentPicker.tsx` (used in §4 workflow chat header)

### 3.5 Risks and rollback

- **Risk:** RBAC drift — admin demoted mid-flight on a workflow they created.
  **Mitigation:** approval re-checks role; if mismatch, workflow transitions to `needs_human_review` (admin re-approval) rather than silently executing.
- **Rollback:** flip all domain agents `is_active=false`; system falls back to flat-agent registry behavior.

### 3.6 Acceptance criteria

- `GET /api/v1/domain-agents/` returns 8 (or 10 with opt-ins) for an admin; fewer for a non-admin.
- `pytest backend/tests/unit/test_domain_agent_palette.py` green.

---

## §4. Phase 3 — Workflow-Draft UX (chat + interview + structured editor)

**Goals.** Replace `<textarea> → POST /sessions/` with the chat→draft→interview→review→approve flow.

### 4.1 Backend endpoints

**New file:** `backend/app/api/v1/workflows.py`

| Method | Path | Purpose | Status transitions |
|---|---|---|---|
| `POST` | `/api/v1/workflows/` | Create workflow (body: `project_id`, `domain_agent_slug`, `model_id`, optional `title`) | `draft` |
| `GET` | `/api/v1/workflows/` | List for project | — |
| `GET` | `/api/v1/workflows/{id}` | Detail (incl. `draft_json`, `messages`, `ambiguity_score`) | — |
| `POST` | `/api/v1/workflows/{id}/messages` | Send user message; AI responds, updates `draft_json`, recomputes ambiguity score | `draft` → `interviewing` → (auto when score < threshold) `ready_for_review` or `needs_human_review` if cap hit |
| `PATCH` | `/api/v1/workflows/{id}/draft` | User edits the structured draft (reorder steps, edit scope, toggle tools) — server validates schema | `ready_for_review` (stays) |
| `POST` | `/api/v1/workflows/{id}/approve` | Approve; runs all four safety layers; if pass, creates `PentestSession(workflow_id=...)` and kicks off existing orchestrator | `approved` → `executing` |
| `POST` | `/api/v1/workflows/{id}/reject` | Reject; final state | `rejected` |

### 4.2 New service modules

- `backend/app/orchestrator/workflow_service.py`
  - `create_workflow(project, user, domain_agent_slug, model_id) -> Workflow`
  - `append_user_message(workflow, content) -> AssistantTurn` (calls model, updates draft, recomputes ambiguity)
  - `update_draft(workflow, patch) -> Workflow` (server-side schema validation)
  - `approve(workflow, user) -> PentestSession` (final safety validation → kick orchestrator)
- `backend/app/orchestrator/ambiguity_scorer.py`
  - Deterministic scorer (see §4.3).
- `backend/app/orchestrator/workflow_prompts.py`
  - Per-domain-agent system prompts; renders the agent's knowledge pack methodology + the project's whitelist + scope constraints.

### 4.3 Ambiguity scorer (deterministic)

```python
def compute_ambiguity(draft: dict, target: dict) -> float:
    # Returns 0.0 (fully specified) to 1.0 (totally vague).
    weights = {
        "has_target_scope": 0.20,         # any IP/domain present and in whitelist
        "has_engagement_window": 0.10,    # start/end timestamps
        "has_per_step_intent": 0.20,      # every step has non-empty `intent`
        "has_per_step_tool_or_agent": 0.15,
        "has_risk_acknowledgment": 0.10,  # user confirmed active_recon flag if any step needs it
        "has_credential_scope": 0.10,     # creds-in-scope yes/no answered
        "has_data_handling_decision": 0.05,
        "has_reporting_audience": 0.05,
        "ambiguous_language_penalty": 0.05,  # regex on "maybe", "probably", "etc." in draft
    }
    score = 1.0
    for key, w in weights.items():
        if _is_satisfied(key, draft, target):
            score -= w
    return max(0.0, round(score, 3))
```

Transitions:
- If `ambiguity ≤ settings.workflow_ambiguity_threshold` (default 0.35) → `ready_for_review`.
- Else, AI is prompted to ask the *single* highest-weight unsatisfied question.
- If `turn_count ≥ settings.workflow_max_interview_turns` (6) OR `last_two_turns_delta < settings.workflow_min_ambiguity_delta` (0.15) → `needs_human_review`.

### 4.4 Frontend: new pages and components

- `frontend/src/pages/WorkflowChat.tsx` — chat UI; sidebar shows live `draft_json` rendered as structured editor; model selector pinned at top; ambiguity progress bar; "Review & Approve" CTA enabled only when status = `ready_for_review`.
- `frontend/src/pages/WorkflowReview.tsx` — structured editor: drag-to-reorder steps (`@dnd-kit/sortable`), per-step scope chips, per-step risk badge, per-step tool select (constrained by domain agent's palette). Out-of-scope hostnames highlighted red via client-side whitelist preview. Approve button disabled while red highlights exist.
- `frontend/src/components/AmbiguityMeter.tsx`
- `frontend/src/components/ModelSelector.tsx` (sonnet-4-6 / opus-4-6; opus disabled for non-admin)
- `frontend/src/components/StructuredStepEditor.tsx`
- `frontend/src/api/client.ts`: new functions `createWorkflow`, `getWorkflow`, `listWorkflows`, `sendWorkflowMessage`, `updateWorkflowDraft`, `approveWorkflow`, `rejectWorkflow`.

### 4.5 ProjectDetail.tsx rewrite

Replace the single-textarea launcher with two CTAs: **"Start guided session (recommended)"** → `/projects/:id/workflows/new`; **"Legacy quick prompt"** (admin-only, hidden by default; can be removed in v3.2.1 once parity is verified).

### 4.6 Risks and rollback

- **Risk:** users lose the speed of the old freeform launcher.
  **Mitigation:** preserve a legacy admin-only path for 1 release; ambiguity scorer is tuned so a fully-specified prompt produces ≤1 interview turn.
- **Risk:** WebSocket churn from live draft updates.
  **Mitigation:** reuse existing `event_bus`; throttle to 1 update/second; client-side optimistic updates.
- **Rollback:** feature flag `settings.workflow_ui_enabled` (default true) — flipping false re-enables the v3.1 single-textarea path.

### 4.7 Acceptance criteria

- E2E `launch_pentest_session_flow.spec.ts` passes end-to-end.
- Ambiguity scorer is unit-tested for monotonicity and determinism.
- Approve fails with 409 + violations list on out-of-scope targets.

---

## §5. Phase 4 — Safety Integration

**Goals.** Make sure the new workflow + OSINT surface stays inside the existing safety chain, and add the active/passive risk band.

### 5.1 Whitelist extensions

**Edit:** `backend/app/safety/whitelist.py`

Add:
- `validate_target(target, profile: Literal["active","passive"]) -> tuple[bool, list[str]]` — passive falls back to `passive_allowed` if `active_allowed` is empty.
- `validate_discovered_targets(discoveries: list[str], rules) -> tuple[list[str], list[str]]` — splits into `accepted` / `rejected`; called by every active OSINT adapter after enumeration, before any probe of discovered hosts.
- `wildcard_block_regex` enforcement.

### 5.2 Risk filter extensions

**Edit:** `backend/app/safety/risk_filter.py`

- New `risk_band` enum value: `OSINT_PASSIVE` (mapped to existing `LOW`) and `OSINT_ACTIVE` (mapped to `MEDIUM`).
- `assess_step` consults `step.active_recon` flag; if true and `step.domain_agent` is opt-in (identity/container), bump one band.

### 5.3 Exploit allowlist extension

**New file:** `backend/app/safety/osint_allowlist.py`

```python
ACTIVE_OSINT_ALLOWED_FLAGS = {
    "subfinder": {"-passive", "-silent", "-all"},  # -active deliberately omitted
    "dnsx": {"-resp", "-silent", "-a", "-mx", "-txt"},
    "httpx": {"-silent", "-status-code", "-title", "-tech-detect"},
    "cloudenum": {"-k"},
    "wappalyzer": set(),  # safe defaults only
}
def filter_osint_step(step: dict) -> tuple[bool, str | None]: ...
```

`filter_plan_steps` in `exploit_allowlist.py` is extended to dispatch to `osint_allowlist.filter_osint_step` for OSINT slugs.

### 5.4 Egress monitor

**Edit:** `backend/app/safety/egress_monitor.py`

- Add `passive_egress_allowlist` awareness: for adapters with `safety_profile=passive`, allow domain-based egress (not just IP) against `settings.passive_egress_allowlist`.
- New audit action `passive_egress_violation` (currently only IP-based `safety_alert` is emitted).

### 5.5 Audit log additions

- `workflow_created`, `workflow_message_sent`, `workflow_draft_updated`, `workflow_approved`, `workflow_rejected`, `workflow_needs_human_review`.
- `active_osint_target_validated`, `active_osint_target_rejected`.
- `knowledge_pack_loaded`.

### 5.6 Acceptance criteria

- Approving a workflow whose draft references an out-of-scope host returns 409 with the violation list.
- An active OSINT step whose `-active` flag is missing from `ACTIVE_OSINT_ALLOWED_FLAGS` is blocked.
- Native passive validator hitting `evil.example.com` (not in `passive_egress_allowlist`) is blocked and audit-logged.

---

## §6. Phase 5 — Tests, Observability, Docs

### 6.1 Tests

(See §0.5 for the full breakdown.) Target: ≥30 new unit, ≥12 new integration, ≥4 new e2e.

### 6.2 Observability

- Prometheus metrics endpoint `/metrics` (existing) gains the new series listed in §0.5.
- Add Grafana dashboard JSON in `docs/observability/workflow-dashboard.json` (LOC-bounded; just the new panels).

### 6.3 Docs

- `docs/workflow-flow.md` — sequence diagram + state machine.
- `docs/domain-agents.md` — catalog reference.
- `docs/knowledge-packs.md` — how to add/update; SHA pinning.
- Update `README.md` with v3.2 highlights.

### 6.4 Acceptance criteria

- All listed tests pass in CI.
- New metrics visible after running a chat workflow end-to-end in dev.
- Docs build clean.

---

## §7. Phase ordering, dependencies, timeline

```
P0 (Foundations) ─┬─► P1 (Tools) ─┬─► P2 (Domain agents) ─┬─► P3 (Workflow UX) ─► P4 (Safety hooks) ─► P5 (Tests/Obs/Docs)
                  │               │                       │
                  └── settings    └── registry refactor   └── knowledge pack loader required for prompts
```

**Suggested cadence (1 senior + 1 mid eng):**
- P0: 3 days
- P1: 7 days (Docker images + native validators dominate)
- P2: 4 days
- P3: 8 days (frontend heavy)
- P4: 3 days (touch existing safety surface, careful)
- P5: 4 days

Total ~29 dev-days, ~6 calendar weeks at 0.7 utilization.

---

## §8. ADR — Architecture Decision Record

**ADR-v3.2.0.1 — Hybrid Claude-OSINT integration (knowledge packs + native passive validators + selective Docker tools)**

- **Decision.** Adopt option **A3** from §0.3.
- **Drivers.** (1) Safety-chain coverage invariant; (2) ROI of porting 5,500 lines of markdown is poor if treated as code; (3) need for reproducible auditable execution.
- **Alternatives considered.** A1 (port everything to Docker), A2 (knowledge-only, no executors).
- **Why chosen.** A3 preserves safety-chain coverage for executable code, harvests the methodology as planning context, and adds only ~6 Docker images instead of ~90.
- **Consequences.** New `NativePassiveAdapter` runtime; new `knowledge_packs` table; tighter governance on `passive_egress_allowlist`; one-time vendoring of upstream content with SHA pinning.
- **Follow-ups.** Quarterly resync against upstream Claude-OSINT; SHA recomputation; secret-pattern regression suite.

**ADR-v3.2.0.2 — Tiered domain-agent model (DomainAgent + curated tool palette)**

- **Decision.** Adopt option **B2**.
- **Drivers.** Market-segmented agent catalog; clean separation of planning persona vs. execution adapter; tool-add velocity.
- **Alternatives considered.** B1 (mega-agent per domain), B3 (flat, no domains).
- **Why chosen.** B2 is the only option that satisfies the user-facing market reorg ask *and* leaves the existing `AgentAdapter` surface untouched.
- **Consequences.** New `domain_agents` + `domain_agent_tools` tables; new `DomainAgentResolver` in orchestrator; RBAC at agent-grant level.
- **Follow-ups.** Phase out `OrchestratorService._planner` "flat-agent" code path once parity is proven (target: v3.2.1).

**ADR-v3.2.0.3 — Chat + structured editor workflow UX**

- **Decision.** Adopt option **C2**.
- **Drivers.** Need for ambiguity reduction (chat) + auditable step-level editing (structured form) + explicit approval gate.
- **Alternatives considered.** C1 (chat-only), C3 (form-only wizard).
- **Why chosen.** C2 is the only option that preserves Principle 2 (advisory until approved) without losing the elicitation value of chat.
- **Consequences.** New `workflows` + `workflow_messages` tables; new chat+editor frontend pages; deterministic ambiguity scorer; cost budget enforcement; legacy single-textarea path kept for one release behind a flag.
- **Follow-ups.** Tune `workflow_ambiguity_threshold` after first 50 real sessions; consider per-domain-agent custom scorers in v3.3.

---

## §9. Open Questions (need user input before/during execution)

> Persisted into `.omc/plans/open-questions.md` per Planner protocol.

1. **Exact Anthropic model IDs for `claude-sonnet-4-6` and `claude-opus-4-6`.** The current `settings.anthropic_model` is `claude-sonnet-4-20250514`. We need confirmed model strings for both options and their per-1k token prices for cost accounting. Plan currently uses `claude-sonnet-4-6-20250514` / `claude-opus-4-6-20250514` as placeholders.
2. **Ambiguity threshold default (0.35) and turn cap (6) — acceptable?** Or do you want a different elicitation aggressiveness?
3. **Optional agents — ship `identity-agent` and `container-k8s-agent` in v3.2.0 or defer to v3.2.1?** Plan keeps them feature-flagged off by default.
4. **`mobile-agent` MVP scope.** Static analysis only (`secret_scan` on APK/IPA contents) or also dynamic (Frida/MobSF in Docker)? Plan assumes static-only for v3.2.0.
5. **Legacy single-textarea path — keep for one release behind admin flag (current plan) or remove immediately?**
6. **Daily USD budget default of $5/user — too low/high?** Admin-overridable per team.
7. **Knowledge-pack vendoring — vendor a snapshot at a pinned commit, or `git submodule`?** Plan assumes vendored snapshot with SHA pinning.
8. **Do we want a Docker image for `secret_scan` too (uniform execution) or accept the native-Python path for low-risk passive scans?** Plan goes native to avoid 48-pattern regex inside a container for a 200-line script.
9. **Wildcard block regex examples per project** — should this be a project-level setting with a UI editor in `Admin.tsx`, or a YAML in `whitelist_rules`? Plan currently puts it inside `whitelist_rules` JSONB.

---

## §10. Plan Summary (for confirmation)

**Plan saved to:** `.omc/plans/offensive-security-agent-consensus-v3.2.0.md`

**Scope.**
- 6 phases (P0–P5)
- ~24 new files, ~12 edited files, 1 new Alembic migration, 5 new Docker images, 1 new native-Python runtime, 8 new domain agents (10 with opt-ins), 7 new REST endpoints, 6 new frontend components/pages.
- Estimated complexity: **HIGH**

**Key deliverables.**
1. `workflows` + `workflow_messages` + `domain_agents` + `domain_agent_tools` + `knowledge_packs` tables.
2. `ModelRouter` (sonnet-4-6 / opus-4-6) with RBAC + cost budget.
3. Hybrid Claude-OSINT migration: 3 knowledge packs + 7 native passive validators + 5 active OSINT Docker tools.
4. 8 domain agents (+2 opt-in) with curated tool palettes and RBAC gating.
5. Chat-driven workflow-draft UI with deterministic ambiguity scorer + structured editor + approval gate.
6. Extended safety chain (active vs. passive distinction; discovered-target re-validation; passive egress allowlist).
7. ≥46 new tests across unit/integration/e2e + observability dashboards.

**Does this plan capture your intent?**
- `proceed` — hand off to `/oh-my-claudecode:start-work offensive-security-agent-consensus-v3.2.0`
- `adjust [X]` — return to interview to modify (especially Open Questions §9)
- `restart` — discard and start fresh
