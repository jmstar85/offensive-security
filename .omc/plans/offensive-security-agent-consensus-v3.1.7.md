# OSA Platform v3.1.7 — Iteration 7 (Resolves §D LOW + §E Pre-Mortem additions)

**Status:** Iteration 7 — final pre-implementation clarification patch for the remaining LOW and pre-mortem items from `PLAN-VERIFICATION-2026-05-10.md` §D/§E.

**Companion docs (read together):**
- v2.1 baseline (implemented): `offensive-security-agent-consensus.md`
- v3.0 base: `offensive-security-agent-consensus-v3.md`
- v3.1+v3.1.3 amendments: `offensive-security-agent-consensus-v3.1.md`
- v3.1.4-rev1 (§A fixes): `offensive-security-agent-consensus-v3.1.4.md`
- v3.1.5-rev3 (§B fixes): `offensive-security-agent-consensus-v3.1.5.md`
- v3.1.6-rev1 (§C fixes): `offensive-security-agent-consensus-v3.1.6.md`
- **v3.1.7 (this file):** final LOW/pre-mortem clarifications before implementation

**Scope:** §D LOW items and §E pre-mortem additions only. This file does not reopen locked architecture choices.

---

## §Y. Iteration-7 Decision Map

| # | From verification | Resolution location |
|---|---|---|
| D-1 | `approval_grants` lacks `created_at` | §Y.1 |
| D-2 | Registry fan-out should include `sub_id` | Already resolved in v3.1.5 §W.5 + v3.1.6 §X.3; restated in §Y.2 |
| D-3 | 6th-level comment race | §Y.3 |
| D-4 | `consumed_at` nullable convention | §Y.4 |
| E-1 | 4-domain MVP fallback if schedule slips | §Y.5 |
| E-2 | Single-target hierarchical overhead | §Y.6 |
| E-3 | Single uvicorn worker deployment regression | §Y.7 |

---

## §Y.1 `approval_grants.created_at` audit convention (resolves D-1)

**Decision:** add `created_at TIMESTAMPTZ NOT NULL DEFAULT now()` to `approval_grants` as an audit-convention alias. Keep `granted_at` as the semantic approval timestamp used by TTL logic.

### §Y.1.1 Amendment to v3.1 §F.1 schema

```sql
CREATE TABLE approval_grants (
    id              UUID PRIMARY KEY,
    session_id      UUID NOT NULL REFERENCES pentest_sessions(id),
    plan_version    INT NOT NULL,
    step_hash       CHAR(64) NOT NULL,
    action_class    VARCHAR(64) NOT NULL,
    granted_by      UUID NOT NULL REFERENCES users(id),
    granted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL DEFAULT (now() + INTERVAL '1 hour'),
    consumed_at     TIMESTAMPTZ NULL,
    UNIQUE (session_id, step_hash, plan_version)
);
```

`created_at` and `granted_at` are expected to be equal for normal API-created grants. If a future import/replay tool creates historical grants, `created_at` is insertion time and `granted_at` is historical operator action time.

### §Y.1.2 Tests

- Insert approval via API -> response includes `granted_at`; DB row has non-null `created_at`.
- TTL calculations use `granted_at`/`expires_at`, not `created_at`.

---

## §Y.2 Registry fan-out routing key (resolves D-2)

**Decision:** approval routing is sub-specific end-to-end. v3.1.5 §W.5 and v3.1.6 §X.3 correctly moved the live registry notification to `sub_id`, but v3.1.7 makes the upstream API, DB uniqueness, and ApprovalGate lookup sub-specific as well.

```python
OrchestratorRegistry.notify_approval(session_id, sub_id, step_hash) -> bool
```

Any implementation that fans out or stores grants by `(session_id, step_hash)` alone is non-compliant.

### §Y.2.1 Overrides v3.1 §F.1 approval_grants identity

Add `sub_id` to `approval_grants` and update uniqueness:

```sql
CREATE TABLE approval_grants (
    id              UUID PRIMARY KEY,
    session_id      UUID NOT NULL REFERENCES pentest_sessions(id),
    sub_id          UUID NOT NULL,
    plan_version    INT NOT NULL,
    step_hash       CHAR(64) NOT NULL,
    action_class    VARCHAR(64) NOT NULL,
    granted_by      UUID NOT NULL REFERENCES users(id),
    granted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL DEFAULT (now() + INTERVAL '1 hour'),
    consumed_at     TIMESTAMPTZ NULL,
    UNIQUE (session_id, sub_id, step_hash, plan_version)
);
```

