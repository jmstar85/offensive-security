# Offensive Security Agent Platform — Consensus Plan

**Source:** Deep Interview Spec (ambiguity: 14.5%)
**Mode:** Consensus (Deliberate — security domain)
**Iteration:** 2 (post-Architect review)

---

## RALPLAN-DR Summary

### Principles
1. **Safety-First Autonomy:** Full-auto execution is only acceptable when bounded by layered safety guards (whitelist, risk filter, kill switch, audit log)
2. **Plugin Extensibility:** Agent integration must follow an adapter pattern so new tools can be added without modifying core orchestration logic
3. **Separation of Concerns:** AI orchestration (Claude API), agent execution (Docker), data persistence (PostgreSQL), and UI (React) are cleanly decoupled services
4. **Auditability:** Every action taken by the system must be traceable — legal compliance requires complete audit trails
5. **Incremental Delivery:** 7-phase implementation allows each layer to be tested independently before integration

### Decision Drivers (Top 3)
1. **Security Boundary Enforcement:** The platform executes real exploits — incorrect scoping or missing safety guards creates legal liability. This is the #1 architectural driver.
2. **Docker Container Orchestration Complexity:** 4 different tools with different interfaces (CLI, API, Python SDK) must be uniformly managed. The agent adapter abstraction is critical.
3. **Real-time Monitoring Fidelity:** Consultants must see live progress of autonomous attacks. WebSocket streaming from Docker containers must be reliable and low-latency.

### Viable Options

#### Option A: Monolithic FastAPI Backend (Recommended)
**Approach:** Single FastAPI application handles API, orchestration, Docker management, and WebSocket streaming.
**Pros:**
- Simpler deployment (one backend process + workers)
- Shared SQLAlchemy session/models — no inter-service communication overhead
- Faster MVP delivery — fewer moving parts
- Docker SDK calls are direct from the orchestrator
**Cons:**
- Orchestrator and API share the same process — long-running pentest sessions could affect API responsiveness
- Scaling requires replicating the entire backend, not individual components
- Tight coupling between orchestration logic and API layer

#### Option B: Microservices (FastAPI API + Celery Workers + Redis)
**Approach:** FastAPI serves API only. Celery workers handle Docker orchestration and agent execution. Redis for task queue and pub/sub.
**Pros:**
- Orchestration runs in separate worker processes — API stays responsive
- Celery provides built-in retry, rate limiting, and task monitoring
- Better horizontal scaling for concurrent pentest sessions
- Redis pub/sub can feed WebSocket streams cleanly
**Cons:**
- Adds Redis + Celery as infrastructure dependencies
- More complex deployment (API + workers + Redis + beat scheduler)
- Celery task serialization adds latency and debugging complexity
- Over-engineered for MVP with likely <10 concurrent sessions

#### Invalidation of Other Alternatives
- **Go/Rust backend:** Rejected — Python ecosystem has the best integration with security tools (python-nmap, pymetasploit3, PyRIT is Python-native). Rewriting in Go would require shell-exec wrappers for every tool.
- **Serverless (Lambda):** Rejected — Pentest sessions are long-running (minutes to hours), Docker containers can't run inside Lambda, and the platform needs persistent WebSocket connections.
- **No-code/low-code platform:** Rejected — The AI orchestration and Docker container management require custom code that no-code tools can't provide.

### Decision
**Option A (Monolithic FastAPI)** with `asyncio.create_task()` + `ThreadPoolExecutor` for Docker SDK calls (NOT `BackgroundTasks` — see Architect review). Docker blocking I/O runs in a thread pool via `loop.run_in_executor()`, while WebSocket and kill-switch handlers remain on the main async loop. This prevents event loop starvation during concurrent sessions. If concurrent session count exceeds ~10, migrate orchestration to Celery workers (Option B) as a Phase 2 optimization.

---

## Pre-Mortem (Deliberate Mode — 3 Failure Scenarios)

