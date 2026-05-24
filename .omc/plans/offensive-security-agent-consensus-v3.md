# Offensive Security Agents Platform — Consensus Plan v3 (Planner Draft)

**Source:** v2.1 plan + Deep-Interview Round 1-3 (2026-05-10)
**Mode:** Consensus (Deliberate — security domain, Azure privesc, credential storage)
**Iteration:** 1 (Planner draft, awaiting Architect review)
**Baseline:** Current implementation 85/85 tests passing, monolithic FastAPI + 4 tool-based agents + RBAC + WS + PDF reports

---

## 0. What Changes vs v2.1

| Dimension | v2.1 (Implemented) | v3 (This plan) |
|---|---|---|
| Agents | 4 tool-based (Nmap/Nuclei/Metasploit/PyRIT) | 4 **domain-based** (Application/Web/Cloud-Azure/Source Code) — tool agents become private internal adapters |
| Interaction | Sequential per plan step | **Hierarchical orchestrator** — Master spawns sub-orchestrators per domain, coordinates via shared blackboard |
| Targets per project | 1 unified whitelist | **Multi-target** with per-target type + scope_rules + concurrency limit |
| Cloud support | `cloud_provider` string only | Full **Azure** stack: Entra ID + ScoutSuite + Microburst + PowerZure (priv-esc sim, gated) |
| Source code | None | **Git URL + Semgrep + Trivy + gitleaks** (clone-in-container) |
| Credentials | None | **AES-GCM encrypted at-rest** in DB + role-gated (admin CRUD) + per-target binding |
| Collaboration UI | Per-session monitor | Project **threaded comments** + per-finding annotations + **activity timeline** + **multi-session campaign** view |
| Health monitoring | Static `/health` endpoint | **Dedicated periodic agent** (30s) — DB/Docker/Claude/agents/WS/disk + admin alerts |
| Execution scheduling | One step at a time | **Parallel** target processing (default 2-3 concurrent), Master arbitrates |

**Backward compatibility:** All v2.1 endpoints preserved. Tool adapters internalized but kept under `app/agents/_tools/`. Existing test suite (85 tests) must continue to pass after refactor.

---

## 1. RALPLAN-DR Summary

### Principles
1. **Safety-First Autonomy** — Every new attack capability ships with at least one new safety guard (whitelist, allowlist, audit, kill-switch wired). Privilege escalation simulation is gated behind explicit human approval per session, not just allowlist.
2. **Domain Encapsulation** — Domain agents own their tooling, output normalization, and risk profile. Master orchestrator never reaches into adapter internals; sub-orchestrators only escalate up via blackboard events.
3. **Credential Minimization** — Credentials are encrypted at-rest, decrypted only into the executing container's env, never logged, scrubbed from agent output before persistence, and never echoed in WS broadcasts.
4. **Auditability** — Every domain agent action, sub-orchestrator decision, blackboard write, and credential access is audit-logged with actor + timestamp + redacted details.
5. **Incremental Refactor with Test Preservation** — Despite "All-in-one MVP" decision, refactoring existing 4 tool adapters into private internals must keep all 85 existing tests green. New code adds tests; no green-field regressions.

### Decision Drivers (Top 3)
1. **Risk explosion from privilege escalation simulation** — PowerZure / Stormspotter touch real Azure tenants. The blast radius is now larger than v2.1; safety must scale up proportionally (per-session priv-esc human gate, audit, egress monitor extended to Azure ARM endpoints).
2. **Refactor blast radius vs new feature delivery** — Replacing 4 tool agents with 4 domain agents while adding hierarchy, collab UI, health worker, multi-target — extreme scope. Single biggest delivery risk.
3. **Credential lifecycle correctness** — encrypted-at-rest + per-container injection + scrubbing + revocation + key rotation must be airtight or the platform itself becomes the attack surface.

### Viable Options

#### Option A: Hierarchical Orchestrator + Shared Blackboard (Recommended)
**Approach:** Master `OrchestratorService` keeps the public entry. Per session, Master parses the prompt and target list, then spawns one `SubOrchestrator` per domain target (asyncio task). Sub-orchestrators read/write to a session-scoped `Blackboard` (asyncio-backed in MVP, Redis pub/sub in Phase-2). Master polls blackboard between sub-iterations and feeds Claude API for replanning. Sub-orchestrators internally call domain adapters (Application/Web/Cloud-Azure/Source-Code), each of which wraps the existing tool adapters.

**Pros:**
- Aligns with answered architecture (Hierarchical + Domain agents + Parallel + Blackboard)
- Minimal new infra — pure asyncio, no Redis/Celery for MVP
- Replaces v2.1 sequential `for step in steps` cleanly with `asyncio.gather` over sub-orchestrators
- Existing safety chain (whitelist, allowlist, risk filter, egress) stays at Master level → preserved guarantees
- Claude rate-limit applied once per session, not per agent

**Cons:**
- In-memory blackboard tied to single backend instance — no horizontal scaling until Redis migration
- Asyncio task supervision, cancellation propagation, error isolation across sub-orchestrators is non-trivial
- Failure of one domain (e.g., Azure auth fails) must not kill other sub-orchestrators — explicit error boundaries needed

