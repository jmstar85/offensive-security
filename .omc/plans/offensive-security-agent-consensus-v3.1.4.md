# OSA Platform v3.1.4 — Iteration 4 (Resolves §A 7 HIGH contradictions)

**Status:** Iteration 4/5 — addresses 7 HIGH contradictions from `PLAN-VERIFICATION-2026-05-10.md` §A
**Companion docs (read together):**
- v2.1 baseline (implemented): `offensive-security-agent-consensus.md`
- v3.0 base: `offensive-security-agent-consensus-v3.md`
- v3.1+v3.1.3 amendments: `offensive-security-agent-consensus-v3.1.md`
- v3.1.4 (this file): textual fixes only — **supersedes** the cited §sections in v3.1 / v3.0

**Scope:** §A items only (contradictions). HIGH-MED §B items deferred to v3.1.5 unless user requests now. MED-LOW §C items will be resolved during implementation.

**Locked decisions unchanged.**

---

## §V. Iteration-4 Decision Map

| # | From verification | Resolution location |
|---|---|---|
| A-1 | Blackboard `version` semantics conflict | §V.1 |
| A-2 | Convergence detection not terminal | §V.2 |
| A-3 | §D shim wildcard contradicts §T NEW-4 | §V.3 |
| A-4 | `whitelist_rules` vs `scope_rules` column naming | §V.4 |
| A-5 | AC #4 inconsistent with §J.2 | §V.5 |
| A-6 | §Q exception scrubber field undefined for sessions | §V.6 |
| A-7 | §5.9 WS table not synced with §L.1 | §V.7 |

---

## §V.1 Blackboard `version` — strictly monotonic (resolves A-1)

**Decision:** version is **strictly monotonic** under a single lock. Drop "advisory" framing entirely.

**Replaces v3.1 §A `Blackboard` class body and §T NEW-1 entirely:**

```python
class Blackboard:
    """Session-scoped coordination surface.

    Region 1 (per-sub append-only): sub-orchestrator findings/observations.
    Region 2 (master control dict): cancel, pause, replan_directive, awaiting_approval.

    Single asyncio.Lock guards version increment AND all writes.
    Version is strictly monotonic: every write increments it under the lock.
    Readers may snapshot without the lock; they may observe (version_n - 1) briefly
    but never an inconsistent state because writes complete-then-publish version.

    Lock-free `snapshot()` correctness depends on single-loop asyncio execution.
    If multi-loop or threaded execution is introduced (e.g., Phase-2 Redis backend
    running master in a thread pool), `snapshot()` MUST acquire `_lock`.
    """
    def __init__(self, session_id: uuid.UUID, sub_ids: list[str]) -> None:
        self._session_id = session_id
        self._sub_lists: dict[str, list[Event]] = {sid: [] for sid in sub_ids}
        self._control: dict = {}
        self._lock = asyncio.Lock()
        self._version = 0

    async def sub_append(self, sub_id: str, event: Event) -> int:
        async with self._lock:
            self._sub_lists[sub_id].append(event)
            self._version += 1
            return self._version

    async def control_set(self, key: str, value: Any) -> int:
        async with self._lock:
            new = {**self._control, key: value}
            self._control = new
            self._version += 1
            return self._version

    def snapshot(self) -> BlackboardSnapshot:
        # Lock-free read; tolerates seeing a write that just landed.
        return BlackboardSnapshot(
            sub_events={sid: list(events) for sid, events in self._sub_lists.items()},
            control=dict(self._control),
            version=self._version,
        )
```

**Performance note:** at MVP scale (≤3 concurrent subs, ≤100 writes/s/sub), single-lock contention is negligible (<5% wait-time per `pyinstrument` rough estimate). Phase-2 Redis backend natively serializes — same contract.

**§S `_has_new_observations` unchanged** — `snapshot.version > self._last_replan_version` works because version is now strictly monotonic.

**§T NEW-1 row updated:** "Version counter is **strictly monotonic** under a single asyncio.Lock guarding both regions. Atomic-list-append optimization removed for spec simplicity."