### Scenario 1: Docker Container Escape / Unscoped Attack
**What goes wrong:** A misconfigured agent container escapes its network sandbox or the whitelist validator has a bypass, causing the platform to attack targets outside the authorized scope.
**Likelihood:** Medium (Docker network isolation is well-understood but easily misconfigured)
**Impact:** Critical — Legal liability, potential criminal charges
**Mitigation:**
- Docker containers run with `--network=none` by default; only the agent runner creates a restricted network with explicit IP whitelisting via iptables rules
- Whitelist validation happens at THREE layers: (1) orchestrator pre-plan, (2) agent runner pre-execution, (3) Docker network-level firewall rules
- All outbound connections from agent containers are logged and auditable
- Integration test: attempt to reach non-whitelisted IP from inside container → must fail

### Scenario 2: Claude API Generates Dangerous Attack Plan
**What goes wrong:** The LLM generates an attack plan that includes destructive exploits (e.g., `rm -rf`, ransomware deployment, DoS amplification) that the risk filter fails to catch because the exploit is described in a novel way.
**Likelihood:** Medium (LLM outputs are inherently unpredictable)
**Impact:** High — Data destruction on client systems
**Mitigation:**
- Risk filter uses an allowlist approach (not blocklist): only pre-approved exploit categories/modules are executable
- Metasploit module execution is restricted to a curated whitelist of module paths
- Nuclei templates are pre-vetted; only templates with severity < critical are auto-executed
- Any exploit not in the allowlist requires explicit human approval (breaks full-auto for novel attacks)
- Claude API system prompt includes strict boundaries and the plan is validated against the allowlist before execution

### Scenario 3: WebSocket Connection Loss During Active Pentest
**What goes wrong:** The consultant loses WebSocket connection during an active penetration test. Without monitoring, they can't observe what's happening or trigger the kill switch. The pentest continues running unsupervised.
**Likelihood:** High (network interruptions are common)
**Impact:** Medium — Loss of oversight during active attack
**Mitigation:**
- Server-side session timeout: if no client heartbeat for 60 seconds, auto-pause the session (stop spawning new agent tasks, let running ones complete)
- Kill switch is also available via REST API (not just WebSocket) — curl command works as backup
- All agent actions continue to be logged regardless of client connection
- On reconnect, full session state is restored from DB (not WebSocket history)
- Optional: email/Slack notification on session state changes

---

## Expanded Test Plan (Deliberate Mode)

### Unit Tests
| Component | Test | Acceptance |
|-----------|------|------------|
| WhitelistValidator | Reject IP outside range | 100% of out-of-scope IPs rejected |
| WhitelistValidator | Accept IP inside range | CIDR notation, single IP, domain all pass |
| RiskFilter | Block high-risk Metasploit modules | DoS, ransomware, wiper modules blocked |
| RiskFilter | Allow low/medium risk modules | Approved scanner/enum modules pass |
| AgentAdapter (Nmap) | Parse nmap XML output | Hosts, ports, services correctly extracted |
| AgentAdapter (Nuclei) | Parse nuclei JSON output | Findings with severity, CVE, URL extracted |
| AgentAdapter (Metasploit) | Parse msfrpc response | Session, loot, vulnerability data extracted |
| AgentAdapter (PyRIT) | Parse PyRIT results | AI red team findings extracted |
| Orchestrator | Generate plan from prompt | Structured plan with agents, order, targets |
| AuditLogger | Log all actions | Every orchestrator decision logged with timestamp |

### Integration Tests
| Scenario | Test | Acceptance |
|----------|------|------------|
| Auth flow | Register → Login → Token refresh → Protected endpoint | JWT lifecycle works |
| Project CRUD | Create → Read → Update → Delete project | All CRUD operations succeed |
| Agent lifecycle | Start container → Execute → Stream logs → Stop → Remove | Full Docker lifecycle |
| Orchestrator pipeline | Prompt → Plan → Agent selection → Mock execution | End-to-end orchestration logic |
| Safety chain | Prompt with out-of-scope IP → Rejection | Whitelist blocks before execution |
| Kill switch | Start session → Kill switch → All containers stopped | < 5 second stop time |
| WebSocket | Connect → Receive updates → Disconnect → Reconnect | State recovery on reconnect |

