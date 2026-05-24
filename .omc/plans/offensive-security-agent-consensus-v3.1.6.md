# OSA Platform v3.1.6 — Iteration 6 (Resolves §C 11 MED-LOW ambiguities)

**Status:** Iteration 6 — operational-clarity patch for all 11 MED-LOW items from `PLAN-VERIFICATION-2026-05-10.md` §C.

**Companion docs (read together):**
- v2.1 baseline (implemented): `offensive-security-agent-consensus.md`
- v3.0 base: `offensive-security-agent-consensus-v3.md`
- v3.1+v3.1.3 amendments: `offensive-security-agent-consensus-v3.1.md`
- v3.1.4-rev1 (§A fixes): `offensive-security-agent-consensus-v3.1.4.md`
- v3.1.5-rev3 (§B fixes): `offensive-security-agent-consensus-v3.1.5.md`
- **v3.1.6 (this file):** §C canonical operational clarifications

**Scope:** §C MED-LOW items only. This patch does not change the locked architecture decisions, target type enum, domain-agent split, approval-gate semantics, or CoreDNS isolation model already resolved in v3.1.4/v3.1.5.

---

## §X. Iteration-6 Decision Map

| # | From verification | Resolution location |
|---|---|---|
| C-1 | Health agent Anthropic key boundary unclear | §X.1 |
| C-2 | `cloud_provider` legacy column lifecycle | §X.2 |
| C-3 | `OrchestratorRegistry` lifecycle | §X.3 |
| C-4 | SecretScrubber prose false positives | §X.4 |
| C-5 | `asyncio.gather` + semaphore wiring | §X.5 |
| C-6 | Health agent `domain_agent.docker_image` arity | §X.6 |
| C-7 | v2.1 frontend fixture source | §X.7 |
| C-8 | Comment depth O(N) check | §X.8 |
| C-9 | `activity_events` 90-day prune | §X.9 |
| C-10 | Partial sub-orchestrator failure reporting | §X.10 |
| C-11 | Approval timeout vs grant TTL mismatch | §X.11 |

---

## §X.1 Platform Anthropic key boundary (resolves C-1)

**Decision:** `settings.anthropic_api_key` is **platform-level runtime configuration**, not a user-managed credential. The CredentialStore exclusion in v3.1 §E.1 applies only to per-project / per-target user-supplied credentials (`azure_sp`, `github_pat`, and future operator-provided secrets).

### §X.1.1 Amendment to v3.1 §E.1

Append to §E.1:

> `settings.anthropic_api_key` is read from deployment configuration and is allowed for the Health Check Agent's Claude probe. It MUST NOT be stored in `credentials`, exposed through CredentialManager, bound to targets, or injected into attack-agent containers. Health may import `app.core.config` but still MUST NOT import `app.services.credentials`.

### §X.1.2 Boundary table

| Secret/source | Owner | Stored in CredentialStore? | Health agent access? | Attack-agent container access? |
|---|---|---:|---:|---:|
| `anthropic_api_key` | Platform operator | No | Yes, config-read only | No |
| Azure service principal | Project admin | Yes | No | Yes, only target-bound CloudAzureAgent |
| GitHub PAT | Project admin | Yes | No | Yes, only target-bound SourceCodeAgent |
| `credential_master_key` | Platform operator | No | No | No |

### §X.1.3 Tests

- Health module import test remains: no import of `app.services.credentials`.
- Add `test_health_uses_platform_anthropic_key_only`: monkeypatch `settings.anthropic_api_key`; assert Claude probe reads config directly and CredentialStore mocks are untouched.
- Add `test_attack_agent_env_excludes_anthropic_key`: Docker env builder for all domain agents never contains `ANTHROPIC_API_KEY`.

---

## §X.2 `cloud_provider` legacy column lifecycle (resolves C-2)

**Decision:** keep `projects.cloud_provider` as **deprecated, kept-for-rollback** through MVP. New code must not write it, new UI must not display it, and multi-target cloud behavior is derived exclusively from `targets.target_type='cloud_azure'` and `targets.whitelist_rules` / API `scope_rules`.

### §X.2.1 Amendment to v3.1.4 §V.6 Migration 003

Add a non-operation row to the consolidated column list:

| Table | Operation | Column | Type | Source section |
|---|---|---|---|---|
| `projects` | KEEP | `cloud_provider` | existing nullable legacy column | **§X.2** deprecated, kept-for-rollback; no new writes |

Migration 003 MUST NOT drop `cloud_provider` and MUST NOT backfill it from targets.

### §X.2.2 ORM/API policy

- ORM may retain `Project.cloud_provider` only for legacy read compatibility and rollback.
- `ProjectCreate` legacy body shape remains v3.1 §K.1-compatible; if an old client sends `cloud_provider`, handler ignores it and creates a default `target_type='web'` target unless the new target endpoint is used.
- `ProjectRead` may include `cloud_provider` if already present in v2.1 response models, but v3 frontend treats it as deprecated and does not branch on it.

### §X.2.3 Removal policy

`cloud_provider` removal is deferred to Phase 2 after one release with:
- migration warning in `docs/api-migration.md`
- CHANGELOG deprecation entry
- telemetry / DB query showing no non-null usage in supported deployments

### §X.2.4 Tests

- Migration test: existing non-null `projects.cloud_provider='azure'` survives Migration 003 unchanged.
- Handler test: new multi-target CloudAzure project leaves `projects.cloud_provider` NULL and creates target row with `target_type='cloud_azure'`.
- Grep/typing gate: no new service code uses `project.cloud_provider` for routing.

---

## §X.3 `OrchestratorRegistry` lifecycle (resolves C-3)

**Decision:** `OrchestratorRegistry` is a process-local, weak-reference routing table for in-flight sub-orchestrators. Registration occurs when a sub is constructed for a live session; deregistration occurs in `finally` after `SubOrchestrator.run()` finishes, fails, or is cancelled.

### §X.3.1 Replaces v3.1 §H.5 lifecycle paragraph

```python
class OrchestratorRegistry:
    _subs: dict[UUID, weakref.WeakValueDictionary[UUID, SubOrchestrator]] = defaultdict(
        weakref.WeakValueDictionary
    )

    @classmethod
    def register(cls, session_id: UUID, sub_id: UUID, sub: SubOrchestrator) -> None:
        cls._subs[session_id][sub_id] = sub

    @classmethod
    def deregister(cls, session_id: UUID, sub_id: UUID) -> None:
        bucket = cls._subs.get(session_id)
        if not bucket:
            return
        bucket.pop(sub_id, None)
        if not bucket:
            cls._subs.pop(session_id, None)

    @classmethod
    def notify_approval(cls, session_id: UUID, sub_id: UUID, step_hash: str) -> bool:
        sub = cls._subs.get(session_id, {}).get(sub_id)
        if not sub or not sub.is_awaiting(step_hash):
            return False
        sub.notify_approved()
        return True
```

### §X.3.2 SubOrchestrator integration

```python
class SubOrchestrator:
    def __init__(self, session_id: UUID, sub_id: UUID, ...):
        self._session_id = session_id
        self._sub_id = sub_id
        OrchestratorRegistry.register(session_id, sub_id, self)

    async def run(self) -> DomainRunResult:
        try:
            return await self._run()
        finally:
            OrchestratorRegistry.deregister(self._session_id, self._sub_id)
```

`weakref.WeakValueDictionary` is a leak guard, not the primary lifecycle mechanism. Correct code still deregisters explicitly.

### §X.3.3 Restart semantics

Registry is not durable. Existing v3.1 §H.5 restart rule remains: on FastAPI lifespan startup, sessions stuck in `awaiting_approval` are marked failed with reason `orchestrator_restart_during_approval`.

### §X.3.4 Tests

- Successful sub run deregisters.
- Exception in sub run deregisters.
- Cancellation during approval wait deregisters.
- `notify_approval` for a deregistered or wrong `sub_id` returns `False` and does not raise.
- Leak test: after a completed session and `gc.collect()`, registry has no bucket for that session.

---

## §X.4 SecretScrubber prose false-positive guard (resolves C-4)

**Decision:** keep generic high-entropy detection, but gate it with a regression corpus to prevent normal prose from being redacted merely because it contains security-related words.

### §X.4.1 Amendment to v3.0 §5.2 SecretScrubber tests