#### Option B: Master + Worker Process Pool (Celery-based)
**Approach:** Master enqueues per-domain sub-orchestrator jobs to Celery; blackboard backed by Redis. WebSocket consumes Redis pub/sub.

**Pros:**
- Horizontal scale-out from day one
- True process isolation between sub-orchestrators — Azure crash cannot affect Web sub-orchestrator
- Built-in retry, rate limiting, ETA scheduling

**Cons:**
- Adds Redis + Celery + beat scheduler — large infra delta
- v2.1 explicitly chose monolithic; switching now contradicts ADR consequence "migrate to Celery if >10 concurrent sessions"
- Triple framework (FastAPI + Celery + asyncio) increases debug surface
- Over-engineered for stated concurrency level (2-3 targets/project, MVP scale)

#### Invalidation of Other Alternatives
- **Pure Reactive Replanner (no hierarchy)** — Rejected: user explicitly chose Hierarchical Orchestrator over Shared Blackboard alone.
- **A2A direct messaging** — Rejected: user explicitly chose Hierarchical over A2A in Round 1.
- **Microservice per domain** — Rejected: explicit "All-in-one MVP" decision; would require 4 deployable services + service mesh.

### Decision
**Option A — Hierarchical Orchestrator + Shared Blackboard.** Migrate to Redis-backed blackboard + Celery only when concurrent multi-domain sessions exceed 10 sustained, deferred per v2.1's existing follow-up.

---

## 2. Pre-Mortem (Deliberate Mode — 3 Failure Scenarios)

### Scenario 1: Azure Privilege Escalation Bursts Out of Scope
**What goes wrong:** Operator submits an Azure subscription target. PowerZure runs a privilege-escalation chain that pivots into a sibling subscription via cross-tenant guest invitations. Azure ARM API calls succeed because the Service Principal has wider-than-intended permissions. Egress monitor only watches IPs (not ARM resource scope).

**Likelihood:** Medium-High — Azure RBAC misconfiguration is one of the most common cloud findings.
**Impact:** **Critical** — Real privilege escalation against unrelated client tenant; legal and contractual liability beyond original engagement.

**Mitigation:**
- **Per-session human approval** for any priv-esc step (override of full-auto for Cloud-Azure agent's HIGH risk steps).
- **Azure Resource Scope Validator** (new safety guard, post-egress) — extracts subscription_id / tenant_id from every Azure SDK call, validates against `target.scope_rules.azure_subscriptions` whitelist before execution. Wraps Azure SDK at adapter level.
- **Service Principal least-privilege checklist** — UI requires admin to confirm SP has `Reader` only; warns if `Owner`/`Contributor`/`User Access Administrator`.
- **Credentials never include refresh tokens** — only Service Principal client_secret with explicit subscription scope; tokens expire on session end.
- **Integration test:** mock Azure SDK responses for cross-tenant call → must be blocked by scope validator before egress.

### Scenario 2: Blackboard Race Condition Causes Duplicate / Conflicting Plans
**What goes wrong:** Web sub-orchestrator finds an LFI vulnerability, writes to blackboard. Cloud-Azure sub-orchestrator simultaneously reads blackboard and replans, but its asyncio tick happens mid-write → reads stale state. Master then receives two conflicting "next step" proposals, picks the wrong one, and Claude is given an inconsistent context window.

**Likelihood:** Medium — concurrent asyncio without explicit locks is failure-prone.
**Impact:** Medium — incoherent attack plans, wasted Claude tokens, potentially unsafe step ordering (e.g., post-exploit before initial access verified).

**Mitigation:**
- **Blackboard writes are atomic via single asyncio.Lock per session** — readers always see complete deltas.
- **Versioned blackboard entries** — every write increments a session-scoped monotonic version. Sub-orchestrators include observed_version when proposing next step; Master rejects stale proposals (CAS-style).
- **Master arbitration window** — Master batches sub-orchestrator events on a 500ms tick before invoking Claude replan, ensuring batch-consistent input.
- **Unit test:** simulate 10 concurrent sub-orchestrators racing to write findings → final blackboard state has all entries, none lost, version monotonic.

### Scenario 3: Encrypted Credentials Leak via Agent Logs
**What goes wrong:** Service Principal `client_secret` is decrypted into the Azure container's env. The Azure SDK's `--debug` flag is accidentally enabled in the adapter's command builder; SDK prints the bearer token to stdout; `EgressMonitor.monitor_log_line` and `event_bus.publish` send the log line to all WebSocket subscribers (including the operator's browser, captured in browser dev-tools). Token is now logged in audit trail and broadcast to multiple users.

**Likelihood:** Medium — common mistake; hard to detect via tests.
**Impact:** **Critical** — Service Principal bearer token in audit log = persistent breach of client tenant.