### E2E Tests
| Scenario | Test | Acceptance |
|----------|------|------------|
| Full pipeline | Login → Create project → Prompt → Auto execution → Monitor → Report | All 14 acceptance criteria pass |
| Safety demo | Attempt out-of-scope attack → Blocked | Whitelist + risk filter both trigger |
| Kill switch demo | Start scan → Press kill switch → All stops | UI kill switch works within 5s |
| Report generation | Complete session → View dashboard → Download PDF | PDF contains all findings |
| Concurrent sessions | 5 projects running simultaneously | No cross-contamination of results, kill switch responsive < 5s |

### Observability
| Signal | Implementation | Alert Threshold |
|--------|---------------|-----------------|
| Agent container CPU/memory | Docker stats API → metrics | > 80% memory for > 60s |
| WebSocket connection count | FastAPI middleware counter | Active connections spike > 100 |
| Orchestrator decision latency | Audit log timestamps | Claude API call > 30s |
| Agent execution duration | DB session records | Any agent running > 30 min |
| Safety guard triggers | Audit log events | Any whitelist/risk rejection |
| Docker daemon health | Periodic health check | Daemon unreachable |

---

## Implementation Plan

### Phase 1: Project Scaffolding & Database (Foundation)
1. Initialize monorepo: `backend/`, `frontend/`, `docker/`, `docs/`
2. FastAPI project with async SQLAlchemy + Alembic
3. PostgreSQL schema (11 tables from ontology):
   - `users` (id, email, password_hash, role, team_id)
   - `teams` (id, name, created_at)
   - `projects` (id, name, client_name, target_description, status, created_by)
   - `targets` (id, project_id, ip_ranges[], domains[], cloud_provider, whitelist_rules)
   - `pentest_sessions` (id, project_id, prompt, plan_json, status, started_at, ended_at)
   - `agent_executions` (id, session_id, agent_type, container_id, status, config_json, output_json, started_at, ended_at)
   - `attack_scenarios` (id, session_id, steps_json, risk_assessment)
   - `reports` (id, session_id, summary, findings_json, risk_score, pdf_path, created_at)
   - `audit_logs` (id, timestamp, actor_id, action, target_entity, details_json)
   - `agent_registry` (id, name, docker_image, capabilities[], risk_level, enabled)
4. Alembic initial migration
5. Docker Compose: postgres:16, backend (FastAPI), frontend (Vite dev)
6. `.env` configuration, `pyproject.toml`, health check endpoints

**Key files:**
- `backend/app/models/*.py` — SQLAlchemy models
- `backend/app/core/config.py` — Settings via pydantic-settings
- `backend/app/core/database.py` — Async engine + session
- `backend/alembic/versions/001_initial.py`
- `docker-compose.yml`

### Phase 2: Auth & Project Management
1. JWT auth: register, login, token refresh, password hashing (passlib + bcrypt)
2. Auth middleware: dependency injection for current_user
3. Project CRUD API with target whitelist management
4. Target validation: IP range parsing (ipaddress module), domain validation
5. React setup: Vite + TypeScript + TailwindCSS + React Router
6. Pages: Login, Register, Dashboard, Project List, Project Create/Detail

**Key files:**
- `backend/app/api/v1/auth.py` — Auth endpoints
- `backend/app/api/v1/projects.py` — Project CRUD
- `backend/app/api/v1/targets.py` — Target/whitelist management
- `backend/app/core/security.py` — JWT + password utilities
- `frontend/src/pages/{Login,Dashboard,Projects}.tsx`
- `frontend/src/api/client.ts` — Axios/fetch API client

### Phase 3: Agent Infrastructure (Docker)
1. Dockerfiles for 4 agents:
   - `docker/nmap/Dockerfile` — Alpine + nmap + python-nmap output wrapper
   - `docker/nuclei/Dockerfile` — Go binary + default templates + JSON output
   - `docker/metasploit/Dockerfile` — Kali base + msfrpcd + pymetasploit3
   - `docker/pyrit/Dockerfile` — Python 3.12 + pyrit-core + pyrit-target