Add `tests/safety/test_secret_scrubber_false_positive_corpus.py`:

```python
PROSE_NEGATIVE_CORPUS = [
    "The secret password policy requires rotation every 90 days.",
    "This report mentions bearer tokens but does not include one.",
    "Operators should store credentials in the vault, not in comments.",
    # 97 more real English sentences from docs, reports, and UI copy
]

def test_prose_corpus_has_zero_false_positive_redactions():
    scrubber = SecretScrubber()
    for sentence in PROSE_NEGATIVE_CORPUS:
        assert scrubber.scrub(sentence) == sentence
```

Corpus requirements:
- At least 100 sentences.
- Must include benign uses of: `secret`, `password`, `token`, `credential`, `key`, `bearer`, `authorization`, `client_secret`.
- Must include long but natural words / hyphenated phrases / UUID-looking prose examples that are not actual secrets.

### §X.4.2 Positive corpus preserved

The existing positive fixture coverage remains mandatory:
- bearer tokens
- JWT
- Azure SAS
- AWS access keys
- GitHub PAT (`ghp_`, `github_pat_`)
- high-entropy 40+ char strings near credential keywords

If a future regex change increases positive recall but fails the negative corpus, the change is rejected unless the corpus sentence is proven to contain an actual secret.

---

## §X.5 Semaphore wiring for parallel subs (resolves C-5)

**Decision:** the master owns a single `asyncio.Semaphore(project.max_concurrent_domains)` per session. Every sub run is wrapped by a small coroutine that acquires the shared semaphore before calling `SubOrchestrator.run()`.

### §X.5.1 Replaces v3.0 §5.5 gather bullet and complements v3.1.4 §V.5

```python
class MasterOrchestrator:
    async def _run_sub_with_limit(self, sub: SubOrchestrator) -> DomainRunResult:
        async with self._domain_semaphore:
            await self._blackboard.sub_append(
                sub.sub_id,
                Event("sub_started", {"target_id": str(sub.target_id)}),
            )
            try:
                result = await sub.run()
                await self._blackboard.sub_append(
                    sub.sub_id,
                    Event("sub_finished", {"target_id": str(sub.target_id), "status": result["status"]}),
                )
                return result
            except asyncio.CancelledError:
                await self._blackboard.sub_append(
                    sub.sub_id,
                    Event("sub_cancelled", {"target_id": str(sub.target_id)}),
                )
                raise
            except Exception as exc:
                await self._blackboard.sub_append(
                    sub.sub_id,
                    Event("sub_failed", {"target_id": str(sub.target_id), "error": SecretScrubber.scrub(str(exc))}),
                )
                raise

    async def run_session(self, project: Project, targets: list[Target]) -> SessionReport:
        limit = project.max_concurrent_domains or settings.default_max_concurrent_domains
        self._domain_semaphore = asyncio.Semaphore(limit)

        subs = [self._make_sub(target) for target in targets]
        results = await asyncio.gather(
            *(self._run_sub_with_limit(sub) for sub in subs),
            return_exceptions=True,
        )
        return await self._aggregate_results(subs, results)
```

### §X.5.2 Semantics

- `max_concurrent_domains` counts active sub-orchestrators, not internal tool processes.
- Subs waiting on approval still hold their semaphore slot. This is intentional: an approval-paused domain remains an active domain and prevents unbounded expansion.
- Master supervisor / blackboard arbitration task is not gated by this semaphore.
- Domain agents may apply their own internal tool-level throttles, but those are independent.

### §X.5.3 Tests

- Project with 5 targets and `max_concurrent_domains=3` never records more than 3 simultaneous `sub_started` without matching terminal events.
- Terminal events are `sub_finished`, `sub_failed`, or `sub_cancelled`; the active-count assertion increments on `sub_started` and decrements on any terminal event.
- Approval-paused sub holds the slot; a queued 4th sub starts only after the paused sub times out, completes, or is killed.
- `max_concurrent_domains=1` produces serial domain execution while retaining master supervisor operation.

---

## §X.6 DomainAgent `docker_image` arity for Health (resolves C-6)

**Decision:** each public `DomainAgent` declares exactly one wrapper container image via `docker_image: str`. Health checks only wrapper images, not internal tool binaries or transitive images.