**Mitigation:**
- **`SecretScrubber` middleware** — every log line passing through `event_bus.publish` runs through regex denylist (Bearer tokens, JWT shapes, Azure SAS, AWS keys, GitHub PAT pattern, common secret formats); matches replaced with `[REDACTED:type]`.
- **Adapter-level command builder review** — Azure adapter explicitly forbids `--debug` / `-vvv` flags; lint test enforces.
- **Container env never written to logs** — adapter wraps Docker SDK so env is set via Docker API, never via shell-visible commands.
- **Audit log entries with `details_json` are scrubbed before persistence** — separate scrubber pass.
- **Integration test:** plant a fake bearer token in a mock agent's stdout → assert it never appears in WebSocket events, audit logs, or finding output.

---

## 3. Expanded Test Plan (Deliberate Mode)

### Unit Tests (new + revised)

| Component | Test | Acceptance |
|---|---|---|
| `Blackboard` | Atomic write under concurrent writers | 10 writers × 100 writes → all 1000 entries present, version monotonic |
| `Blackboard` | CAS rejects stale-version proposals | Old observed_version → write returns False |
| `Master.arbitrate` | Batches sub-orchestrator events on 500ms tick | Single Claude call per tick |
| `SubOrchestrator` | Failure isolation | One sub raises → others continue, master sees failed sub but completes others |
| `ApplicationAgent` | Wraps Nmap adapter for app-layer scan | Calls existing Nmap with app-specific flags |
| `WebAgent` | Wraps Nuclei adapter for web | Calls existing Nuclei, normalizes output |
| `CloudAzureAgent.scout_suite` | Read-only audit returns findings | Mock SDK call, parse JSON output |
| `CloudAzureAgent.microburst` | Storage account public-blob check | Detects misconfigured public container |
| `CloudAzureAgent.powerzure` | **Requires explicit approval token** | Without token → blocked + audit log |
| `AzureScopeValidator` | Cross-subscription call rejected | Mock ARM call to non-whitelisted subscription → blocked |
| `SourceCodeAgent.git_clone` | Honors PAT, depth=1 | Clone succeeds; secrets in PAT scrubbed |
| `SourceCodeAgent.semgrep` | Parse Semgrep JSON | Findings normalized to common schema |
| `SourceCodeAgent.gitleaks` | Detect secrets | Plant secret in test repo → detected |
| `SourceCodeAgent.trivy` | SCA finds vulnerable deps | Test fixture package.json with known CVE |
| `CredentialStore.encrypt` | AES-GCM round-trip | Encrypt→decrypt yields original |
| `CredentialStore.decrypt` | Wrong key returns error | InvalidTag exception caught |
| `CredentialStore.role_gating` | Member cannot CRUD | 403 |
| `CredentialStore.injection` | Decrypt only into container env | Backend memory holds plaintext < 1s, never logged |
| `SecretScrubber` | Bearer / JWT / SAS / PAT redacted | All known patterns replaced with `[REDACTED:type]` |
| `SecretScrubber` | False positives bounded | Random text passes through unchanged |
| `HealthCheckAgent.run_cycle` | Status of all subsystems | DB/Docker/Claude/agents/WS/disk → 6 status entries per tick |
| `HealthCheckAgent.thresholds` | Triggers WS alert on threshold breach | Disk >85% → WS event |
| `MultiTarget.scope_rules` | Per-target whitelist enforcement | Project-level not-allowed; per-target allowed |
| `Concurrency.limit` | Max 3 sub-orchestrators per project | 4th queued, not started |
| `CommentService.create` | Project + finding scopes | Both work; member can comment, all read |
| `ActivityTimeline.aggregate` | Combines sessions+findings+comments+state changes | Returns reverse chronological |

### Integration Tests

| Scenario | Test | Acceptance |
|---|---|---|
| End-to-end domain pipeline | Project with 4 targets (web/app/azure/source) → multi-domain session → all 4 sub-orchestrators run | All 4 produce findings, master generates unified report |
| Privilege escalation gate | Plan includes priv-esc step → no approval → blocked | Audit log records approval missing |
| Privilege escalation approved | Same plan + approval token → executes | Real Azure mock call succeeds |
| Credential lifecycle | Admin creates encrypted creds → session uses them → creds never appear in logs/WS/findings | grep audit + WS captures = no leak |
| Health agent integration | Stop Docker daemon → next health tick reports unhealthy → admin WS alert fires | < 35s to detect |
| Multi-target concurrency | Launch session with 5 targets → only 3 run concurrent, 2 queued | Verified via blackboard timestamps |
| Comment thread realtime | Two browsers viewing same project → A posts comment → B receives WS event | < 1s delivery |
| Activity timeline | Project with mixed events → timeline aggregates correctly across sessions/findings/comments/state | Order = reverse chronological |
| Backward compatibility | All 85 existing tests still pass after refactor | 0 regressions |

### E2E Tests