2. Agent adapter abstract base class + ExecutionBackend abstraction (Architect feedback — enables non-Docker agents in future):
   ```python
   class ExecutionBackend(ABC):
       """How to run: Docker, native process, or remote API"""
       async def start(self, config) -> str  # returns execution_id
       async def stream_logs(self, execution_id) -> AsyncGenerator[str]
       async def stop(self, execution_id) -> None
       async def cleanup(self, execution_id) -> None

   class DockerBackend(ExecutionBackend): ...
   class ProcessBackend(ExecutionBackend): ...  # future: native Python agents

   class AgentAdapter(ABC):
       """What to run: agent-specific logic"""
       agent_type: str
       backend: ExecutionBackend
       async def build_command(self, target: Target, config: dict) -> list[str]
       async def execute(self, target: Target, config: dict) -> AsyncGenerator[AgentEvent]
       async def parse_output(self, raw_output: str) -> AgentResult
       def get_capabilities(self) -> list[str]
       def get_risk_level(self) -> RiskLevel
   ```
3. Concrete adapters: NmapAdapter, NucleiAdapter, MetasploitAdapter, PyRITAdapter
4. DockerRunner service: container create → start → log stream → stop → remove
   - **Container resource limits (Architect feedback):** All containers created with `--memory=512m`, `--cpus=1.0`, `--pids-limit=100`, `--read-only` (where possible). Metasploit gets `--memory=2g`, `--cpus=2.0` due to larger footprint.
   - Docker SDK calls run via `loop.run_in_executor(thread_pool)` to prevent event loop starvation
   - **Metasploit RPC auth (Architect feedback):** `MetasploitAdapter` generates per-session random RPC passwords via `secrets.token_urlsafe(32)`, passed to `msfrpcd` at container start
5. Agent registry: DB-backed + in-memory cache of available agents

**Key files:**
- `backend/app/agents/base.py` — AgentAdapter ABC + ExecutionBackend ABC
- `backend/app/agents/backends/docker.py` — DockerBackend implementation
- `backend/app/agents/{nmap,nuclei,metasploit,pyrit}.py` — Concrete adapters
- `backend/app/agents/runner.py` — DockerRunner (docker-py SDK, ThreadPoolExecutor)
- `backend/app/agents/registry.py` — Agent discovery and registration
- `docker/{nmap,nuclei,metasploit,pyrit}/Dockerfile`

### Phase 4: AI Orchestrator + Safety Guards
1. Claude API client (Anthropic Python SDK, streaming)
2. Orchestrator service:
   - `analyze_target(prompt) -> TargetAnalysis` — NLP → structured target info
   - `create_plan(analysis) -> AttackPlan` — Agent selection + execution order
   - `execute_plan(plan) -> AsyncGenerator[SessionEvent]` — Run agents per plan
3. Safety guard chain (executed in order):
   - `WhitelistValidator` — Reject any target IP/domain not in project whitelist
   - `RiskAssessor` — Score the plan's risk level (low/medium/high/critical)
   - `RiskFilter` — Block critical-risk actions, warn on high-risk
   - `ExploitAllowlist` — Only pre-approved Metasploit modules/Nuclei templates executable
4. Kill switch service: `stop_session(session_id)` → stop all running containers for session
5. Audit logger middleware: log every orchestrator decision to `audit_logs` table
6. **Runtime Egress Monitor (Architect feedback):** Sidecar-style component that tails Docker container network logs during execution and cross-references outbound connections against the whitelist in real-time. On violation → auto-trigger kill switch + audit log alert. This closes the gap between plan-time validation and execution-time enforcement (critical for Metasploit post-exploitation lateral movement).
7. **Claude API rate limiter:** Token bucket rate limiting on prompt submissions (max 5 per minute per user) to prevent cost runaway and rapid re-prompting that bypasses human review cadence.

**Key files:**
- `backend/app/orchestrator/service.py` — Main orchestrator
- `backend/app/orchestrator/planner.py` — Claude API → attack plan
- `backend/app/orchestrator/executor.py` — Plan execution engine (uses `asyncio.create_task()` + `ThreadPoolExecutor` for Docker SDK calls)
- `backend/app/safety/whitelist.py` — IP/domain whitelist validator
- `backend/app/safety/risk_filter.py` — Risk assessment + filtering
- `backend/app/safety/exploit_allowlist.py` — Approved module registry
- `backend/app/safety/kill_switch.py` — Emergency stop
- `backend/app/safety/egress_monitor.py` — Runtime outbound connection monitoring
- `backend/app/safety/audit.py` — Audit logging