**Tests retained from v3.1 §A:**
- 10 subs × 100 events concurrent → all 1000 appended, version reaches exactly 1000
- `control_set` cancellation in flight → atomic (lock released by `__aexit__`, dict either old or new)
- snapshot consistency → `snapshot.version` ≥ count of events visible

---

## §V.2 Convergence detection — terminal flag (resolves A-2)

**Decision:** add `self._converged: bool` to MasterOrchestrator. Once set, no further Claude calls; subs continue executing the current plan.

**Replaces v3.1 §I.2 entirely:**

```python
class MasterOrchestrator:
    def __init__(self, ...):
        self._replan_count = 0
        self._token_budget = settings.max_claude_tokens_per_session
        self._last_plan_hashes: deque[str] = deque(maxlen=3)
        self._last_replan_version = 0
        self._converged = False  # ← new terminal flag

    async def supervisor_loop(self):
        while not self._all_subs_done():
            await asyncio.sleep(0.5)
            if self._converged:
                continue                                     # never replan after terminal
            if self._replan_count >= settings.max_replans_per_session:
                self._converged = True
                self._stop_reason = "replan_cap"
                continue
            if self._token_budget <= 0:
                self._converged = True
                self._stop_reason = "token_budget"
                continue
            snapshot = self._blackboard.snapshot()
            if not self._has_new_observations(snapshot):
                continue
            new_plan, tokens_used = await self._claude_replan(snapshot)
            self._replan_count += 1
            self._token_budget -= tokens_used
            # advance after every replan call (even if convergence aborts distribute);
            # prevents re-trigger on the same observation snapshot in the next tick.
            self._last_replan_version = snapshot.version
            plan_hash = self._hash_plan(new_plan)
            self._last_plan_hashes.append(plan_hash)
            if (
                len(self._last_plan_hashes) == 3
                and len(set(self._last_plan_hashes)) == 1
            ):
                self._converged = True
                self._stop_reason = "converged"
                continue                                     # do NOT distribute (same plan)
            await self._distribute_plan(new_plan)
        await self._finalize(stop_reason=self._stop_reason)   # persists pentest_sessions.stop_reason
```

**New session column (Migration 003 — see also §V.6 consolidated list):**
```sql
ALTER TABLE pentest_sessions ADD COLUMN stop_reason VARCHAR(32) NULL;
-- values: "converged" | "replan_cap" | "token_budget" | NULL (still running / completed normally)
```
ORM: `PentestSession.stop_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)`.
API: `SessionRead.stop_reason: str | None` — additive field, safe to expose.

**Behavior change vs v3.1 §I.2:**
- All three §I.1 stop conditions (replan cap, token cap, convergence) now set `_converged`. `_converged` is the single terminal switch checked at loop top.
- `_last_replan_version` advances **after every replan call** (not only if distribution happened) → eliminates re-trigger on the same observation snapshot.
- §I.1 #3 wording in v3.1 ("master simply stops calling Claude") is now factually correct.

**New unit test (replaces v3.1 §I.4 cycle 3 test):**
- 3 consecutive replans produce identical plan_hash → `_converged == True`, no further `_claude_replan` calls in next 5 supervisor ticks (assert via mock counter)
- After convergence, sub-orchestrators continue executing the most recent distributed plan to completion

---

## §V.3 §D shim — explicit re-export (resolves A-3)

**Replaces v3.1 §D code block in full** (no wildcard, matches §T NEW-4):

```python
# app/agents/nmap.py  (now a 2-line shim)
"""Backward-compat shim. New code should import from app.agents._tools.nmap."""
from app.agents._tools.nmap import NmapAdapter  # noqa: F401
```

Apply the **identical** pattern (single explicit class import, no `*`, no extra symbols) to `app/agents/nuclei.py`, `app/agents/metasploit.py`, `app/agents/pyrit.py`. Each shim re-exports exactly **one** class — matching the v2.1 surface that 85 tests import.

**CI gate (already in §T NEW-4) reaffirmed:**
```bash
! grep -rn "from app.agents._tools" backend/tests/  # tests must import from app.agents.<tool>, not _tools
! grep -n "import \*" backend/app/agents/*.py        # no wildcard imports allowed in shims
```

---

## §V.4 Column naming — keep `whitelist_rules`, semantics extended (resolves A-4)

