# OSA Platform v3 — Iteration 2 (Revised after Architect + Critic Review)

**Status:** Iteration 2/5 — addresses Architect 3 principle violations + 5 defects + Critic 2 CRITICAL + 4 MAJOR + 4 MINOR
**Companion:** v3.0 base plan at `offensive-security-agent-consensus-v3.md` — sections not amended below remain in force unchanged.
**Locked decisions (deep-interview, not relitigated):** Domain agents replace tool agents; Hierarchical Orchestrator + Blackboard; Azure full scope incl. priv-esc; Source-code via Git URL; Multi-target single project; Per-target scope_rules; Collab UI (4 components); Dedicated periodic Health agent; All-in-one MVP; Encrypted credentials at-rest; Parallel default with concurrency limit; Internalize tool agents.

---

## Iteration-2 Revisions Map

| # | Source | Finding | Resolution Section |
|---|---|---|---|
| ARC-1 | Architect Antithesis | Blackboard lock contention | §A. Blackboard Hybrid |
| ARC-2 | Architect Tradeoff | AzureScopeValidator: ARM-only blind to data-plane | §B. Azure Scope (split) |
| ARC-3 | Architect PV-1 | SecretScrubber positioning too late | §C. Secret Scrubber (two interception points) |
| ARC-4 | Architect PV-2 | Refactor breaks 85 existing test imports | §D. Re-export shims |
| ARC-5 | Architect PV-3 | HealthCheckAgent privilege boundary, Claude cost | §E. Health Agent revised |
| ARC-6 | Architect Defect-1 | asyncio.Lock not cancellation-atomic | §A. Blackboard Hybrid (CoW) |
| ARC-7 | Architect Defect-2 | EgressMonitor IP-only regex | §B. Azure Scope (DNS interception) |
| ARC-8 | Architect Defect-3 | ApprovalGate no TTL / no plan_version | §F. Approval Gate (versioned + TTL) |
| ARC-9 | Architect Defect-4 | Session-level EgressMonitor wrong for multi-target | §G. Per-Sub EgressMonitor |
| ARC-10 | Architect Defect-5 | HealthCheckAgent rate-limit collision | §E. Health Agent revised |
| CRI-C1 | Critic CRITICAL | Pause/resume mechanism unspecified | §H. Pause-Resume Lifecycle |
| CRI-C2 | Critic CRITICAL | Replan loop infinite cycle | §I. Replan Termination |
| CRI-M1 | Critic MAJOR | Target schema migration breaks fixtures | §J. Migration 003 revised |
| CRI-M2 | Critic MAJOR | Frontend backward compat for POST /projects | §K. API Backward Compat |
| CRI-M3 | Critic MAJOR | WebSocket explosion 4× endpoints | §L. WS Multiplexing |
| CRI-M4 | Critic MAJOR | concurrency_limit on targets vs project | §J. Migration 003 revised |
| CRI-Min1 | Critic minor | Comment thread depth | §M. Minor refinements |
| CRI-Min2 | Critic minor | PII scrubbing not in MVP | §M. Minor refinements |
| CRI-Min3 | Critic minor | activity_events scaling | §M. Minor refinements |
| CRI-Min4 | Critic minor | Health agent uses orchestrator's Claude model | §E. Health Agent revised |
| CRI-AC | Critic | Vague AC items 3, 14, 17 | §N. AC Clarifications |
| CRI-PRE | Critic | Missing pre-mortem 4, 5 | §O. Pre-Mortem Additions |
| CRI-TST | Critic | Missing tests: cancellation cascade, migration ordering, replan termination, frontend BC | §P. Test Plan Additions |

---

## §A. Blackboard Hybrid (Replaces v3.0 §5.5 Blackboard subsection)

The Blackboard becomes a **two-region structure** to eliminate the v3.0 lock-contention concern:

```python
class Blackboard:
    """Session-scoped coordination surface.

    Region 1 (per-sub append-only): Sub-orchestrators write findings/observations
    to their own per-sub list. No cross-sub lock needed for appends.

    Region 2 (master control dict): Master writes control signals (cancel,
    pause, replan_directive, awaiting_approval). Single asyncio.Lock guards.

    Reads: Master reads Region 2 + tails of all Region 1 lists in one tick.
    """
    def __init__(self, session_id: uuid.UUID, sub_ids: list[str]) -> None:
        self._session_id = session_id
        self._sub_lists: dict[str, list[Event]] = {sid: [] for sid in sub_ids}  # append-only per sub
        self._control: dict = {}                                                 # mutable, master writes
        self._control_lock = asyncio.Lock()
        self._version = 0  # monotonic; equals sum of all sub list lengths + control writes

    def sub_append(self, sub_id: str, event: Event) -> int:
        """Sub-orchestrator path. No lock — single-list append in CPython is atomic."""
        self._sub_lists[sub_id].append(event)
        # version bump is best-effort; stale-version reads are acceptable for findings
        self._version += 1
        return self._version

    async def control_set(self, key: str, value: Any) -> int:
        """Master path. Copy-on-write under lock to survive cancellation."""
        async with self._control_lock:
            new = {**self._control, key: value}  # build outside-then-assign
            self._control = new                   # single-assignment, atomic
            self._version += 1
            return self._version

    def snapshot(self) -> BlackboardSnapshot:
        """Master arbitration tick path. Read all subs + control in one pass."""
        return BlackboardSnapshot(
            sub_events={sid: list(events) for sid, events in self._sub_lists.items()},
            control=dict(self._control),
            version=self._version,
        )
```

**Cancellation safety:** `control_set` builds the new dict outside the lock-managed mutation, then performs a single assignment. If cancelled mid-`control_set`, the lock is released by `__aexit__`, and `self._control` either holds the prior dict or the new dict — never a half-mutated state. Sub appends are CPython-atomic single-element list appends.