### §X.6.1 Amendment to v3.0 §5.4 base class

```python
class DomainAgent(ABC):
    agent_type: Literal["application", "web", "cloud_azure", "source_code"]
    docker_image: str
    risk_level: RiskLevel
    capabilities: list[str]
    default_concurrency: int
```

Canonical wrapper image names:

| Agent | `docker_image` |
|---|---|
| `ApplicationAgent` | `osa-agent-application:latest` |
| `WebAgent` | `osa-agent-web:latest` |
| `CloudAzureAgent` | `osa-agent-azure:latest` |
| `SourceCodeAgent` | `osa-agent-sourcecode:latest` |

### §X.6.2 Amendment to v3.1 §E.3 step 4

Health iterates:

```python
image_names = [agent_cls.docker_image for agent_cls in _DOMAIN_AGENTS.values()]
await DockerBackend.images_present(image_names)
```

Health does **not** check:
- `nmap`, `nuclei`, `pyrit`, `metasploit`, `semgrep`, `trivy`, `gitleaks` inner binaries individually
- language runtimes inside wrapper images
- remote registry availability

Those checks belong to image build CI and domain-agent smoke tests, not the periodic runtime health loop.

### §X.6.3 Tests

- Every registered domain agent has `docker_image: str` and non-empty value.
- Health image check count equals `len(_DOMAIN_AGENTS)` exactly.
- Removing an internal tool binary from a test image does not affect Health status; it is caught by domain-agent smoke tests instead.

---

## §X.7 v2.1 frontend fixture source (resolves C-7)

**Decision:** do not commit a built frontend bundle under `tests/e2e/v2_1_frontend_fixture/`. The fixture is a pinned CI artifact, fetched during E2E setup from a specific git ref / release asset and cached outside source control.

### §X.7.1 Amendment to v3.1 §K.4

Replace "cached in `tests/e2e/v2_1_frontend_fixture/`" with:

> The v2.1 frontend fixture is pinned by `tests/e2e/frontend-fixture.lock` and fetched by `scripts/fetch_v2_1_frontend_fixture.sh` into `.cache/e2e/v2_1_frontend_fixture/` (gitignored). The built bundle is not committed. CI restores it from artifact cache keyed by the lockfile hash; on cache miss, CI builds it from the pinned ref.

### §X.7.2 Lockfile shape

`tests/e2e/frontend-fixture.lock`:

```toml
repo = "jmstar85/offensive-security"
ref = "v2.1.0"
path = "frontend"
package_manager = "npm"
node_version = "20"
artifact_sha256 = "<filled by fixture build job>"
```

If no `v2.1.0` tag exists yet, create an immutable tag before enabling this gate. Do not use a branch name.

### §X.7.3 Fetch/build script contract

```bash
scripts/fetch_v2_1_frontend_fixture.sh \
  --lock tests/e2e/frontend-fixture.lock \
  --out .cache/e2e/v2_1_frontend_fixture
```

The script:
- verifies the resolved commit SHA matches the lockfile metadata
- runs `npm ci && npm run build`
- verifies `artifact_sha256` when present
- exits non-zero if the fixture cannot be reproduced

### §X.7.4 Tests / CI

- E2E job depends on the fixture-fetch step.
- Source tree grep: no committed files under `tests/e2e/v2_1_frontend_fixture/dist` or equivalent bundle output.
- Playwright config reads fixture root from `V2_1_FRONTEND_FIXTURE_DIR`, defaulting to `.cache/e2e/v2_1_frontend_fixture`.

---

## §X.8 Comment depth column (resolves C-8)

**Decision:** add `comments.depth INT NOT NULL DEFAULT 0` in Migration 005 and enforce max depth with a DB CHECK plus service-level parent-depth computation. This replaces recursive O(N) ancestry checks on every comment creation.

### §X.8.1 Amendment to v3.0 §5.1 Migration 005

```sql
ALTER TABLE comments
    ADD COLUMN depth INT NOT NULL DEFAULT 0,
    ADD CONSTRAINT comments_depth_range CHECK (depth >= 0 AND depth <= 5);

CREATE INDEX idx_comments_parent_depth ON comments(parent_comment_id, depth);
```