### Phase 5: Real-time Monitoring (WebSocket)
1. FastAPI WebSocket endpoint: `/ws/sessions/{session_id}`
2. Event types: `agent_started`, `agent_log`, `agent_completed`, `agent_failed`, `session_update`, `safety_alert`
3. Server-side event bus: orchestrator → WebSocket broadcast
4. Client heartbeat + auto-reconnect + state recovery from DB
5. React monitoring page: session timeline, agent status cards, live log viewer, kill switch button
6. Session auto-pause on client disconnect (60s timeout)

**Key files:**
- `backend/app/api/v1/ws.py` — WebSocket endpoint
- `backend/app/core/events.py` — Event bus (asyncio)
- `frontend/src/pages/Monitor.tsx` — Monitoring dashboard
- `frontend/src/hooks/useWebSocket.ts` — WS hook with reconnect
- `frontend/src/components/{AgentCard,LogViewer,KillSwitch,Timeline}.tsx`

### Phase 6: Reporting
1. Report generator: aggregate agent outputs → structured findings
2. Finding model: vulnerability, severity (CVSS), affected asset, evidence, remediation
3. Risk score calculation: weighted by severity × exploitability
4. Web report view: summary dashboard, findings table, severity charts
5. PDF generation (WeasyPrint): HTML template → styled PDF with findings, evidence, recommendations
6. Report API: list, detail, PDF download

**Key files:**
- `backend/app/reports/generator.py` — Aggregate findings
- `backend/app/reports/pdf.py` — WeasyPrint PDF generation
- `backend/app/reports/templates/report.html` — PDF HTML template
- `backend/app/api/v1/reports.py` — Report API endpoints
- `frontend/src/pages/Reports.tsx` — Report dashboard
- `frontend/src/pages/ReportDetail.tsx` — Single report view

### Phase 7: Integration Testing & Demo
1. Pytest test suite: unit + integration + safety tests
2. Test fixtures: mock Docker containers, mock Claude API responses
3. Vulnerable test target: Docker container running intentionally vulnerable services (e.g., DVWA, Metasploitable3)
4. E2E demo script: full pipeline walkthrough
5. Documentation: API docs (FastAPI auto-generated), deployment guide, safety guide

**Key files:**
- `backend/tests/unit/test_safety.py`
- `backend/tests/unit/test_agents.py`
- `backend/tests/integration/test_pipeline.py`
- `backend/tests/e2e/test_full_flow.py`
- `docker/targets/Dockerfile` — Vulnerable test target
- `docs/deployment.md`, `docs/safety.md`

---

## Safety Architecture

```
User Prompt
    │
    ▼
[1. Rate Limiter] ──throttle──> "Too many requests"
    │ pass
    ▼
[2. Whitelist Validator] ──reject──> "Error: Target out of scope"
    │ pass
    ▼
[3. Claude API: Generate Plan]
    │
    ▼
[4. Risk Assessor] ──score──> low/medium/high/critical
    │
    ▼
[5. Exploit Allowlist] ──block──> "Blocked: Unapproved module"
    │ pass
    ▼
[6. Risk Filter] ──block critical──> "Blocked: Critical risk"
    │ pass              ──warn high──> "Warning logged"
    ▼
[7. Agent Execution (Docker, ThreadPoolExecutor)]
    │
    ├──[Kill Switch]──> Stop all containers + log
    ├──[Egress Monitor]──> Real-time outbound connection check vs whitelist
    │       └──violation──> Auto-kill + alert
    │
    ▼
[8. Results + Report]
    │
    ▼
[9. Audit Log] (records steps 1-8)
```

---