| Scenario | Test | Acceptance |
|---|---|---|
| Full domain demo | Login → create project → add 4 targets (web acme.com / Azure subscription / Git repo / app IP) → launch session → monitor campaign view → kill mid-test → resume → finish → multi-domain unified report → PDF | Full pipeline completes < 25 min |
| Azure read-only audit demo | Project with Azure SP (Reader role) → run Cloud-Azure agent → ScoutSuite findings appear → no priv-esc attempted | Read-only verified, no high-risk steps in audit log |
| Source code SAST demo | Public Git repo → Semgrep + Trivy + gitleaks → findings in unified report | Findings include all 3 tool sources |
| Collaboration demo | Two operators in project → comments + finding annotations → activity timeline reflects both | Both users see each other's events realtime |
| Health agent demo | Stop one agent container → Admin sees red status in 30-60s | Visible in admin health dashboard |
| Concurrent campaigns | 5 projects, each running 2-target sessions simultaneously | No cross-project leakage; kill switch on project A doesn't affect B |

### Observability

| Signal | Implementation | Alert Threshold |
|---|---|---|
| Sub-orchestrator latency | Master timing per spawn → metrics | p95 > 10s |
| Blackboard write rate | counter | > 100/s sustained 30s (replan loop runaway) |
| Claude API per-session token cost | Audit log → aggregation | > 50k tokens/session |
| Health agent tick duration | self-recording | > 25s (slow check) |
| Credential decryption count | counter per actor | spike > 10/min/user |
| Privilege escalation approvals | audit query | any unapproved → page admin |
| Egress / scope violations | audit + WS | any → admin alert + auto-kill |
| Concurrent sub-orchestrators | gauge | > 3 per project (limit breach) |

---

## 4. Architecture Overview

```
                  ┌──────────────────────────────────────────────────┐
                  │              React Frontend (v3)                  │
                  │  Login│Projects│Project Hub│Campaign│Reports│Admin│Health│
                  │   ▲ WS (sessions, comments, health, timeline)     │
                  └─────────────────────┬─────────────────────────────┘
                                        │ REST + WS
                  ┌─────────────────────▼─────────────────────────────┐
                  │              FastAPI Backend (v3)                  │
                  │  ┌───────────────────────────────────────────┐     │
                  │  │      MasterOrchestrator (per session)      │     │
                  │  │  - Parses prompt + targets                │     │
                  │  │  - Spawns SubOrchestrators                │     │
                  │  │  - Reads Blackboard, replans via Claude   │     │
                  │  │  - Applies safety chain at master level   │     │
                  │  └────┬───────┬──────┬─────────────┬──────────┘     │
                  │       │       │      │             │                │
                  │   ┌───▼──┐┌──▼───┐┌─▼─────┐ ┌─────▼──────┐         │
                  │   │ App  ││ Web  ││Cloud- │ │ SourceCode │  Sub-   │
                  │   │Sub-  ││Sub-  ││Azure  │ │   Sub-     │  orch.  │
                  │   │Orch. ││Orch. ││Sub-O. │ │   Orch.    │         │
                  │   └──┬───┘└──┬───┘└──┬────┘ └─────┬──────┘         │
                  │      │       │      │             │                │
                  │   ┌──▼───────▼──────▼─────────────▼──────────┐     │
                  │   │   Internal Tool Adapters (private)        │     │
                  │   │  Nmap | Nuclei | Metasploit | PyRIT |     │     │
                  │   │  ScoutSuite | Microburst | PowerZure |    │     │
                  │   │  ROADrecon | Semgrep | Trivy | gitleaks   │     │
                  │   └────────────────────────┬──────────────────┘     │
                  │                            │ Docker SDK              │
                  │   ┌────────────────────────▼──────────────────┐     │
                  │   │  Safety Chain (extended)                   │     │
                  │   │  Whitelist | Allowlist | Risk | Egress |   │     │
                  │   │  AzureScope | Approval Gate | Scrubber     │     │
                  │   └────────────────────────────────────────────┘     │
                  │                                                      │
                  │   ┌──────────────────────────────────────────────┐   │
                  │   │  HealthCheckAgent (separate asyncio task)    │   │
                  │   │  Cycle: DB → Docker → Claude → Agents → WS   │   │
                  │   │  Persists: health_checks; broadcasts: WS     │   │
                  │   └──────────────────────────────────────────────┘   │
                  │                                                      │
                  │   ┌──────────────────────────────────────────────┐   │
                  │   │  CommentService + ActivityTimeline service   │   │
                  │   └──────────────────────────────────────────────┘   │
                  └────────────────┬─────────────────────────────────────┘
                                   │
                  ┌────────────────▼─────────────────────────────────────┐
                  │           PostgreSQL 16 (extended schema)            │
                  │  v2.1 tables + targets(scope_rules,target_type) +    │
                  │  credentials(encrypted) + comments + finding_notes + │
                  │  activity_events + health_checks + approvals         │
                  └──────────────────────────────────────────────────────┘
```

---

## 5. Implementation Plan (Single Phase 1 — All-in-one MVP)

> **Sequencing within Phase 1:** Schema & safety foundation first (1-2), then domain agents (3), then orchestration refactor (4), then UI (5-7), then health agent (8), then integration & docs (9). This ordering keeps tests green throughout — the existing test suite must pass after every numbered milestone.