`sub_id` is the UUID assigned to the live SubOrchestrator and used in Blackboard keys (`awaiting_approval:{sub_id}`).

### §Y.2.2 Overrides v3.1 §F.2 ApprovalGate signature and lookup

```python
class ApprovalGate:
    async def require(self, session_id: UUID, sub_id: UUID, step: Step, plan_version: int) -> None:
        step_hash = _hash_step(step)
        action_class = self._classify(step)
        if action_class is None:
            return
        result = await self._db.execute(
            select(ApprovalGrant).where(
                ApprovalGrant.session_id == session_id,
                ApprovalGrant.sub_id == sub_id,
                ApprovalGrant.step_hash == step_hash,
                ApprovalGrant.plan_version == plan_version,
                ApprovalGrant.consumed_at.is_(None),
                ApprovalGrant.expires_at > func.now(),
            )
        )
        grant = result.scalar_one_or_none()
        if not grant:
            raise ApprovalRequired(
                action_class=action_class,
                step_hash=step_hash,
                plan_version=plan_version,
                sub_id=sub_id,
            )
        await self._db.execute(
            update(ApprovalGrant).where(ApprovalGrant.id == grant.id).values(consumed_at=func.now())
        )
```

`SubOrchestrator` always calls:

```python
await self._approval_gate.require(self._session_id, self._sub_id, step, self._plan_version)
```

### §Y.2.3 Overrides v3.1.5 §W.5 approval API body

`POST /api/v1/sessions/{id}/approvals` body:

```json
{
  "sub_id": "uuid",
  "step_hash": "sha256hex",
  "plan_version": 7
}
```

Handler behavior:

```python
grant = ApprovalGrant(
    session_id=session_id,
    sub_id=body.sub_id,
    step_hash=body.step_hash,
    plan_version=body.plan_version,
    action_class=await _action_class_from_awaiting_key(session_id, body.sub_id, body.step_hash),
    granted_by=current_user.id,
)
db.add(grant)
try:
    await db.commit()
except IntegrityError:
    await db.rollback()
    raise HTTPException(409, {"reason": "already_approved"})

delivered = OrchestratorRegistry.notify_approval(session_id, body.sub_id, body.step_hash)
return ApprovalRead.from_orm(grant, notify_delivered=delivered)
```

`_action_class_from_awaiting_key` reads exactly `awaiting_approval:{sub_id}` and verifies the stored `step_hash` and `plan_version` match the request. If no matching awaiting key exists, return 404 or 409 with `{"reason": "approval_target_not_waiting"}` and do not insert a grant.

### §Y.2.4 Backward-compatibility shim for old clients

The old body shape without `sub_id` is accepted only when exactly one `awaiting_approval:*` Blackboard key in the session matches `(step_hash, plan_version)`.

- zero matches -> 404 `approval_target_not_waiting`
- one match -> fill `sub_id` server-side and proceed
- multiple matches -> 409 `ambiguous_approval_sub_id_required`

New UI must always send `sub_id`.

### §Y.2.5 Tests

- Two subs in the same session wait on identical step hashes under contrived test input; approval for `sub_a` wakes only `sub_a`.
- Approval for `sub_b` later succeeds independently because uniqueness includes `sub_id`.
- `notify_approval(session_id, wrong_sub_id, step_hash)` returns `False`.
- Duplicate approval for the same `(session_id, sub_id, step_hash, plan_version)` returns 409.
- Old body shape without `sub_id` succeeds only with exactly one matching awaiting key and returns `ambiguous_approval_sub_id_required` when multiple subs match.

---

## §Y.3 Comment depth race convention (resolves D-3)

**Decision:** v3.1.6 §X.8 is canonical. Service computes `depth = parent.depth + 1`; DB enforces `CHECK (depth >= 0 AND depth <= 5)`. Under concurrent replies to the same parent, both replies may legitimately receive the same depth. This is not a lost-update problem because depth is a derived immutable value, not a sibling counter.

### §Y.3.1 Race handling

