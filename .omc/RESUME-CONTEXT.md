# Resume Context — OSA Platform v3.1.3

**Purpose:** Auto-compact survival doc. After context compaction, re-load files in §1 in this exact order before continuing work.

**Last updated:** 2026-05-10 (Copilot CLI session 272ff947)
**Source repo cwd:** `/Users/chrisjung/myproject/offensive-security/offensive-security` (nested git root)
**Plans/specs root:** `/Users/chrisjung/myproject/offensive-security/.omc/`

---

## 1. Required Reading on Resume (in order)

| # | Path | Why |
|---|------|-----|
| 1 | `.omc/RESUME-CONTEXT.md` (this file) | Roadmap |
| 2 | `.omc/specs/deep-interview-offensive-security-agent.md` | Locked decisions, 11 entities, AC list, ambiguity 14.5% |
| 3 | `.omc/plans/offensive-security-agent-consensus.md` | **v2.1 baseline** = currently implemented (85/85 tests) |
| 4 | `.omc/plans/offensive-security-agent-consensus-v3.md` | **v3.0 base plan** (§0–§8) |
| 5 | `.omc/plans/offensive-security-agent-consensus-v3.1.md` | **v3.1+v3.1.3 revisions** (§A–§T) — supersedes v3.0 in amended sections |
| 6 | `.omc/PLAN-VERIFICATION-2026-05-10.md` | Latest verification findings (this session) |
| 7 | `.omc/state/mission-state.json` | Last orchestration mission state |
| 8 | `.omc/project-memory.json` | Project hot-paths and structure inventory |

**Companion rule (from v3.1 header):** sections in v3.1 amend v3.0; sections not amended remain in force unchanged. v2.1 is the executing baseline.

---

## 2. Plan Hierarchy (read-merge order)

```
v3.1 (§A–§T)  ─ amends ─▶  v3.0 (§0–§8)  ─ extends ─▶  v2.1 (implemented)
```

When a topic appears in multiple plans, **v3.1 wins, then v3.0, then v2.1**.

---

## 3. Locked Decisions (do NOT relitigate)

From deep-interview Round 1–10 (ambiguity 14.5%) + v3.0 architect/critic rounds:

- Domain agents (Application/Web/Cloud-Azure/SourceCode) **replace** tool agents publicly
- Hierarchical orchestrator + Blackboard (asyncio MVP, Redis Phase-2)
- Azure full scope including priv-esc (gated by ApprovalGate)
- Source-code via Git URL clone-in-container
- Multi-target single project, per-target `scope_rules`
- Collab UI: 4 components (CommentThread / FindingAnnotation / ActivityTimeline / TargetCard)
- Dedicated periodic Health agent (30s)
- All-in-one MVP (no Celery, no microservices, no Kubernetes)
- Encrypted credentials at-rest (AES-GCM) + role-gated CRUD
- Parallel default with concurrency limit on `projects.max_concurrent_domains`
- Tool agents internalized to `app/agents/_tools/` with re-export shims (preserves 85 tests)
- **Single uvicorn worker MVP constraint** (§R) — startup assertion enforces

---

## 4. Open Items / Verification Findings

See `.omc/PLAN-VERIFICATION-2026-05-10.md` for the latest pass.

---

## 5. Current Implementation Snapshot

- `backend/app/{agents,api,core,models,orchestrator,reports,safety}/` — v2.1 baseline
- `backend/tests/{unit,integration,e2e}/` — 85 tests passing
- `frontend/src/{api,hooks,pages}/` — v2.1 React UI
- `docker-compose.yml`, `backend/Dockerfile`, `backend/alembic/versions/001_initial.py`

**Not yet present (v3 work):**
- `app/agents/domain/` (4 domain agents)
- `app/agents/_tools/` (moved tool adapters + shims)
- `app/orchestrator/{master.py, sub_orchestrator.py, blackboard.py}`
- `app/safety/{azure_scope.py, approval_gate.py, secret_scrubber.py, dns_resolver.py}`
- `app/services/{credentials.py, comments.py, activity.py}`
- `app/agents/health.py`
- `app/core/crypto.py`
- Migrations 003 / 003b / 004 / 005 / 006

---

## 6. Quick Resume Commands

```bash
# Verify v2.1 baseline still green
cd backend && pytest -q

# Re-load context on a fresh session
view .omc/RESUME-CONTEXT.md
view .omc/PLAN-VERIFICATION-2026-05-10.md
```