### 5.1 Schema & Migrations (alembic 003-006)

**003_multi_target.py**
- Extend `targets`: add `target_type ENUM('application','web','cloud_azure','source_code')` NOT NULL default 'web' (legacy rows backfill = 'web'); add `scope_rules JSONB` (existing column kept, semantics extended); add `name VARCHAR(255)` NOT NULL default 'Default Target' (legacy rows backfill); add `concurrency_limit INT` default 1 (legacy rows = 1).
- Add unique constraint `(project_id, name)`.

**004_credentials.py**
- New `credentials`: id, project_id (FK), target_id (FK NULL = project-wide), name, kind (`azure_sp` | `github_pat`), encrypted_blob (BYTEA), nonce (BYTEA), created_by (FK users), created_at, last_used_at, revoked_at NULL.
- New `approval_grants`: id, session_id (FK), step_index INT, granted_by (FK users), granted_at, action (`privilege_escalation`).

**005_collab.py**
- New `comments`: id, project_id, session_id NULL, finding_id NULL (UUID, references findings_json item id), parent_comment_id (FK self NULL — for threading), author_id, body TEXT, created_at, updated_at, deleted_at NULL.
- New `activity_events`: id, project_id, kind ENUM('session_started','session_completed','session_killed','finding_added','comment_posted','target_added','approval_granted','health_alert'), actor_id NULL, target_entity, target_id, payload_json, created_at. Index `(project_id, created_at DESC)`.

**006_health.py**
- New `health_checks`: id, ts, subsystem (`db`|`docker`|`claude_api`|`agent_<type>`|`websocket`|`disk`|`memory`), status (`healthy`|`degraded`|`unhealthy`), latency_ms, details_json, created_at. Index `(subsystem, ts DESC)`. Retention: trim entries > 7 days via daily prune.

**Existing tests:** all 85 must pass after each migration applied to test SQLite via `aiosqlite` (existing harness in `conftest.py`).

### 5.2 Safety Chain Extensions

- `app/safety/azure_scope.py` — `AzureScopeValidator` wraps Azure SDK calls; extracts `subscription_id`, `tenant_id`, `resource_group` from ARM resource IDs and validates against target's `scope_rules.azure_subscriptions` / `scope_rules.tenants`. Used inside `CloudAzureAgent` only.
- `app/safety/approval_gate.py` — `ApprovalGate.require(session_id, step)` checks `approval_grants` for matching session+step+action; returns ApprovalRequired error if missing. Master orchestrator catches and pauses session into `awaiting_approval` state; UI shows approval modal.
- `app/safety/secret_scrubber.py` — `SecretScrubber.scrub(text) -> str` using compiled regex patterns: bearer tokens, JWT, Azure SAS, AWS keys (`AKIA...`), GitHub PAT (`ghp_...`/`github_pat_...`), common base64-like high-entropy 40+ char strings near credential keywords. Wrap `event_bus.publish`, audit log `details_json`, and finding output before persistence.
- Extend `EgressMonitor` to also recognize `*.azure.com`, `*.microsoftonline.com`, `*.windows.net` ARM endpoints — not just IPs. When matched, route to `AzureScopeValidator` for the body of the request (best-effort, log-line based).

### 5.3 Credential Storage

- `app/core/crypto.py` — `Cipher` class wrapping `cryptography.hazmat.primitives.ciphers.aead.AESGCM`. Master key from `settings.credential_master_key` (32-byte URL-safe base64); validate at startup; refuse to start if missing.
- `app/services/credentials.py` — `CredentialStore.create/get/list/revoke`; `inject_into_env(credential_id) -> dict[str,str]` returns plaintext env dict for passing to Docker `env=` parameter; never logs plaintext; uses RAII pattern (returned dict zeroed via `secrets.token_bytes` after Docker SDK call returns).
- `app/api/v1/credentials.py` — admin-only CRUD (uses `require_admin`); never returns `encrypted_blob` in responses; only metadata.
- Frontend `pages/CredentialManager.tsx` (admin only) — list / create / revoke; create form by `kind` (Azure SP fields: tenant_id, client_id, client_secret, default_subscription; GitHub PAT field: token, optional username).

### 5.4 Domain Agents (replace tool agents publicly)

**Common base:**
- `app/agents/domain/base.py` — `DomainAgent(ABC)` with `agent_type: 'application'|'web'|'cloud_azure'|'source_code'`, `risk_level: RiskLevel`, `capabilities: list[str]`, `default_concurrency: int`. Methods: `plan_steps(target, context)`, `execute_step(step, target, context, sub_blackboard)`, `parse_findings`. Holds reference to internal tool adapters.
- `app/agents/_tools/` — moved from `app/agents/{nmap,nuclei,metasploit,pyrit}.py`. Public `app.agents.registry.get_adapter` deprecated but kept (returns from `_tools` for backward compatibility); existing 85 tests continue to pass.