- Use parent row lock where the DB supports it (`SELECT ... FOR UPDATE`) to ensure the parent is not deleted or moved while creating the child.
- If parent is soft-deleted between read and insert, reject with 400 `"parent comment deleted"`.
- Last-write-wins is acceptable only for UI ordering metadata such as `updated_at`; it must not bypass the DB depth check.

### §Y.3.2 Tests

- Two concurrent replies to a depth-4 parent both succeed at depth 5.
- Two concurrent replies to a depth-5 parent both fail with 400 or DB CHECK violation mapped to 400.

---

## §Y.4 `approval_grants.consumed_at` nullable convention (resolves D-4)

**Decision:** keep `consumed_at TIMESTAMPTZ NULL`. NULL means "not consumed"; non-NULL means "consumed at timestamp." Do not use an infinity sentinel in MVP.

Rationale:
- PostgreSQL partial index `WHERE consumed_at IS NULL` is clear and already specified in v3.1 §F.1.
- SQLAlchemy/Pydantic nullable timestamp maps cleanly to API/admin tooling.
- Infinity timestamp behavior differs across SQLite/PostgreSQL test paths and adds no MVP value.

### §Y.4.1 Tests

- Unconsumed grants query via `consumed_at IS NULL`.
- Consuming a grant atomically sets `consumed_at=now()`.
- A consumed grant cannot be reused even if `expires_at` is still in the future.

---

## §Y.5 Four-domain MVP fallback decision gate (resolves E-1)

**Decision:** the official MVP remains all 4 domain agents: `application`, `web`, `cloud_azure`, `source_code`. If implementation schedule or cost forces a scope cut, the only allowed cut is to defer `SourceCodeAgent` behind a feature flag; it must be an explicit operator/product decision, not a silent slip.

### §Y.5.1 Risk table addendum

Append to v3.0 §6 Risks:

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Four-domain MVP exceeds implementation budget | Medium | Medium | Keep all schema/API enum values. If cut is required, set `settings.source_code_agent_enabled=false`, return 501 for launching source-code targets, and document Phase-2 restoration. Do not remove `source_code` enum or DB compatibility. |

### §Y.5.2 Feature flag behavior if activated

```python
settings.source_code_agent_enabled: bool = True
```

If false:
- creating `target_type='source_code'` remains allowed for forward compatibility
- launching a session containing source-code targets returns 501 with reason `"source_code_agent_disabled"`
- UI shows "Source Code agent disabled by deployment config"
- existing source-code targets are not deleted

### §Y.5.3 Tests

- Default config: SourceCodeAgent registered and launchable.
- Disabled config: source-code target create succeeds; session launch fails cleanly with 501; other target types unaffected.

---

## §Y.6 Single-target fast path (resolves E-2)

**Decision:** implementation may optimize the v2.1-compatible single-target path by bypassing Master+Blackboard orchestration, but correctness must not depend on the fast path. The canonical multi-target behavior remains hierarchical.

### §Y.6.1 Fast-path constraints

Fast path is allowed only when all are true:
- project has exactly one selected target
- no campaign/multi-session coordination requested
- `settings.single_target_fast_path_enabled == True`
- target does not require cross-domain shared observations

Fast path still uses:
- DomainAgent interface
- per-target EgressMonitor
- ApprovalGate
- SecretScrubber
- AuditLogger
- same report shape as hierarchical path

### §Y.6.2 Fallback

Any fast-path error before first tool execution falls back to hierarchical path. Any error after execution starts follows normal failure handling and must not rerun tools automatically.

### §Y.6.3 Tests

- Legacy single web target can run with fast path and produces v2.1-compatible output.
- Disabling `single_target_fast_path_enabled` routes the same target through Master+Blackboard.
- Fast path and hierarchical path produce equivalent normalized report fields for the same mocked findings.

---

## §Y.7 Single-worker deployment breaking note (resolves E-3)

**Decision:** v3 orchestration remains single-process/single-worker for MVP because `OrchestratorRegistry`, live `asyncio.Event`s, scheduler tasks, and in-memory WebSocket subscribers are process-local. This is a **breaking deployment requirement** for any v2.1 deployment that used multiple Uvicorn/Gunicorn workers.

### §Y.7.1 Deployment docs amendment

Add to `docs/deployment.md`:

> **BREAKING (v3 MVP): run exactly one backend worker.** Do not run `uvicorn --workers > 1` or Gunicorn with multiple workers. Live orchestration state is process-local in MVP. Horizontal/multi-worker deployment requires Phase-2 external coordination (Redis/NATS for registry/events + durable orchestration state).

Recommended command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

### §Y.7.2 Startup guard

§Y.7 supersedes v3.1 §R.1–§R.2's hard startup assertion with a warning-only guard for MVP; deployment docs and Docker/compose pinning remain the enforcement path.

At startup, log a warning if known worker-count env vars indicate multiple workers:

```python
for name in ("UVICORN_WORKERS", "WEB_CONCURRENCY"):
    value = os.getenv(name)
    if not value:
        continue
    try:
        workers = int(value)
    except ValueError:
        logger.warning(
            "OSA v3 MVP requires single-worker deployment; ignoring non-integer %s=%r",
            name,
            value,
        )
        continue
    if workers != 1:
        logger.warning(
            "OSA v3 MVP requires %s=1; multi-worker orchestration is unsupported",
            name,
        )
```

Do not hard-fail startup in MVP; container platforms may set these variables inconsistently. Documentation and health warnings are the enforcement path.

### §Y.7.3 CHANGELOG entry

Root `CHANGELOG.md` v3 entry must include:

> BREAKING: backend must run with a single worker for v3 MVP. Multi-worker deployments are unsupported until Phase 2 externalizes orchestration registry/events.

### §Y.7.4 Tests

- Config/startup test: `WEB_CONCURRENCY=2` emits warning.
- Docs test/grep: `docs/deployment.md` contains "single worker" and `--workers 1`.

---

## §Y.8 Updated Acceptance Criteria

After §Y applied, prior ACs remain. Add:

- **AC 41:** `approval_grants.created_at` is non-null, while TTL semantics still use `granted_at`/`expires_at`. (§Y.1)
- **AC 42:** Approval flow is sub-specific end-to-end: API body, grant uniqueness, ApprovalGate lookup, and registry notification all include `sub_id`; duplicate step hashes across subs are independently approvable. (§Y.2)
- **AC 43:** Concurrent comment replies cannot bypass depth <= 5. (§Y.3)
- **AC 44:** `consumed_at IS NULL` is the sole unconsumed-grant convention. (§Y.4)
- **AC 45:** SourceCodeAgent is enabled by default; if explicitly disabled, source-code target creation remains compatible and launch returns 501. (§Y.5)
- **AC 46:** Single-target fast path is optional and output-compatible with hierarchical path. (§Y.6)
- **AC 47:** Deployment docs and startup warning communicate single-worker MVP requirement. (§Y.7)

---

## §Y.9 Implementation start marker

With v3.1.7 applied, all verification items from `PLAN-VERIFICATION-2026-05-10.md` are addressed:
- §A HIGH -> v3.1.4
- §B HIGH-MED -> v3.1.5
- §C MED-LOW -> v3.1.6
- §D LOW + §E pre-mortem -> v3.1.7

Implementation may begin with Phase 5.1 Schema & Migrations, using the cumulative precedence:

`v3.1.7 §Y > v3.1.6 §X > v3.1.5 §W > v3.1.4 §V > v3.1 §A–§T > v3.0 §0–§8 > v2.1 baseline`.

---

## Iteration Changelog

- **v3.1.7-rev2** (2026-05-10): Critic follow-up — §Y.7 worker env parsing is explicitly non-fatal; non-integer `UVICORN_WORKERS`/`WEB_CONCURRENCY` values warn and continue rather than hard-failing startup.
- **v3.1.7-rev1** (2026-05-10): Critic blocking edit applied — approval flow is now sub-specific end-to-end (`sub_id` in API body, `approval_grants`, uniqueness, ApprovalGate lookup, and registry notification); old approval body shape retained only as an unambiguous shim. §Y.7 startup guard now checks both `UVICORN_WORKERS` and `WEB_CONCURRENCY` and explicitly supersedes v3.1 §R hard assertion with warning-only MVP guard.
- **v3.1.7** (2026-05-10): Final pre-implementation clarification patch. Resolves §D LOW and §E pre-mortem additions: `approval_grants.created_at`, canonical registry routing with `sub_id`, comment depth race convention, nullable `consumed_at`, explicit SourceCodeAgent fallback gate, optional single-target fast path, and single-worker deployment warning.