For SQLite test migrations, use the repository's existing batch-alter pattern if direct `ADD CONSTRAINT` is unavailable.

### §X.8.2 CommentService.create rule

```python
async def create_comment(project_id: UUID, parent_comment_id: UUID | None, body: str, author_id: UUID):
    if parent_comment_id is None:
        depth = 0
    else:
        parent = await self._comments.get_for_update(parent_comment_id)
        if parent.project_id != project_id:
            raise HTTPException(400, "parent comment belongs to another project")
        depth = parent.depth + 1
    if depth > 5:
        raise HTTPException(400, "thread depth exceeded")
    return await self._comments.insert(..., depth=depth)
```

`SELECT ... FOR UPDATE` is required for databases that support it. SQLite tests rely on transaction serialization; production PostgreSQL uses row lock.

### §X.8.3 Backfill

Existing comments at migration time:
- v2.1 has no comments table, so normal MVP migration needs no recursive backfill.
- If a pre-release v3 deployment exists, migration script computes depth via recursive CTE once and fails if any row exceeds 5.

### §X.8.4 Tests

- Root comment depth = 0.
- Reply depth = parent.depth + 1.
- 6th-level reply rejected with 400 before DB insert.
- Direct DB insert with depth 6 violates CHECK.
- Cross-project parent rejected.

---

## §X.9 Daily `activity_events` prune job (resolves C-9)

**Decision:** add a daily APScheduler job in `app/services/scheduling.py` that prunes `activity_events` older than 90 days. This supersedes v3.1 §M.3's standalone `scripts/prune_activity.py` as the primary runtime mechanism; the script may remain as a manual admin fallback.

### §X.9.1 Scheduling service

```python
class SchedulingService:
    def __init__(self, db_session_factory: async_sessionmaker[AsyncSession]):
        self._scheduler = AsyncIOScheduler(timezone="UTC")
        self._db_session_factory = db_session_factory

    def start(self) -> None:
        self._scheduler.add_job(
            self.prune_activity_events,
            trigger="cron",
            hour=3,
            minute=17,
            id="prune_activity_events",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()

    async def prune_activity_events(self) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=settings.activity_retention_days)
        async with self._db_session_factory() as db:
            result = await db.execute(
                delete(ActivityEvent).where(ActivityEvent.created_at < cutoff)
            )
            await db.commit()
            return result.rowcount or 0
```

### §X.9.2 Config

```python
settings.activity_retention_days: int = 90
settings.activity_prune_enabled: bool = True
```

If disabled, Health reports subsystem `activity_prune` as `degraded` with reason `disabled_by_config` unless deployment docs explicitly mark retention externalized.

### §X.9.3 Lifespan integration

FastAPI lifespan starts `SchedulingService` after DB readiness and stops it on shutdown. In tests, scheduler startup is disabled by default; jobs are invoked directly.

### §X.9.4 Tests

- Inserts events at 91 days and 89 days; prune deletes only 91-day row.
- Job is idempotent; second run deletes 0 rows.
- `max_instances=1` prevents overlapping prunes.
- Manual script and scheduler call the same service method.

---

## §X.10 Partial sub-orchestrator failure reporting (resolves C-10)

**Decision:** sub failures do not crash the master. Master aggregates per-domain results with explicit `domain_results[].status`. If a sub produced findings before failing, its status is `failed_after_partial` and captured findings remain in the final report.

### §X.10.1 Result shape

```python
class DomainRunResult(TypedDict):
    sub_id: str
    target_id: str
    target_type: Literal["application", "web", "cloud_azure", "source_code"]
    status: Literal["completed", "failed", "failed_after_partial", "approval_timeout", "killed"]
    findings: list[Finding]
    error_message: str | None
```

Session-level status uses existing / amended lifecycle:
- operator kill -> `killed`
- all domain results completed -> `completed`
- any domain produced findings or completed, and any domain ended in a non-completed terminal state (`failed`, `failed_after_partial`, `approval_timeout`, `killed` for that domain only) -> `completed_with_partial_failures`
- otherwise -> `failed`

Add `completed_with_partial_failures` to documented allowed session status values, API schemas, frontend status mapping, and tests. The current v2.1 model stores status as `String(50)`, so no SQL enum migration is required unless the implementation later introduces a database enum.