**ApplicationAgent** (`app/agents/domain/application.py`)
- Capabilities: native binary recon, port enumeration, service fingerprint, msf scanner aux modules.
- Internally uses: Nmap (-sV -sC -O), Metasploit `auxiliary/scanner/*` (allowlist enforced).
- Risk: MEDIUM.

**WebAgent** (`app/agents/domain/web.py`)
- Capabilities: web vulnerability scan, CVE detection, API endpoint discovery, prompt injection (PyRIT) when target is AI-fronted.
- Internally uses: Nuclei (with severity allowlist), PyRIT (when target.metadata.has_llm == true).
- Risk: MEDIUM.

**CloudAzureAgent** (`app/agents/domain/cloud_azure.py`)
- Capabilities: Entra ID audit, resource configuration audit, storage active probing, privilege escalation simulation.
- Internally uses: ScoutSuite (read-only), ROADrecon (Entra), Microburst (storage), PowerZure (priv-esc, **requires ApprovalGate**).
- Risk: HIGH (because priv-esc included).
- Mandatory: every step calls `AzureScopeValidator` before execution; priv-esc class steps go through `ApprovalGate.require`.
- Docker images: `osa-agent-azure:latest` containing scoutsuite, microburst, roadrecon, powerzure, az CLI. Pre-built; ~3GB; lazy-pulled.

**SourceCodeAgent** (`app/agents/domain/source_code.py`)
- Capabilities: SAST, SCA, secret scanning.
- Internally uses: Semgrep (default ruleset + p/owasp-top-ten), Trivy (filesystem mode), gitleaks (full history).
- Input: `target.scope_rules.git_url` + optional credential reference (GitHub PAT). Container clones with depth=1 (gitleaks does separate full-history scan — heavier, gated by config flag).
- Risk: LOW (read-only static analysis; no network egress except git clone).
- Docker image: `osa-agent-sourcecode:latest`.

**Agent registry update:**
- `_DOMAIN_AGENTS = {"application": ApplicationAgent, "web": WebAgent, "cloud_azure": CloudAzureAgent, "source_code": SourceCodeAgent}`
- Public API exposes domain agent types only; tool agents are internal implementation detail.

### 5.5 Hierarchical Orchestrator + Blackboard

- `app/orchestrator/blackboard.py` — `Blackboard(session_id)` async-safe, asyncio.Lock-backed. Methods: `write(key, value, observed_version=None) -> int (new version)`; `read(key=None) -> dict|list`; `subscribe() -> AsyncIterator[BlackboardEvent]`. Versions monotonic per session.
- `app/orchestrator/sub_orchestrator.py` — `SubOrchestrator(session_id, target, domain_agent, blackboard, db)`. `run()` runs domain agent's plan_steps loop, writes findings + observations to blackboard, listens for cancellation.
- `app/orchestrator/master.py` (refactor of v2.1 `service.py`) —
  - Replaces sequential `for step in steps`.
  - Loads project + targets (multi).
  - For each target, instantiate domain_agent and SubOrchestrator.
  - `asyncio.gather(*subs, return_exceptions=True)` with semaphore = project's concurrency_limit.
  - Concurrent supervisor task: every 500ms, batch blackboard events → if Claude rate-limit allows, replan (Claude given full blackboard summary) → broadcast plan updates via WS.
  - Final report aggregation reads from blackboard.
- Existing safety chain (whitelist, allowlist, risk filter, audit, egress) stays at master level — unchanged contract.

### 5.6 Health Check Agent

- `app/agents/health.py` — `HealthCheckAgent` runs as long-lived asyncio task started on FastAPI lifespan startup.
- Cycle (default 30s, configurable via `settings.health_check_interval_seconds`):
  1. `db` — `SELECT 1` round-trip latency
  2. `docker` — `client.ping()` latency
  3. `claude_api` — light prompt to `claude-haiku-4-5-20251001` (cheap) on a sampled basis (every 10th cycle = 5min) to avoid cost
  4. `agent_<type>` — Docker image presence check via `client.images.get(image)` for each registered domain agent
  5. `websocket` — internal counter of active connections, healthy if < 1000
  6. `disk` — `psutil.disk_usage('/')` percent used
  7. `memory` — `psutil.virtual_memory()` percent used
- Each check: capture latency, status (healthy/degraded/unhealthy with thresholds), persist to `health_checks` table, publish to internal `health` event bus.
- Admin WS endpoint `/ws/admin/health` broadcasts latest cycle results.
- Frontend `pages/Health.tsx` (admin only) shows current matrix + 24h history sparkline per subsystem.

### 5.7 Collaboration UI Backend

- `app/services/comments.py` — CRUD; supports project/session/finding scope; threads via `parent_comment_id`; soft-delete (admin can purge).
- `app/api/v1/comments.py` — REST endpoints; WS `/ws/projects/{id}/comments` for realtime push.
- `app/services/activity.py` — `ActivityTimeline.list(project_id, limit, before)` returns reverse-chronological merged events; subscribers via existing `event_bus`.
- `app/api/v1/activity.py` — REST endpoint for project timeline.
- All session/finding/comment/state-change events synthesize an `activity_events` row via a single helper called from the relevant write paths.