## Acceptance Criteria (Testable)
1. `POST /api/v1/auth/login` returns JWT token with valid credentials (< 500ms)
2. `POST /api/v1/projects` creates project with target whitelist
3. `POST /api/v1/sessions` with natural language prompt returns attack plan within 30s
4. Attack plan includes at least 2 of 4 agents (Nmap, Nuclei, Metasploit, PyRIT)
5. Docker containers for selected agents start within 30s of plan approval
6. WebSocket at `/ws/sessions/{id}` streams agent events within 1s of occurrence
7. `POST /api/v1/sessions/{id}/kill` stops all containers within 5s
8. Prompt with out-of-scope IP returns 403 with whitelist violation error
9. Metasploit execution restricted to allowlisted modules only
10. `GET /api/v1/reports/{id}` returns structured findings with CVSS scores
11. `GET /api/v1/reports/{id}/pdf` returns downloadable PDF
12. `GET /api/v1/audit-logs?session_id={id}` returns complete action history
13. Full pipeline (prompt → execution → report) completes within 15 minutes on test target
14. Five concurrent sessions run without data cross-contamination (Architect: test at 5-8, not just 2)

---

## Risks and Mitigations
| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Container escape / unscoped attack | Medium | Critical | Triple-layer whitelist (orchestrator + runner + Docker network) |
| LLM generates dangerous plan | Medium | High | Exploit allowlist (not blocklist), plan validation |
| Metasploit Docker image too large | High | Low | Pre-build, cache in registry, lazy pull |
| Claude API latency/downtime | Medium | Medium | Streaming responses, graceful degradation, retry with backoff |
| WebSocket disconnection | High | Medium | Auto-pause, REST kill switch backup, DB state recovery |
| Docker daemon overload | Low | Medium | Container resource limits (CPU, memory, time) |
| Legal compliance violation | Low | Critical | Audit logs, whitelist enforcement, terms of service |

---

## ADR (Architecture Decision Record)

### Decision
Monolithic FastAPI backend with async Docker orchestration, 4 security tool agents in Docker containers, Claude API for autonomous planning, triple-layer safety guard chain, and WebSocket real-time monitoring.

### Drivers
1. Security boundary enforcement is the #1 priority — safety guards must be layered and defense-in-depth
2. Python ecosystem provides the best integration with security tools (python-nmap, pymetasploit3, PyRIT)
3. MVP speed — monolithic architecture minimizes infrastructure complexity

### Alternatives Considered
- **Microservices (Celery + Redis):** Better scalability but over-engineered for MVP; clear migration path exists
- **Go backend:** Higher performance but poor security tool ecosystem integration
- **Serverless:** Incompatible with long-running pentest sessions and Docker containers

### Why Chosen
Monolithic FastAPI delivers the fastest MVP while the async architecture handles concurrent sessions adequately for the initial use case (<10 concurrent). The triple-layer safety architecture addresses the critical security boundary risk without adding infrastructure complexity. Python's native integration with all 4 target tools eliminates shell-exec wrappers.

### Consequences
- (+) Fastest path to working MVP
- (+) Single deployment unit simplifies operations
- (+) Direct Docker SDK access from orchestrator
- (-) Must migrate to Celery workers if concurrent sessions exceed ~10
- (-) API responsiveness may degrade during heavy orchestration

### Follow-ups
- Monitor concurrent session count; if >10 sustained, migrate to Celery
- Evaluate Kubernetes deployment when scaling beyond single-host Docker
- Consider adding Burp Suite, OWASP ZAP, or Nikto as plugin agents
- Implement RBAC when multi-tenant support is needed

---

## Changelog
- v1.0: Initial plan from deep-interview spec (14.5% ambiguity)
- v2.0: Architect review incorporated:
  - Replaced `BackgroundTasks` with `asyncio.create_task()` + `ThreadPoolExecutor` for Docker SDK calls
  - Added runtime Egress Monitor to safety chain (closes plan-time vs execution-time gap)
  - Added container resource limits (`--memory`, `--cpus`, `--pids-limit`)
  - Added `ExecutionBackend` abstraction below `AgentAdapter` for plugin extensibility
  - Added Metasploit per-session RPC authentication
  - Added Claude API rate limiter (5 req/min/user)
  - Increased concurrent session test from 2 to 5
- v2.1: Critic APPROVED. Fixed E2E test table consistency (2→5 concurrent sessions). Minor items noted for executor: egress monitor capture mechanism choice, secrets management.