Deterministic rollup helper:

```python
def rollup_session_status(domain_results: list[DomainRunResult], operator_killed: bool) -> str:
    if operator_killed:
        return "killed"
    if all(r["status"] == "completed" for r in domain_results):
        return "completed"
    any_useful_output = any(
        r["status"] in {"completed", "failed_after_partial"} or bool(r["findings"])
        for r in domain_results
    )
    return "completed_with_partial_failures" if any_useful_output else "failed"
```

### §X.10.2 Aggregation code

```python
async def _aggregate_results(self, subs: list[SubOrchestrator], gather_results: list[object]) -> SessionReport:
    domain_results: list[DomainRunResult] = []
    for sub, result in zip(subs, gather_results, strict=True):
        captured = await self._blackboard.findings_for_sub(sub.sub_id)
        if isinstance(result, Exception):
            scrubbed = SecretScrubber.scrub(str(result))
            status = "failed_after_partial" if captured else "failed"
            domain_results.append({
                "sub_id": str(sub.sub_id),
                "target_id": str(sub.target_id),
                "target_type": sub.target_type,
                "status": status,
                "findings": captured,
                "error_message": scrubbed,
            })
        else:
            domain_results.append(result)
    return self._build_report(domain_results)
```

### §X.10.3 Persistence

- `pentest_sessions.output_json` / report JSON includes `domain_results`.
- `pentest_sessions.error_message` (v3.1.4 §V.6) stores a scrubbed summary only when final session status is `failed` or `completed_with_partial_failures`.
- Individual domain error messages are scrubbed before report persistence.

### §X.10.4 Tests

- One sub emits 2 findings then raises; another completes -> final session `completed_with_partial_failures`, report contains both partial findings and completed findings.
- One sub fails before findings; others complete -> partial-failure final status with failed domain result.
- All subs fail before findings -> final status `failed`.
- Raw exception containing bearer token is scrubbed in both domain result and session `error_message`.

---

## §X.11 Approval wait timeout vs grant TTL (resolves C-11)

**Decision:** the 30-minute approval wait and 1-hour approval grant TTL are intentionally different:

- `approval_wait_timeout_seconds` (default 1800) is the maximum time a live sub-orchestrator will remain suspended after requesting approval.
- `approval_ttl_seconds` (default 3600) is the maximum time an inserted approval grant remains valid for consumption.

This allows an operator to grant approval near the end of the 30-minute wait while still giving the resumed sub enough time to consume the grant after scheduling delay, DB latency, or a brief event-loop stall.

### §X.11.1 Amendment to v3.1 §H.4

Append:

> Approval wait timeout is measured from the sub's `ApprovalRequired` event. If no approval arrives within 1800s, the sub exits with `approval_timeout`. A grant inserted after the sub has timed out may still exist until its 3600s TTL but will not wake any sub; `notify_approval` returns `False` because the registry entry is gone. Stale unconsumed grants are ignored by future replans because `plan_version` and `step_hash` must match.

### §X.11.2 Amendment to v3.1 §F.1 / §F.2

Append:

> Grant TTL is measured from `granted_at`. It is intentionally longer than the live wait timeout. ApprovalGate consumes only non-expired grants matching `(session_id, step_hash, plan_version)` and `consumed_at IS NULL`. Timeout cleanup does not need to delete the grant; expiry and mismatch rules make it inert.

### §X.11.3 Edge-case table

| Event timing | Expected behavior |
|---|---|
| Approval at T+10m | Sub wakes, consumes grant, executes |
| Approval at T+29m59s | Sub wakes; grant remains valid until T+89m59s from request if needed |
| Approval at T+30m01s after sub timeout | POST may create grant, but registry notify returns false/no-op; UI shows session already timed out |
| Replan changes `plan_version` before grant consumed | Grant mismatch; fresh approval required per §W.4 |
| Duplicate approval before consumption | 409 per §W.5 |

### §X.11.4 Tests

- Approval at 1799s wakes and consumes.
- Approval after timeout does not revive sub; POST response includes `notify_delivered=false` or equivalent API field if exposed.
- Grant older than TTL rejected even if sub is waiting.
- Grant inserted after timeout is ignored by subsequent session relaunch because session_id / plan_version differ.