### 5.8 Frontend (React)

**New pages:**
- `pages/ProjectHub.tsx` — replaces `ProjectDetail.tsx`. Tabs: Overview / Targets / Sessions / Findings / Comments / Timeline. Shows multi-target list with target_type badges + status; "Launch Session" supports per-target selection.
- `pages/CampaignView.tsx` — multi-session campaign monitor for a project. Grid of small `SessionCard`s showing live progress; click drills into single-session monitor.
- `pages/Health.tsx` (admin) — health matrix with 24h sparklines, click to drill into history.
- `pages/CredentialManager.tsx` (admin) — credentials CRUD.

**New components:**
- `components/CommentThread.tsx` — threaded comments with WS subscription.
- `components/FindingAnnotation.tsx` — inline note popover on a finding.
- `components/ActivityTimeline.tsx` — vertical timeline per project with WS event push.
- `components/TargetCard.tsx` — per-target type icon, scope summary, concurrency.
- `components/HealthMatrix.tsx` — subsystem grid with color status.

**Updated:**
- `pages/Projects.tsx` — list now shows multi-target counts + active campaign indicator.
- `pages/Monitor.tsx` — when launched from CampaignView, breadcrumb shows campaign context; otherwise unchanged.
- `App.tsx` routes: `/projects/:id` → ProjectHub; `/projects/:id/campaign` → CampaignView; `/admin/health` → Health; `/admin/credentials` → CredentialManager.

### 5.9 API Surface (additions)

| Method | Path | Description | Auth |
|---|---|---|---|
| POST | `/api/v1/projects/{id}/targets` | Add target with target_type + scope_rules | member |
| PATCH | `/api/v1/projects/{id}/targets/{tid}` | Update target | member (owner) |
| DELETE | `/api/v1/projects/{id}/targets/{tid}` | Remove target | member (owner) |
| POST | `/api/v1/sessions/{id}/approvals` | Grant priv-esc approval for a paused session | member (owner) |
| GET, POST, DELETE | `/api/v1/credentials/...` | Credential CRUD | admin |
| GET, POST | `/api/v1/projects/{id}/comments` | List/create comments | member |
| GET | `/api/v1/projects/{id}/activity` | Project activity timeline | member |
| GET | `/api/v1/admin/health` | Latest health snapshot | admin |
| GET | `/api/v1/admin/health/history` | 24h history per subsystem | admin |
| WS | `/ws/projects/{id}/comments` | Realtime comments | member |
| WS | `/ws/projects/{id}/activity` | Realtime activity events | member |
| WS | `/ws/admin/health` | Realtime health updates | admin |

### 5.10 Documentation

- `docs/architecture-v3.md` — supersedes README architecture diagram; explains hierarchical orchestrator + blackboard.
- `docs/safety-v3.md` — new safety guards: AzureScopeValidator, ApprovalGate, SecretScrubber.
- `docs/credentials.md` — operator guide for Azure SP + GitHub PAT registration; least-privilege checklist.
- `docs/health.md` — health agent semantics, thresholds, operator runbook for each unhealthy subsystem.
- Update `README.md` quick-start to include credential setup and multi-target example.

---

## 6. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Azure priv-esc bursts out of scope | Medium-High | Critical | Per-session approval gate + AzureScopeValidator + Service Principal least-privilege checklist |
| Blackboard race / replan thrash | Medium | Medium | asyncio.Lock + versioned writes (CAS) + 500ms arbitration tick |
| Credential leak via logs | Medium | Critical | SecretScrubber on all log/audit/event paths + adapter command lint |
| Refactor breaks 85 existing tests | High | High | Adapter internalization preserves entry points; CI runs full suite per PR; staged migrations |
| Docker images bloat (Azure ~3GB, msf ~2GB) | High | Low | Lazy pull, separate image registry, document size in deployment guide |
| Health agent itself becomes overload source | Low | Medium | 30s default + Claude check sampled at 1/10; resource limits on agent containers checked, not full exec |
| Concurrent sub-orchestrator failure cascades | Medium | Medium | `asyncio.gather(return_exceptions=True)` + per-sub error boundaries + master never crashes on sub failure |
| Comment spam / activity flood | Low | Low | WS rate limit per user (10 msg/s), DB write batching for activity events |
| Multi-target whitelist confusion (per-target vs project) | Medium | Medium | UI displays effective scope clearly; default is "no override = inherit project default" but per-target whitelist always wins; integration test enforces |
| Credential master key loss = all encrypted creds dead | Low | High | Document key backup procedure; admin-only key rotation flow (not in MVP, but documented as Phase-2 follow-up); refusal-to-start guards against silent misconfig |

---

## 7. Acceptance Criteria (Testable, supersedes v2.1's 14)