**Decision:** **DO NOT rename** the existing `targets.whitelist_rules` column. Reasons:

1. v2.1 baseline uses `whitelist_rules` in `app/models/project.py:37`, `alembic/versions/001_initial.py:58`, `app/orchestrator/executor.py:30`, `app/safety/egress_monitor.py:27`, plus all test fixtures.
2. Rename forces churn across ORM model + migration + 2 safety modules + 6+ tests = high risk for zero functional gain.
3. The v3 plan's "scope rules" terminology can refer to the same column as a semantic concept.

**Spec-text change:** all v3.0 / v3.1 references to `target.scope_rules` mean the column **named** `whitelist_rules` whose JSONB content is interpreted per the **scope_rules schema** (to be canonicalized in §B-1 / future §U).

**Migration 003 update:** no rename. Migration 003 still adds `target_type`, `name` per §J.1, and the `scope_rules` JSONB content is stored in the existing `whitelist_rules` column.

**v3.0 §5.1 003_multi_target.py amendment:**
> ~~`scope_rules JSONB` (existing column kept, semantics extended)~~  
> → `whitelist_rules JSONB` (existing column kept, semantics extended per scope_rules schema; column not renamed for backward-compat with 85 v2.1 tests)

**v3.1 §G `target.scope_rules` references:** read as `target.whitelist_rules` (Python attribute on the ORM model, JSONB column) carrying scope_rules-schema content.

**v3.1 §K.2 POST body `scope_rules` field name:** **kept as `scope_rules`** at the API boundary. Handler maps API field `scope_rules` → ORM attribute `whitelist_rules` → DB column `whitelist_rules`. The API name is forward-looking; the DB name is backward-compat. Document mapping in `docs/api-migration.md`.

```python
# app/api/v1/targets.py  — handler maps API ↔ ORM in BOTH directions
class TargetCreate(BaseModel):
    target_type: str
    name: str
    scope_rules: dict          # API field name (write path)

class TargetRead(BaseModel):
    id: uuid.UUID
    target_type: str
    name: str
    scope_rules: dict          # API field name (read path)

    @classmethod
    def from_orm_target(cls, t: Target) -> "TargetRead":
        return cls(
            id=t.id,
            target_type=t.target_type,
            name=t.name,
            scope_rules=t.whitelist_rules,   # ← reverse map: ORM → API
        )

@router.post(...)
async def create_target(body: TargetCreate, ...) -> TargetRead:
    target = Target(
        target_type=body.target_type,
        name=body.name,
        whitelist_rules=body.scope_rules,   # ← forward map: API → ORM
    )
    ...
    return TargetRead.from_orm_target(target)

@router.get("/{id}", response_model=TargetRead)
async def get_target(id: uuid.UUID, ...) -> TargetRead:
    target = await db.get(Target, id)
    return TargetRead.from_orm_target(target)
```

**Additional spec corrections (residual naming drift):**

- **v3.0 §5.5** — paragraph beginning "asyncio.gather(*subs, ...)" — replace `project's concurrency_limit` with `project.max_concurrent_domains` (parity with §V.5).
- **§G text** — remains using `target.scope_rules` as a *semantic* reference. ORM attribute is `target.whitelist_rules`. This split is **permanent for MVP** and tracked in §8 ADR follow-ups for Phase-2 cleanup.
- **OpenAPI schema** — must expose `scope_rules` (NOT `whitelist_rules`) on both `TargetCreate` and `TargetRead`. Asserted by §V.9 test.

**Future migration window (Phase-2 follow-up, not MVP):** rename `whitelist_rules → scope_rules` in a single migration once v2.1 test fixtures are deprecated. Track in §8 ADR follow-ups.

---

## §V.5 AC #4 update (resolves A-5)

**Replaces v3.0 §7 AC #4:**

> **AC 4 (revised):** Multi-domain session runs sub-orchestrators in parallel up to `projects.max_concurrent_domains` (default 3); excess sub-orchestrators are throttled by an `asyncio.Semaphore(project.max_concurrent_domains)` shared across all subs in the session. Test: launch session with 5 targets → at any moment, no more than 3 are in `running` state; remaining queued via semaphore acquire.