**Cross-sub control delivery:** When Master writes `_control["cancel"] = True`, sub-orchestrators check this on every `await` boundary and self-cancel. Implemented via a `Blackboard.cancellation_requested(sub_id) -> bool` query the sub polls, plus an `asyncio.Event` per sub for prompt wake-up.

**Updated unit tests (replaces v3.0 §3 Blackboard tests):**
- `Blackboard.sub_append` 10 subs × 100 events concurrent → all 1000 appended, monotonic version
- `Blackboard.control_set` cancellation in flight → control dict is either old or new, never mid-write
- `Blackboard.snapshot` consistency → snapshot taken concurrently with appends sees ≥ snapshot.version events
- `Blackboard.cancellation_requested` → master sets cancel → all subs return True within 1 await tick

---

## §B. Azure Scope Validation (Split — Adapter + Master DNS)

Replaces v3.0 §5.2 AzureScopeValidator paragraph and §5.2 EgressMonitor extension paragraph.

### §B.1 Adapter-Level: `AzureArmScopeValidator`
- Lives in `app/agents/domain/cloud_azure_validators.py`
- Used inside `CloudAzureAgent` only, before any tool execution that touches ARM
- Extracts `subscription_id` / `tenant_id` / `resource_group` from ARM resource IDs the tool will operate on (e.g., for ScoutSuite: parse the SP's listed subscriptions; refuse if any not in scope)
- Pre-execution gate: tool config (subscription list, resource graph queries) is rewritten to match scope_rules; out-of-scope subscriptions are stripped before tool invocation
- Output post-processor: re-validates findings reference only in-scope resources; flags any out-of-scope finding as a safety event (does not silently drop)

### §B.2 Master/Network-Level: `AzureEndpointClassifier` extension to `EgressMonitor`
Acknowledges that data-plane Azure calls bypass ARM and have no resource ID structure.

```python
class AzureEndpointClassifier:
    """Classifies Azure hostnames against scope_rules."""
    AZURE_HOSTS = {
        # data plane (no ARM resource ID — must validate by hostname)
        r"([a-z0-9]+)\.blob\.core\.windows\.net":  "storage_account",
        r"([a-z0-9-]+)\.vault\.azure\.net":         "key_vault",
        r"graph\.microsoft\.com":                   "ms_graph",
        # control plane (has ARM resource ID in URL path — caller extracts from request body)
        r"management\.azure\.com":                  "arm_control",
        r"login\.microsoftonline\.com":             "auth",
    }
    def classify(self, hostname: str) -> tuple[str, str | None]:
        ...

class EgressMonitor:  # extended
    HOSTNAME_PATTERN = re.compile(r"\b([a-z0-9-]+\.[a-z0-9.-]+\.(com|net|io|cloud))\b", re.I)

    async def monitor_log_line(self, line: str, actor_id: str) -> bool:
        # existing IP check stays — handles direct-IP egress
        for ip_match in CONNECTION_PATTERN.finditer(line):
            if not self._is_allowed_ip(ip_match.group(1)):
                return await self._violate(ip_match.group(1), line, actor_id)
        # new hostname check — handles azure / github / cloud SaaS
        for host_match in self.HOSTNAME_PATTERN.finditer(line):
            host = host_match.group(1).lower()
            kind, key = self._azure_classifier.classify(host)
            if kind == "storage_account" and key not in self._allowed_storage_accounts:
                return await self._violate(host, line, actor_id)
            if kind == "key_vault" and key not in self._allowed_key_vaults:
                return await self._violate(host, line, actor_id)
            if kind == "ms_graph" and not self._allow_ms_graph:
                return await self._violate(host, line, actor_id)
        return True
```

### §B.3 DNS-level interception (defense in depth)
Each agent container's Docker network is created with a custom resolver (`--dns 127.0.0.1` pointing to a per-container CoreDNS instance) that **only resolves** allowlisted hostnames. Any A/AAAA query for a non-allowlisted name returns NXDOMAIN. This is a complementary mechanism — log-line parsing is best-effort detection, DNS gating is preventive.

- New file: `app/agents/backends/dns_resolver.py` — generates per-session CoreDNS Corefile from `scope_rules`
- Container creation in `DockerBackend.start()` extended to mount Corefile and set `--dns`

**New tests:**
- `AzureEndpointClassifier.classify` for all 5 Azure host patterns
- `EgressMonitor.monitor_log_line` with line containing `*.blob.core.windows.net` of out-of-scope storage account → violation triggers kill
- `DnsResolver.generate_corefile` from sample scope_rules → resolves whitelisted, refuses others (integration test using actual CoreDNS container)
- Document explicitly in §safety-v3.md: data-plane scope guarantee is **best-effort log + DNS** (not authoritative ARM-level).

---

## §C. Secret Scrubber (Two Interception Points)

Replaces v3.0 §5.2 SecretScrubber paragraph.

`SecretScrubber.scrub(text: str) -> str` — pure function. **Two interception points**, NOT one:

### §C.1 Log-capture interception (BEFORE event_bus.publish)
File: `app/orchestrator/sub_orchestrator.py` (and `app/orchestrator/executor.py` for backward-compat shim).

```python
# inside SubOrchestrator.run() / PlanExecutor.execute() — replaces current line at executor.py:73-74
async for event in adapter.execute(target, config, container_id_holder):
    if event.event_type == "log":
        raw_line = event.data.get("line", "")
        scrubbed = SecretScrubber.scrub(raw_line)               # ← scrub HERE
        event = AgentEvent("log", event.agent_type, event.execution_id, {"line": scrubbed})
    # ...rest of existing flow unchanged; event_bus.publish receives already-scrubbed event
```

### §C.2 Audit log persistence interception
File: `app/safety/audit.py`.

```python
class AuditLogger:
    async def log(self, action: str, actor_id: str, target_entity: str,
                  target_id: str, details: dict) -> None:
        scrubbed_details = SecretScrubber.scrub_dict(details)   # ← scrub HERE before persist
        # ...persist as today
```

`SecretScrubber.scrub_dict` recursively walks dict/list, scrubs string leaves.

### §C.3 Pattern coverage
File: `app/safety/secret_scrubber.py`. Patterns (compiled `re`, all case-insensitive where applicable):
- Bearer tokens: `(?i)Bearer\s+[A-Za-z0-9._\-]+`
- JWT: `eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}`
- Azure SAS: `\?sv=\d{4}-\d{2}-\d{2}&[A-Za-z0-9&=%]+sig=[A-Za-z0-9%]+`
- AWS keys: `AKIA[0-9A-Z]{16}` / `aws_secret_access_key\s*=\s*[A-Za-z0-9/+=]{30,}`
- GitHub PAT: `gh[ousp]_[A-Za-z0-9]{36,}` / `github_pat_[A-Za-z0-9_]{82}`
- Generic high-entropy near keyword: `(?i)(secret|password|token|api[_-]?key)["':=\s]+[A-Za-z0-9+/=_-]{20,}`
- Replacement format: `[REDACTED:{type}]` (e.g., `[REDACTED:bearer]`, `[REDACTED:jwt]`)

**False-positive bound test:** 1000 random 200-char texts → 0 matches.
**False-negative test:** Each pattern type → 30+ realistic samples → 100% match.

---

## §D. Tool Adapter Re-export Shims (Refactor preserves 85 tests)

Replaces v3.0 §5.4 last paragraph.

**File moves:**
- `app/agents/nmap.py` → `app/agents/_tools/nmap.py` (and same for nuclei, metasploit, pyrit)

**Re-export shims at original paths** to preserve `from app.agents.nmap import NmapAdapter` imports:

```python
# app/agents/nmap.py  (now a 2-line shim)
"""Backward-compat shim. New code should import from app.agents._tools.nmap."""
from app.agents._tools.nmap import NmapAdapter, *  # noqa: F401, F403
```

Same shim pattern for nuclei.py, metasploit.py, pyrit.py.

**Registry preservation:**
- `app/agents/registry.py` `_ADAPTERS` keeps old keys (`nmap`/`nuclei`/`metasploit`/`pyrit`) — used by current tests
- New domain registry separate: `app/agents/domain/registry.py` `_DOMAIN_AGENTS`
- v3.0 §5.4's "tool agents are internal implementation detail" amended: tool agent **classes** internalized; **import paths** preserved via shims; **adapter names in registry** preserved.

**Verification:** `pytest tests/unit/test_agents.py` runs unchanged after refactor; CI gate.

---

## §E. Health Check Agent (Revised)

Replaces v3.0 §5.6.

### §E.1 Privilege boundary
- Runs as asyncio task in main FastAPI process (same as v3.0) — but **no access to `CredentialStore`**.
- The Health agent's module does not import `app.services.credentials` and is unit-tested to assert this import is absent (`grep -L credentials app/agents/health.py`).
- For Docker image presence checks, uses `DockerBackend.images_present(image_names)` which reads `client.images.get` only — never starts a container.
- Privilege documented in `docs/health.md`.

### §E.2 Claude probe — separate rate-limit + cost cap
- Health agent's Claude probe uses **separate rate-limit bucket** from orchestrator. New config: `settings.health_claude_probe_max_per_hour: int = 12` (default = once per 5 min, 12/hr cap regardless of cycle frequency).
- New config: `settings.health_claude_probe_model: str = "claude-haiku-4-5-20251001"` (separate from orchestrator's `anthropic_model`).
- Daily cost projection documented in `docs/health.md`: 288 probes/day × ~50 input + 30 output tokens = 23k tokens/day on Haiku ≈ $0.02/day ≈ $0.60/month per deployment.
- Probe disabled if `health_claude_probe_max_per_hour == 0` (operator can opt out).

### §E.3 Cycle structure unchanged from v3.0 §5.6 except:
- Step 3 (Claude probe) wrapped in `RateLimiter.try_acquire("health_claude")`; on rate-limit miss, returns `degraded` with reason `"rate_limited"`, NOT calls Claude.
- Step 4 (agent images) iterates registered domain agents (`_DOMAIN_AGENTS.keys()`), not tool agents — health is about the public surface.

### §E.4 Resource use bound
- Each cycle has a 25s wall-clock budget; if exceeded, partial results persisted with `cycle_timeout=true` flag.
- Tests: simulate slow `psutil.disk_usage` → cycle terminates within 25s, partial results recorded.

---

## §F. Approval Gate (Versioned + TTL)

Replaces v3.0 §5.2 ApprovalGate paragraph.

### §F.1 Schema (revises Migration 004)
```sql
CREATE TABLE approval_grants (
    id              UUID PRIMARY KEY,
    session_id      UUID NOT NULL REFERENCES pentest_sessions(id),
    plan_version    INT NOT NULL,                     -- blackboard version when step was proposed
    step_hash       CHAR(64) NOT NULL,                -- sha256 of (agent, action, config) — binds approval to step content
    action_class    VARCHAR(64) NOT NULL,             -- "privilege_escalation" | future
    granted_by      UUID NOT NULL REFERENCES users(id),
    granted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL DEFAULT (now() + INTERVAL '1 hour'),
    consumed_at     TIMESTAMPTZ NULL,                 -- set when ApprovalGate.use() succeeds
    UNIQUE (session_id, step_hash, plan_version)
);
CREATE INDEX idx_approval_session_unconsumed
    ON approval_grants(session_id) WHERE consumed_at IS NULL;
```

### §F.2 Gate logic
```python
class ApprovalGate:
    async def require(self, session_id: UUID, step: dict, plan_version: int) -> None:
        step_hash = hashlib.sha256(
            json.dumps([step["agent"], step["action"], step.get("config", {})], sort_keys=True).encode()
        ).hexdigest()
        action_class = self._classify(step)  # returns "privilege_escalation" or None
        if action_class is None:
            return  # no approval needed
        result = await self._db.execute(
            select(ApprovalGrant).where(
                ApprovalGrant.session_id == session_id,
                ApprovalGrant.step_hash == step_hash,
                ApprovalGrant.plan_version == plan_version,
                ApprovalGrant.consumed_at.is_(None),
                ApprovalGrant.expires_at > func.now(),
            )
        )
        grant = result.scalar_one_or_none()
        if not grant:
            raise ApprovalRequired(action_class=action_class, step_hash=step_hash, plan_version=plan_version)
        # mark consumed atomically
        await self._db.execute(
            update(ApprovalGrant).where(ApprovalGrant.id == grant.id).values(consumed_at=func.now())
        )
```

**Replan invalidation guarantee:** Because step_hash includes `plan_version`, any replan that produces different step content (or even the same content at a different version) requires fresh approval. Stale approvals expire at 1h regardless.

**TTL configurable:** `settings.approval_ttl_seconds: int = 3600`.

### §F.3 New tests:
- Approval matches → consumed → second use blocked (already consumed)
- Approval expired → rejected with `expired_at` detail
- Replan changes step config → step_hash differs → old approval invalid
- Replan keeps same step but plan_version increments → approval invalid (forces re-approval per plan version, conservative)

---

## §G. Per-Sub EgressMonitor (Multi-target whitelist correctness)

Replaces v3.0 §5.5 final paragraph (which incorrectly inherited the v2.1 session-level monitor pattern).

```python
# app/orchestrator/sub_orchestrator.py
class SubOrchestrator:
    def __init__(self, session_id, target, domain_agent, blackboard, db):
        self._target = target
        self._egress = EgressMonitor(
            session_id=session_id,
            scope_rules=target.scope_rules,                     # ← per-target, not per-session
            azure_classifier=AzureEndpointClassifier(target.scope_rules),
        )
        # ...
```

Master no longer holds a session-level EgressMonitor; safety enforcement is delegated to each SubOrchestrator with its target's scope.

**v2.1 backward-compat:** for legacy single-target projects (target_type=`web` only, one target), behavior identical to v2.1 — single SubOrchestrator with single EgressMonitor. Test `test_pipeline.py` continues to pass.

**New test:** Project with 2 targets (in-scope `acme.com` and out-of-scope `evil.com`); two subs run; only sub for `acme.com` allows acme traffic; both subs reject any cross-target leakage.

---

## §H. Pause-Resume Lifecycle (CRITICAL — addresses Critic C1)

**New section. Defines the concrete asyncio mechanism for ApprovalGate-induced pause and the corresponding session-status state machine.**

### §H.1 State machine
```
pending ─▶ running ─▶ awaiting_approval ─▶ running ─▶ completed
                            │                    │
                            └─▶ approval_timeout │
                                  (after 30 min) │
                                       ▼         ▼
                                    failed     killed (operator)
```

### §H.2 Mechanism — `asyncio.Event` per sub-orchestrator
```python
class SubOrchestrator:
    def __init__(self, ...):
        self._approval_event = asyncio.Event()
        self._approval_pending: ApprovalRequired | None = None

    async def run(self):
        for step in self._domain_agent.plan_steps(...):
            try:
                await self._approval_gate.require(self._session_id, step, self._plan_version)
            except ApprovalRequired as exc:
                self._approval_pending = exc
                # write to blackboard so master + UI see it
                await self._blackboard.control_set(f"awaiting_approval:{self._sub_id}", {
                    "step_hash": exc.step_hash,
                    "action_class": exc.action_class,
                    "deadline": (datetime.now(UTC) + timedelta(seconds=settings.approval_wait_timeout_seconds)).isoformat(),
                })
                await self._db.execute(
                    update(PentestSession).where(PentestSession.id == self._session_id)
                    .values(status="awaiting_approval")
                )
                # SUSPEND — wait for approval API to call self.notify_approved() OR timeout
                try:
                    await asyncio.wait_for(
                        self._approval_event.wait(),
                        timeout=settings.approval_wait_timeout_seconds,  # default 1800s
                    )
                    self._approval_event.clear()
                    self._approval_pending = None
                    # retry the step now that approval grant exists
                    await self._approval_gate.require(self._session_id, step, self._plan_version)
                except asyncio.TimeoutError:
                    # approval did not arrive — fail this sub gracefully, do not crash master
                    await self._blackboard.sub_append(self._sub_id, Event("approval_timeout", step))
                    return  # exits sub cleanly; master sees timeout via blackboard
            await self._execute_step(step)

    def notify_approved(self) -> None:
        """Called by POST /api/v1/sessions/{id}/approvals after row inserted."""
        self._approval_event.set()
```

### §H.3 Docker container lifecycle during pause
- Sub-orchestrator that hits ApprovalGate has not yet started any container for the pending step (gate fires pre-execution by design).
- Containers from previous steps already cleaned up by `adapter.cleanup()` in their normal flow.
- No leaked Docker resources.

### §H.4 Master behavior during pause
- Master's `asyncio.gather(*subs)` continues. Subs that are not awaiting approval continue running.
- Master arbitration tick observes `awaiting_approval:*` keys in blackboard control region; broadcasts to UI via WS.
- Kill switch (operator) cancels the entire `gather` group — paused subs receive cancellation and exit cleanly without consuming the pending grant.
- Project-level approval timeout setting: `settings.approval_wait_timeout_seconds: int = 1800` (30 min).

### §H.5 API support
- `POST /api/v1/sessions/{id}/approvals` body: `{"step_hash": ..., "plan_version": ...}`. Inserts `approval_grants` row, then calls `OrchestratorRegistry.notify_approval(session_id, sub_id, step_hash)` which fans out to the live sub-orchestrator's `_approval_event`.
- `OrchestratorRegistry` is a process-local singleton mapping `session_id → list[SubOrchestrator]` for in-flight sessions.
- If the orchestrator process restarts mid-pause, on startup the lifespan recovers `awaiting_approval` sessions: marks them as `failed` with reason `"orchestrator_restart_during_approval"` (no fragile coroutine state recovery in MVP).

### §H.6 Tests
- Approval arrives within timeout → step executes; consumed_at set
- Approval does not arrive within `approval_wait_timeout_seconds` → sub exits cleanly, blackboard records timeout, master continues with other subs
- Operator kills session during pause → all subs cancelled including paused; no half-consumed grants
- Two simultaneous pauses (Cloud-Azure priv-esc + nested rare case) → both pause independently, approvals delivered separately

---

## §I. Replan Termination (CRITICAL — addresses Critic C2)

**New section. Bounds master's replan loop with three stop conditions.**

### §I.1 Stop conditions (any one terminates replanning)
1. **Replan count cap:** `settings.max_replans_per_session: int = 10`. Master keeps a counter; replan #11 is refused — master proceeds to finalize with current findings.
2. **Token budget cap:** `settings.max_claude_tokens_per_session: int = 50000`. Master tracks cumulative input+output tokens via Anthropic SDK response. Exceeded → no further replans.
3. **Convergence detection:** if 3 consecutive replans produce a plan whose step set hash matches the previous (no new steps added), master concludes convergence and stops replanning. Sub-orchestrators continue executing the existing plan; master simply stops calling Claude.

### §I.2 Implementation
```python
class MasterOrchestrator:
    async def supervisor_loop(self):
        replan_count = 0
        token_budget = settings.max_claude_tokens_per_session
        last_plan_hashes: deque[str] = deque(maxlen=3)
        while not self._all_subs_done():
            await asyncio.sleep(0.5)
            snapshot = self._blackboard.snapshot()
            if not self._has_new_observations(snapshot):
                continue
            if replan_count >= settings.max_replans_per_session:
                continue
            if token_budget <= 0:
                continue
            new_plan, tokens_used = await self._claude_replan(snapshot)
            replan_count += 1
            token_budget -= tokens_used
            plan_hash = self._hash_plan(new_plan)
            if len(last_plan_hashes) == 3 and all(h == plan_hash for h in last_plan_hashes):
                continue  # converged — keep current plan
            last_plan_hashes.append(plan_hash)
            await self._distribute_plan(new_plan)
        await self._finalize()
```

### §I.3 Observability (already in v3.0 §3 obs table; extended here)
- New metric: `replan_count_per_session` (gauge) — exposed in audit log
- New metric: `claude_token_budget_remaining` (gauge per session)
- New alert: replan_count == cap → emit info-level audit event for operator visibility
- Existing alert: blackboard write rate > 100/s sustained 30s — kept

### §I.4 New tests
- Replan loop with synthetic continuous findings (10 cycles) → halts at `max_replans_per_session`
- Token budget exhausted at cycle 3 → replans stop, sub execution continues
- 3 consecutive replans produce same plan_hash → master logs `converged`, stops calling Claude
- Replan cycle never starts if no new observations since last snapshot

---

## §J. Migration 003 Revised + concurrency_limit Resolution

Replaces v3.0 §5.1 003 paragraph and addresses Critic M1 + M4.

### §J.1 New `targets` columns
- `target_type ENUM('application','web','cloud_azure','source_code')` NOT NULL
  - Backfill: legacy rows = `'web'`
- `name VARCHAR(255)` NOT NULL
  - Backfill via SQL: `UPDATE targets SET name = COALESCE('Default Target ' || SUBSTR(id::text, 1, 8))` — guaranteed unique by appending UUID prefix
  - **Unique constraint deferred to Migration 003b** which runs AFTER backfill: `ALTER TABLE targets ADD CONSTRAINT uq_target_project_name UNIQUE (project_id, name)`
  - Two-step migration prevents constraint violation on existing data
- `scope_rules JSONB` — semantics extended (already exists, plan documents new schema)

### §J.2 `concurrency_limit` moved to `projects` table (per-project semantics)
Migration 003 also includes:
```sql
ALTER TABLE projects ADD COLUMN max_concurrent_domains INT NOT NULL DEFAULT 3;
```
Removed from `targets`. Master uses `project.max_concurrent_domains` to size the asyncio.Semaphore wrapping `gather(*subs)`. Per-target throttling (if needed in future) can be added as a separate column without schema reshuffle.

### §J.3 Test fixture updates
v3.0 conftest creates Targets via test fixtures (`tests/conftest.py`). Update fixture:
```python
@pytest_asyncio.fixture
async def sample_target(db_session, sample_project):
    target = Target(
        project_id=sample_project.id,
        target_type="web",                              # ← NEW required field
        name="Default Target",                          # ← NEW required field
        ip_ranges=["192.168.1.0/24"], domains=["test.local"],
        scope_rules={"ip_ranges": [...], "domains": [...]},
    )
    ...
```
Document in `tests/conftest.py` the migration: any test that creates Target objects must provide `target_type` and `name`. CI grep gate: `grep -rn "Target(" tests/ | grep -v target_type` returns zero results.

### §J.4 Integration test for migration ordering
- New test `tests/integration/test_migrations.py`: spins up a SQLite DB, applies migrations 001 → 002 → seeds with v2.1-shaped Target rows → applies 003 → 003b → 004 → 005 → 006 → asserts:
  - All legacy targets have `target_type='web'` and `name LIKE 'Default Target %'`
  - Unique constraint passes
  - All v2.1 acceptance criteria queries still work

---

## §K. API Backward Compatibility

**New section. Addresses Critic M2.**

### §K.1 `POST /api/v1/projects` — body shape preserved
Existing body shape (single embedded `target`) **kept as-is**. Internally, the handler:
- Creates the project
- Creates a single Target with `target_type='web'`, `name='Default Target'`, fields from body.target
- Returns the project (legacy response shape)

```python
@router.post("/", response_model=ProjectResponse, status_code=201)
async def create_project(body: ProjectCreate, ...):  # ProjectCreate UNCHANGED from v2.1
    project = Project(...)
    target = Target(
        target_type="web",       # default for legacy single-target body
        name="Default Target",
        ip_ranges=body.target.ip_ranges, domains=body.target.domains, ...
    )
    return ProjectResponse(...)
```

### §K.2 New multi-target endpoint
`POST /api/v1/projects/{id}/targets` body:
```json
{ "target_type": "cloud_azure", "name": "Production Subscription",
  "scope_rules": { "azure_subscriptions": ["..."], "tenants": ["..."] },
  "credential_id": "uuid-or-null" }
```
Adds an additional Target to the project. Project may have N targets after creation.

### §K.3 Existing GET endpoints unchanged
- `GET /api/v1/projects/{id}/targets` returns list (always list — was list before, just typically with 1 element)
- New fields (`target_type`, `name`) appear in responses; **frontend must tolerate unknown fields** (it already does via TypeScript loose interfaces — verified in `frontend/src/api/client.ts`)

### §K.4 Frontend backward-compat regression test
- Spin up backend with v3 schema; run a Playwright test against the deployed v2.1 frontend bundle (cached in `tests/e2e/v2_1_frontend_fixture/`); login + create project + launch session → all v2.1 flows still work.
- Document this as a CI gate.

---

## §L. WebSocket Connection Multiplexing

**New section. Addresses Critic M3.**

### §L.1 Decision: multiplex per-project events
Instead of 3 separate per-project WS endpoints (`comments`, `activity`, plus session-level), **multiplex onto one** per-project WS:
- New endpoint: `/ws/projects/{id}` — single WS per project per browser tab
- Message envelope: `{ "channel": "comments" | "activity" | "session_update", "data": { ... } }`
- Client subscribes once per project; routes by channel field
- Session monitor (`/ws/sessions/{id}`) **kept separate** to preserve v2.1 backward compat for the existing Monitor.tsx page

### §L.2 Connection caps in EventBus
Extend `app/core/events.py`:
```python
class EventBus:
    MAX_TOTAL_SUBSCRIBERS = 200          # global hard cap
    MAX_SUBSCRIBERS_PER_USER = 10        # per JWT subject
    QUEUE_MAXSIZE = 500                   # already exists; documented

    def subscribe(self, topic: str, user_id: str | None = None) -> asyncio.Queue:
        if self._total_count >= self.MAX_TOTAL_SUBSCRIBERS:
            raise WebSocketRejected("server saturated")
        if user_id and self._user_count[user_id] >= self.MAX_SUBSCRIBERS_PER_USER:
            raise WebSocketRejected("per-user limit reached")
        # ...
```

### §L.3 Admin health WS
`/ws/admin/health` kept as separate endpoint (admin-only, low cardinality).

### §L.4 Tests
- Open 11 WS as same user → 11th rejected with `4002 per_user_limit`
- Open 201 total WS across users → 201st rejected with `4003 saturated`
- Project-level multiplexed WS: subscribe → receive comment + activity + session_update events on same socket; client demuxes correctly

---

## §M. Minor Refinements

### §M.1 Comment thread depth (Critic Min1)
- Hard cap: `max_thread_depth = 5`. Enforced in CommentService.create — 6th-level reply rejected with HTTP 400 `"thread depth exceeded"`.
- UI flattens deeper-than-3 replies with a "show in thread view" link.

### §M.2 PII in findings (Critic Min2)
Documented as an out-of-scope MVP concern. Add `docs/safety-v3.md#pii-scope` section: SecretScrubber covers credentials only; finding outputs may contain client PII (IPs of test users, emails in API responses). Operators are responsible for redaction before sharing reports externally. Phase-2 follow-up: add `PiiScrubber` with email / phone / SSN patterns and per-project consent flags.

### §M.3 activity_events scaling (Critic Min3)
- Document as scaling concern in `docs/architecture-v3.md`.
- Add monthly-partition scaffolding in Migration 005 comments (not enabled at MVP, but partition functions documented).
- Default retention: 90 days; daily prune job via `scripts/prune_activity.py`.

### §M.4 Health agent uses its own model config (Critic Min4)
Already addressed in §E.2 above (`settings.health_claude_probe_model` separate from `settings.anthropic_model`).

---

## §N. Acceptance Criteria Clarifications

Replaces ambiguous AC items 3, 14, 17 in v3.0 §7.

- **AC 3 (revised):** "Per-target `scope_rules` are enforced independently. **Resolution rule:** if a target's `scope_rules` is non-empty, it is used **exclusively** for that sub-orchestrator (project default is NOT merged). If a target's `scope_rules` is empty/null, the project's default `scope_rules` (stored on a future `projects.default_scope_rules` column, MVP: stored on the first/only target if legacy) is used."
- **AC 14 (revised):** "ActivityTimeline returns events in `created_at DESC` order; ties broken by `id DESC`. Cursor pagination via `before=<created_at>` returns up to `limit` (default 50, max 200) events strictly older than the cursor."
- **AC 17 (revised):** "Concurrent multi-domain session against test fixture (web target: `acme-test.local` HTTP nginx in docker / Azure target: **mock SDK responses** via `azure-mock` test fixture image / Git target: in-tree `tests/fixtures/sample-vulnerable-repo` / app target: `127.0.0.1` MetasploitableLite docker) completes within **20 minutes wall-clock** (image pulls excluded — assumed pre-pulled). Note: real Azure tenant E2E is a Phase-2 demo, not a CI gate."

### §N.1 Additional ACs (new)
- **AC 19:** Master replan loop terminates within `max_replans_per_session` (default 10) replans OR `max_claude_tokens_per_session` (default 50k) OR convergence (3 identical plan hashes), whichever first. Test: continuous-findings fixture → halts at correct condition.
- **AC 20:** Approval grant honored within 5s of POST /approvals; expired approvals rejected; `step_hash` mismatch rejected. Test: TTL boundary, hash mismatch, double-consume.
- **AC 21:** Multi-target session with 2 targets + scope_rules differing — egress monitor rejects cross-target contamination. Integration test required.
- **AC 22:** v2.1 frontend bundle (cached) connects successfully to v3 backend; original 14 ACs still pass. CI E2E gate.

---

## §O. Pre-Mortem Additions

### §O.4 Scenario 4: Master Replan Infinite Cycle (NEW — addresses Critic CRI-PRE)

**What goes wrong:** Cloud-Azure sub-orchestrator scans a misconfigured tenant with 200+ public storage accounts. Each batch of findings triggers a master replan. Claude generates new sub-steps. New steps execute, find more issues, write to blackboard. Master sees new observations every tick, calls Claude again. Token budget consumed within 3 minutes. Without termination, the loop continues until rate limit or process kill.

**Likelihood:** **High** — any real Azure tenant scan generates dozens to hundreds of findings.
**Impact:** High — Claude API cost runaway ($10s-$100s per session), unbounded execution time, operator forced to use kill switch.

**Mitigation:** §I (max_replans_per_session=10, max_claude_tokens_per_session=50k, convergence detection over 3 ticks). Operator alert when limit hit.

### §O.5 Scenario 5: Approval Gate Stuck Open / Timeout (NEW — addresses Critic CRI-PRE)

**What goes wrong:** Cloud-Azure sub hits priv-esc step → emits ApprovalRequired. Operator with admin rights is unavailable; approval never arrives. Sub-orchestrator's `await self._approval_event.wait()` hangs indefinitely. asyncio task held alive holding sub_id slot. Other domains complete; session stuck in `awaiting_approval` for hours.

**Likelihood:** Medium — common in async consultant workflows where approver is across timezones.
**Impact:** Medium — resource leak (asyncio task + Docker network reservations + DB session marker stuck).

**Mitigation:** §H (asyncio.wait_for with `approval_wait_timeout_seconds=1800`). On timeout: sub exits cleanly with `approval_timeout` event; session moves to `failed` (or `partially_completed` if other domains succeeded). Operator can re-launch with explicit approval pre-staged.

---

## §P. Test Plan Additions

### §P.1 New unit tests (in addition to v3.0)
| Component | Test | Acceptance |
|---|---|---|
| `Blackboard.control_set` | Cancellation mid-write → atomic | Final state is old or new, never partial |
| `Blackboard.cancellation_requested` | Master cancel propagates | Within 1 await tick |
| `MasterOrchestrator.supervisor_loop` | Replan cap honored | Halts at `max_replans_per_session` |
| `MasterOrchestrator.supervisor_loop` | Token budget honored | Halts when budget exhausted |
| `MasterOrchestrator.supervisor_loop` | Convergence detection | 3 identical plan hashes → stops calling Claude |
| `ApprovalGate.require` | step_hash mismatch on replan | Old approval invalid |
| `ApprovalGate.require` | TTL expiry | Expired grant rejected |
| `SubOrchestrator.run` | Approval timeout path | Sub exits cleanly, blackboard records timeout |
| `SubOrchestrator.notify_approved` | Event set wakes sub | Step executes within 5s |
| `EgressMonitor.AzureEndpointClassifier` | All 5 host patterns classified | 100% pattern coverage |
| `EgressMonitor.monitor_log_line` | Out-of-scope storage account | Triggers violation |
| `SecretScrubber.scrub` | Pre-publish scrubbing | Raw line never reaches event_bus |
| `EventBus.subscribe` | Per-user limit | 11th subscription rejected |
| `EventBus.subscribe` | Global limit | 201st subscription rejected |
| `CredentialStore.never_logged` | Full-trace assertion | Plaintext never in audit/event/finding |
| `HealthCheckAgent` | No CredentialStore import | Static check via grep |
| `HealthCheckAgent.claude_probe` | Rate limit honored | 13th probe in 1h returns degraded(rate_limited) |

### §P.2 New integration tests
| Scenario | Test | Acceptance |
|---|---|---|
| Cancellation cascade | Master kill → all subs stop within 5s | Includes paused subs |
| Multi-target whitelist | 2 targets with disjoint scopes | No cross-contamination |
| Migration ordering | Apply 001-006 to v2.1-shape data | All v2.1 acceptance queries succeed |
| Frontend BC | Cached v2.1 frontend ↔ v3 backend | All v2.1 flows pass |
| Approval E2E | POST /approvals during paused session | Sub resumes within 5s |
| Approval timeout | No POST /approvals within 30 min | Sub exits cleanly, session = failed |
| Replan loop runaway sim | Synthetic continuous findings fixture | Halts within 10 replans |

### §P.3 New observability signals
| Signal | Implementation | Threshold |
|---|---|---|
| `replan_count` per session | counter | warn at 8, alert at 10 |
| `claude_token_budget_remaining` | gauge | alert at <10k remaining |
| `approval_pending_seconds` | gauge per pending grant | warn at 1500s, alert at 1800s |
| `ws_subscribers_per_user` | gauge | alert at 9 (1 below cap) |
| `ws_total_subscribers` | gauge | alert at 180 (10% headroom) |

---

## §Q. Exception-Path Secret Scrubbing (Iteration-3 fix — Architect NEW-3)

`executor.py:96-106` writes `{"error": str(exc)}` to both `output_json` (DB) and `event_bus.publish` outside the C.1 log-loop. Azure SDK and msfrpc exceptions can embed bearer tokens / SP secrets in their messages. **Required fix:**

```python
# In SubOrchestrator (replaces executor.py:91-106 in v3.1's revised structure)
except Exception as exc:
    scrubbed_error = SecretScrubber.scrub(str(exc))            # ← scrub HERE
    await self._db.execute(
        update(AgentExecution).where(AgentExecution.id == exec_id)
        .values(status="failed", ended_at=datetime.now(UTC),
                output_json={"error": scrubbed_error})           # ← scrubbed before DB write
    )
    await event_bus.publish(str(self._session_id), {
        "type": "agent_failed",
        "agent": agent_type,
        "execution_id": str(exec_id),
        "error": scrubbed_error,                                  # ← scrubbed before broadcast
    })
```

Applies the same scrubber to:
- `update(PentestSession).values(status="failed")` paths in `service.py` / future `master.py`
- Any `details_json={"violations": ...}` in audit log paths (already covered by §C.2 audit scrubber, but verified by NEW unit test)

**New unit test:** `executor.exception_path_scrubs_credentials` — plant a fake bearer token in a mock adapter's exception → assert it never appears in `output_json` row, `agent_failed` WS event, or audit log row.

---

## §R. Deployment Constraint — Single Uvicorn Worker (Iteration-3 fix — Architect NEW-6)

`OrchestratorRegistry` (§H.5) is a process-local in-memory singleton. With multi-worker uvicorn/gunicorn, `POST /approvals` may hit a different worker than the one running the suspended sub-orchestrator, breaking `notify_approved()`.

### §R.1 MVP constraint
- **MVP runs on single uvicorn worker.** Documented in `docs/deployment.md` and enforced via runtime assertion at FastAPI lifespan startup.

### §R.2 Startup assertion
```python
# app/main.py — inside lifespan startup
import os
workers_env = os.environ.get("UVICORN_WORKERS") or os.environ.get("WEB_CONCURRENCY")
if workers_env and int(workers_env) > 1:
    raise RuntimeError(
        "OSA platform requires single uvicorn worker for OrchestratorRegistry "
        "and Health agent correctness. Set UVICORN_WORKERS=1 / WEB_CONCURRENCY=1 "
        "or upgrade to Phase-2 Redis-backed registry."
    )
```

### §R.3 Dockerfile / docker-compose enforcement
- `docker/backend/Dockerfile` CMD locked to `uvicorn ... --workers 1`.
- `docker-compose.yml` backend service env: `UVICORN_WORKERS=1`.
- Production deployment guide warns that Kubernetes Deployments must use 1 replica until Phase-2.

### §R.4 Phase-2 follow-up (documented)
Replace `OrchestratorRegistry` with Redis pub/sub channel + persistent `approval_grants` polling on suspended subs. Allows N-worker scaling.

### §R.5 Test
- Lifespan startup with `UVICORN_WORKERS=2` → fails with the explicit error message.
- Default startup (no env var) → succeeds.

---

## §S. `_has_new_observations` Specification (Iteration-3 fix — Architect NEW-7)

In §I.2 supervisor loop, `self._has_new_observations(snapshot)` is defined as:

```python
def _has_new_observations(self, snapshot: BlackboardSnapshot) -> bool:
    """Returns True iff the snapshot contains observations not seen at last replan."""
    return snapshot.version > self._last_replan_version
```

`self._last_replan_version` initialized to 0 at session start. Updated to `snapshot.version` after each successful Claude replan call. This guarantees:
- Clock skew has no effect (compares monotonic version, not timestamps)
- Convergence detection (§I.1 condition 3) operates on plan content hash, not snapshot version
- A blackboard snapshot taken between two replans with no new sub-events returns False → no Claude call → no token spent

---

## §T. Disposition of LOW-MEDIUM Architect NEW Findings

Brief textual amendments — no structural change.

| Finding | Severity | Disposition |
|---|---|---|
| NEW-1 (version counter under inner sub concurrency) | MED | §A class docstring updated to: "version counter is **advisory**; readers tolerate skew. For authoritative ordering, use `len(sub_events_for_sub_id)` per-sub which is CPython-atomic." |
| NEW-2 (DNS interception per-tool verification) | MED | §B.3 test list extended: per-domain-agent integration test asserts container respects `--dns 127.0.0.1` (test mocks CoreDNS, asserts NXDOMAIN observed in tool stderr for non-allowlisted host). Tools known to bypass system DNS (e.g., specific Go binaries with embedded resolvers) flagged as Phase-2 hardening. |
| NEW-4 (`import *` private helpers) | LOW | §D shim spec amended: shim file uses explicit `from ._tools.nmap import NmapAdapter` (no wildcard) — exports the exact public names tests rely on. CI grep gate already covers this. |
| NEW-5 (replan-same-step UX) | MED | §F documented as Phase-2 UX improvement: "auto-approve identical step on replan with operator-marked 'persistent grant' flag." MVP keeps conservative re-approval. |
| NEW-8 (Alembic separate revisions) | LOW | §J.1 explicitly states: "003 and 003b are **separate Alembic revision files** (`003_multi_target.py` and `003b_target_unique_constraint.py`), each with its own `revision` ID and downgrade. Two transactions." |
| NEW-9 (cloud_provider deprecation) | LOW | §K.1 amended: legacy `cloud_provider='azure'` field on POST /projects body is **silently ignored** (target_type stays 'web'). Frontend deprecation notice added; new flow forces `POST /projects/{id}/targets` with explicit `target_type='cloud_azure'`. Documented in `docs/api-migration.md`. |
| NEW-10 (frontend WS demux) | MED | §L.1 amended with frontend spec: new hook `useProjectWebSocket(projectId)` that maintains 3 separate state slices (`comments`, `activity`, `sessions`) routed by `channel` field; existing `useWebSocket` (single-session) preserved. Add to §5.8 component list. |
| NEW-11 (PII commitment) | LOW | §M.2 amended: explicitly state that report PDF generation is local-only; no auto-distribution; operators must manually send. Phase-2 PiiScrubber and per-project consent-flag committed in follow-up list. |

---

## Iteration-2 + Iteration-3 Changelog
- **v3.1** (2026-05-10): Iteration 2 revisions addressing 23 issues from Architect-1 (10) + Critic-1 (13). Added §A-§P.
- **v3.1.3** (2026-05-10, same session): Iteration 3 textual fixes addressing Architect-2 NEW-1 through NEW-11. Added §Q (exception-path scrubbing), §R (single-worker deployment constraint), §S (`_has_new_observations` spec), §T (LOW-MED disposition). No structural changes — all fixes are textual or 2-line code spec.
- Locked decisions unchanged (deep-interview Round 1-3 results).
- v3.0 base plan retained as authoritative for sections not amended here.