1. All v2.1 acceptance criteria continue to pass (no regression).
2. Project supports adding ≥ 4 targets with distinct `target_type` values (application/web/cloud_azure/source_code).
3. Per-target `scope_rules` enforced independently; project-level rules treated as default fallback.
4. Multi-domain session runs sub-orchestrators in parallel up to `concurrency_limit` (default 3); excess queued.
5. CloudAzureAgent privilege-escalation step requires explicit approval; without it, step blocks and session pauses with `awaiting_approval` status.
6. Approval recorded in `approval_grants` and audit log; resumed session executes priv-esc step within 5s.
7. CredentialStore round-trip: encrypt→persist→decrypt yields exact plaintext; admin role required for CRUD.
8. SecretScrubber removes bearer tokens / JWT / Azure SAS / AWS keys / GitHub PAT from all WS events, audit logs, finding outputs (regex test fixture coverage ≥ 30 patterns).
9. SourceCodeAgent clones a public Git repo (depth=1) and produces findings from Semgrep + Trivy + gitleaks, normalized to common finding schema.
10. CloudAzureAgent ScoutSuite read-only audit produces ≥ 1 normalized finding for a known-misconfigured test tenant fixture.
11. HealthCheckAgent runs every 30s ± 2s; emits 6+ subsystem checks per cycle; persisted to `health_checks`.
12. HealthCheckAgent posts WS event to `/ws/admin/health` within one cycle of state transition.
13. Admin Health page shows current matrix + 24h sparkline.
14. ActivityTimeline aggregates events from sessions + findings + comments + state changes + approvals + health alerts in correct reverse-chronological order; supports `before` cursor pagination.
15. CommentService supports project / session / finding scopes + threading via `parent_comment_id`; realtime WS push within 1s.
16. CampaignView shows live status of all sessions in a project; clicking a session navigates to single-session Monitor.
17. Concurrent multi-domain session against test fixture (web acme-test.com / azure mock subscription / git public repo / app 127.0.0.1) completes within 25 minutes and produces a unified report covering all 4 domains.
18. Existing test suite (85 tests) plus new tests (≥ 80 additional) all pass; coverage on safety/orchestrator modules ≥ 85%.

---

## 8. ADR (Architecture Decision Record)

### Decision
Refactor v2.1 into a **hierarchical multi-agent platform**: domain-based agents (Application/Web/Cloud-Azure/Source-Code) wrapping internalized tool adapters, coordinated by a master orchestrator over a session-scoped shared blackboard, with extended safety chain (Azure scope, approval gate, secret scrubber), encrypted credential storage, multi-target projects, project-level collaboration UI (comments + finding annotations + activity timeline + campaign view), and a dedicated periodic health agent.

### Drivers
1. New domain coverage requirement (Azure incl. priv-esc, source code) demands per-domain expertise that doesn't fit the v2.1 tool-flat structure.
2. Multi-target single-project requirement breaks v2.1's single-whitelist-per-project assumption; needs per-target scope.
3. Operator demand for collaboration + history + campaign view requires schema additions and realtime UI surfaces v2.1 lacks.
4. Health monitoring requirement creates a new agent class with monitoring-only privilege boundary — distinct from attack agents.

### Alternatives Considered
- **Celery worker pool** — rejected: contradicts v2.1's monolithic ADR + over-engineered for current scale.
- **Microservice per domain** — rejected: explicit "All-in-one MVP" decision.
- **Reactive blackboard without hierarchy** — rejected: user explicitly chose Hierarchical.
- **External secret manager (Vault / Key Vault)** — rejected: adds infra dependency; chose AES-GCM at-rest with master key.

### Why Chosen
Hierarchical + blackboard preserves v2.1's monolithic deployability while introducing the agent autonomy and parallelism the new domains need. AES-GCM at-rest meets the credential-protection bar without forcing an external secret manager (which can be a Phase-2 migration). All-in-one Phase-1 matches the operator's explicit completeness preference; sequencing (schema → safety → agents → orchestration → UI → health) keeps tests green continuously.

### Consequences
- (+) Domain agents scale independently to new tools without orchestrator changes.
- (+) Multi-target campaigns become natural; concurrency limit per project is a single dial.
- (+) Privilege escalation is a first-class safety concern with audit + UI flow.
- (-) Refactor blast radius is large — single biggest delivery risk.
- (-) Master key for credential encryption becomes a critical secret with its own management burden.
- (-) Docker image inventory grows (~3GB Azure image, plus existing msf 2GB); deployment doc must call this out.

### Follow-ups
- Phase-2: migrate blackboard to Redis pub/sub once concurrent multi-target sessions exceed 10 sustained.
- Phase-2: external secret manager (Vault or Azure Key Vault) integration; key rotation flow.
- Phase-2: AWS / GCP cloud agents (mirror CloudAzureAgent pattern).
- Phase-2: PR/diff source-code mode (GitHub App integration).
- Phase-2: cross-project executive dashboard.

---

## Changelog
- v3.0 (2026-05-10): Planner draft. Integrates deep-interview Round 1-3 decisions: domain agents replace tool agents, hierarchical orchestrator with shared blackboard, full Azure scope incl. priv-esc, Git+SAST source code agent, encrypted credential storage, multi-target projects, full collab UI, dedicated health agent, all-in-one MVP. Awaiting Architect review.