**No other v3.0 §7 ACs affected** (verified by grep against `concurrency_limit` — only AC #4 referenced the deprecated naming).

---

## §V.6 Session-level error scrubber field (resolves A-6)

**Decision:** add `error_message TEXT NULL` column to `pentest_sessions` so §Q can scrub session-level failures uniformly.

**Migration 003 — consolidated column list (literal rewrite of §J.1; supersedes the §J.1 enumeration):**

| Table | Operation | Column | Type | Source section |
|---|---|---|---|---|
| `targets` | ADD | `target_type` | ENUM('application','web','cloud_azure','source_code') NOT NULL DEFAULT 'web' | v3.1 §J.1 (corrected in v3.1.5 §W.1.0 — earlier draft incorrectly said `'web_application'`) |
| `targets` | ADD | `name` | VARCHAR(255) NOT NULL DEFAULT 'unnamed' | v3.1 §J.1 |
| `targets` | (kept) | `whitelist_rules` | JSONB (semantics extended per scope_rules schema) | v2.1 + §V.4 |
| `projects` | ADD | `max_concurrent_domains` | INT NOT NULL DEFAULT 3 | v3.1 §J.1 + §V.5 |
| `pentest_sessions` | ADD | `error_message` | TEXT NULL | **§V.6** |
| `pentest_sessions` | ADD | `stop_reason` | VARCHAR(32) NULL | **§V.2** |
| (no RENAME) | — | — | — | §V.4 + §V.9 test |

- No backfill needed for new NULL columns
- No index needed at MVP
- Migration 003 **must NOT** issue any `RENAME COLUMN` (asserted by §V.9 grep test)

**§Q amendment:**
```python
# Session-level failure (e.g., orchestrator-restart-during-approval, or _claude_replan blew up)
scrubbed_session_error = SecretScrubber.scrub(str(session_exc))
await self._db.execute(
    update(PentestSession).where(PentestSession.id == session_id)
    .values(status="failed", error_message=scrubbed_session_error)
)
```

**ORM model update:** `app/models/session.py` `PentestSession` adds `error_message: Mapped[str | None] = mapped_column(Text, nullable=True)`.

**API exposure:** `GET /api/v1/sessions/{id}` response (`SessionRead` Pydantic model) includes:
- `error_message: str | None` — already-scrubbed, safe to return
- `stop_reason: str | None` — from §V.2

Both are **additive** API changes (existing clients ignore unknown fields). Document in `docs/api-migration.md` and root `CHANGELOG.md`.

**Test addition (extends §Q test list):** `session.error_message_scrubs_credentials` — plant fake bearer in `_claude_replan` exception → assert `pentest_sessions.error_message` row contains `[REDACTED:bearer]`, never the raw token.

---

## §V.7 WS endpoint table sync (resolves A-7)

**Replaces v3.0 §5.9 rows for project-level WS:**

| Method | Path | Description | Auth |
|---|---|---|---|
| ~~WS~~ | ~~`/ws/projects/{id}/comments`~~ | ~~Realtime comments~~ | ~~member~~ |
| ~~WS~~ | ~~`/ws/projects/{id}/activity`~~ | ~~Realtime activity events~~ | ~~member~~ |
| **WS** | **`/ws/projects/{id}`** | **Multiplexed: comments + activity + session_update via `channel` envelope (per §L.1)** | **member** |
| WS | `/ws/admin/health` | Realtime health updates | admin |
| WS | `/ws/sessions/{id}` | Single-session monitor — **kept separate** for v2.1 backward-compat | member |

**Frontend hook spec (cross-ref §T NEW-10) reaffirmed:** `useProjectWebSocket(projectId)` demuxes `channel` field into 3 state slices (`comments`, `activity`, `sessions`). Existing `useWebSocket(sessionId)` for `/ws/sessions/{id}` preserved.

---

## §V.8 Updated Acceptance Criteria Summary

After §V applied, the authoritative AC set is:
- v3.0 §7 ACs 1–18 with **AC #4 replaced by §V.5**
- v3.1 §N.1 AC 19–22 unchanged
- (No new ACs added in v3.1.4 — fixes are textual.)

---

## §V.9 Test Plan Additions for v3.1.4

| Component | Test | Acceptance |
|---|---|---|
| `Blackboard.sub_append` + `control_set` race | 10 subs concurrent + master concurrent control writes | final version == total writes; no skipped numbers |
| `MasterOrchestrator.supervisor_loop` convergence terminal | 3 identical plan hashes | `_converged == True`; subsequent 5 ticks make 0 Claude calls |
| `MasterOrchestrator.supervisor_loop` budget terminal | token budget exhausted | `_converged == True`; subs continue last plan |
| `MasterOrchestrator.supervisor_loop` cap terminal | replan_count == cap | `_converged == True`; subs continue last plan |
| `app/agents/nmap.py` shim explicit import | `from app.agents.nmap import NmapAdapter` works post-refactor | no ImportError; `NmapAdapter` is exact same class as `_tools.nmap.NmapAdapter` |
| `Migration 003` no column rename | run 001→002→003 against v2.1-shape SQLite | `targets.whitelist_rules` exists with v2.1 contents intact |
| `targets API mapping` | POST `{scope_rules: {...}}` | DB `whitelist_rules` column matches body; GET response surfaces field as `scope_rules` |
| `pentest_sessions.error_message scrubbing` | mock `_claude_replan` raises with bearer token in message | row's `error_message` contains `[REDACTED:bearer]`, no raw token |
| `pentest_sessions.error_message default` | normal completed session (no failure) | `error_message IS NULL`; `SessionRead.error_message == None` |
| `pentest_sessions.stop_reason terminal paths` | trigger each of 3 terminal conditions | row's `stop_reason` ∈ `{"converged", "replan_cap", "token_budget"}` matching the trigger |
| `Migration 003 no RENAME` | grep alembic 003 file | zero matches for `op.alter_column.*new_column_name`, zero `RENAME COLUMN` raw SQL |
| `OpenAPI target schema field name` | inspect `/openapi.json` after app boot | `components.schemas.TargetCreate.properties.scope_rules` exists; `.whitelist_rules` does NOT exist |
| `OpenAPI session schema additive fields` | inspect `/openapi.json` | `SessionRead.properties.error_message` and `.stop_reason` both present |

---

## §V.10 Documentation updates required

- `docs/api-migration.md` — new file. Documents `scope_rules` (API name) ↔ `whitelist_rules` (DB column) mapping. References v2.1 → v3 frontend flow.
- `docs/safety-v3.md` — append: "Session-level errors are scrubbed via SecretScrubber before persistence to `pentest_sessions.error_message`."
- `docs/architecture-v3.md` — append §I terminal flag note (convergence is terminal, not transient).

---

## §V.11 What this patch does NOT cover

- §B HIGH-MED items (B-1 scope_rules schema canonical, B-2 priv-esc classification, B-3 CoreDNS mechanism, B-4 paused-sub plan_version freeze, B-5 approval race 409, B-6 credential M:N) — deferred to **v3.1.5** if user requests.
- §C MED-LOW items — to be resolved during implementation; tracked as todos.

---

## §V.12 Recommended next step

1. Run **Critic** agent on v3.1.4 (regression-free check on §V resolutions).
2. If Critic APPROVES → either proceed to v3.1.5 (§B items) or begin implementation Phase 5.1 (Migration 003 with §V.4 + §V.6 amendments).
3. If Critic finds defects → patch in v3.1.4-rev2.

---

## Iteration Changelog
- **v3.1.4-rev1** (2026-05-10): Critic edits applied — added `stop_reason` column + branching, `TargetRead` symmetric mapping, consolidated Migration 003 column table, OpenAPI/no-rename tests, single-loop asyncio caveat in Blackboard docstring, residual §5.5 / §G naming-drift call-outs.
- **v3.1.4** (2026-05-10): Iteration 4 contradiction-resolution patch. §V.1–§V.11. Resolves all 7 HIGH `§A` items from `PLAN-VERIFICATION-2026-05-10.md`. Textual changes only; no new architecture.
- v3.1.3 (2026-05-10): Iteration 3 — §Q–§T (Architect NEW-1~11).
- v3.1 (2026-05-10): Iteration 2 — §A–§P (Architect-1 + Critic-1 reviews).
- v3.0 (2026-05-10): Planner draft.