---

## §X.12 Updated Acceptance Criteria

After §X applied, ACs from v3.0 §7, v3.1 §N, v3.1.4 §V, and v3.1.5 §W remain. Add:

- **AC 30 (health credential boundary):** Health Claude probe reads only platform config and never imports or calls CredentialStore; attack-agent Docker env never includes `ANTHROPIC_API_KEY`. (§X.1)
- **AC 31 (`cloud_provider` deprecation):** Migration preserves legacy `projects.cloud_provider` values but all new cloud routing uses target rows; no new service logic branches on `project.cloud_provider`. (§X.2)
- **AC 32 (registry lifecycle):** Sub registration is removed on success, exception, cancellation, and approval timeout; stale `notify_approval` returns false/no-op. (§X.3)
- **AC 33 (scrubber false positives):** 100-sentence benign prose corpus has zero redactions while positive secret corpus still redacts all covered secret formats. (§X.4)
- **AC 34 (semaphore enforcement):** With 5 targets and `max_concurrent_domains=3`, no more than 3 subs are active at once; approval-paused subs count as active. (§X.5)
- **AC 35 (wrapper image health):** Health checks exactly one wrapper image per domain agent and does not inspect internal tool binaries. (§X.6)
- **AC 36 (frontend fixture reproducibility):** v2.1 frontend E2E fixture is fetched/built from an immutable pinned ref and no compiled bundle is committed. (§X.7)
- **AC 37 (comment depth):** Comment depth is stored, constrained to 0..5, and 6th-level replies fail at service and DB layers. (§X.8)
- **AC 38 (activity retention):** Daily scheduler prunes only `activity_events` older than `settings.activity_retention_days` and is idempotent. (§X.9)
- **AC 39 (partial failure report):** A sub that fails after emitting findings appears as `failed_after_partial`; final report preserves captured findings and scrubbed error. (§X.10)
- **AC 40 (approval timeout/TTL):** Approval wait timeout and grant TTL behave independently per §X.11 edge-case table. (§X.11)

---

## §X.13 Documentation updates required

- `docs/health.md` — platform Anthropic key boundary + wrapper-image-only health checks.
- `docs/api-migration.md` — `cloud_provider` deprecation and frontend fixture lock behavior.
- `docs/testing.md` or E2E README — v2.1 frontend fixture lockfile and fetch script.
- `docs/collaboration.md` — comment depth model and activity retention.
- `docs/orchestration.md` — registry lifecycle, semaphore behavior, partial failure semantics, approval wait vs TTL.
- `CHANGELOG.md` — v3.1.6 entry covering §C operational clarifications.

---

## §X.14 What this patch does NOT cover

- §D LOW items (4) — still deferred.
- §E pre-mortem additions (3) — still deferred.
- Any implementation code changes — this remains a plan/spec amendment.

After v3.1.6 is approved, proceed either to §D+§E final clarification patch or Phase 5.1 implementation.

---

## §X.15 Recommended next step

Run Critic review focused on:
1. Whether any §X item contradicts v3.1.4/v3.1.5 locked decisions.
2. Whether `completed_with_partial_failures` status documentation, API schema, frontend mapping, and tests are sufficient without a DB enum migration.
3. Whether the `cloud_provider` ignore policy in §X.2 is compatible with legacy clients that may send it.

---

## Iteration Changelog

- **v3.1.6-rev1** (2026-05-10): Critic minor edits applied — §X.5 now emits terminal sub events for semaphore active-count tests; §X.10 now has deterministic rollup rules for all partial/timeout cases; `completed_with_partial_failures` is documented as an allowed string status/API/frontend mapping addition, not a SQL enum migration.
- **v3.1.6** (2026-05-10): Iteration 6 operational-clarity patch. Resolves all 11 MED-LOW §C items: platform-vs-user credential boundary, legacy `cloud_provider` lifecycle, registry weakref lifecycle, SecretScrubber negative corpus, semaphore wiring, wrapper-image health checks, reproducible v2.1 frontend fixture, comment depth column, APScheduler activity retention, partial sub failure reporting, and approval wait/TTL semantics.
