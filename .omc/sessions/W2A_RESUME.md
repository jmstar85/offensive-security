# OSA → XBOW Transition: Session Resume State (W2A entry)

**Generated**: 2026-05-31
**Branch**: `feat/kali-coexistence-v1` (off `main` baseline `b954060`)
**Plan source of truth**: [.omc/plans/ralplan-osa-xbow-v1.md](.omc/plans/ralplan-osa-xbow-v1.md) (RALPLAN-DR v1.1, 404 lines)
**Test count**: **632 passed + 3 skipped** (pre-W2a baseline)

---

## 1. Where we are

| Wave | Status | Commits |
|------|--------|---------|
| Pre-v1.1 Kali coexistence + v1.1-#1/2/3/4 fixes | Already on branch | 25+ commits ending `7a50f79` |
| **W0** + **W0.5** (CI invariants + comparator + CODEOWNERS + AST + fuzz) | ✅ DONE | `54f8f74`, `4152cdd`, `b400a02`, `c5803cb`, `5582983`, `3789e1e`, `e07d4ef`, `b622d2d` |
| **W1** (Multi-LLM + Credential Vault + 2-layer Budget + TEAM_ADMIN role) | ✅ DONE | `188b18e`, `5437126`, `648eb99`, `46a65b7`, `daeb743`, `8ca8e4f`, `246906c`, `075aca8` |
| **W2a** (Coordinator façade + Conversation topic + Scrubber) | ▶ NEXT | — |
| W2b, W3, W4, W5 | Pending | — |

---

## 2. v1.1 Critic items — status

### Resolved in plan v1.1 (visible in [.omc/plans/ralplan-osa-xbow-v1.md](.omc/plans/ralplan-osa-xbow-v1.md))
- **MF-CRITIC-1** — saved-workflow opt-out (`Workflow.skip_coordinator_replay` + `osa_coordinator_replay_enabled`) + `coordinator.replay_drift_detected` audit on Jaccard < 0.6 target divergence
- **MF-CRITIC-4** — `UserRole.TEAM_ADMIN` enum — **landed in W1/PR1.0 `188b18e`**
- **MF-CRITIC-7** — L2 FPR measurement gate (PR2a.4a inserted before PR2a.4) on DVWA + Juice Shop golden corpus
- **SF-CRITIC-1** — W0.5 deprioritised (load harness moved to W2b/PR2b.6; W0.5 keeps only flag-fuzz)

### Still in ADR Follow-ups (per-wave absorption)
- **MF-CRITIC-2** — contextvars spike — landed in W0/PR0.0 `4152cdd`
- **MF-CRITIC-3** — docker-socket-proxy runtime assertion mechanism — for W3
- **MF-CRITIC-5** — scrubber L2 entropy threshold measurement — **lands in W2a/PR2a.4a**
- **MF-CRITIC-6** — incremental_addon risk/effort re-rating (no PR; doc note)
- **MF-CRITIC-8** — pairwise prereq matrix vs 4-tuple — doc PR5.3
- **MF-CRITIC-9** — canary determinism test — **lands in W2a/PR2a.4** as `test_canary_determinism.py`
- SF-CRITIC-2..9 — absorbed into per-wave AC during execution

---

## 3. Hard-won execution pattern (W0 + W1 verified)

**Worker Bash hook is BLOCKED at the sub-agent level** in this environment.
- Workers (Agent calls with `subagent_type=oh-my-claudecode:executor`) can use **Write/Edit/Read** freely but every Bash invocation returns "Permission for this tool use was denied".
- **Lead (main session) MUST run `pytest`, `git add`, `git commit` on behalf of each worker.**
- Worker briefs MUST tell them "Do NOT attempt Bash. Write files only. Lead will run pytest + commit." — saves them wasted tool calls.

**Common test-fixture problems we already debugged twice (W1):**
- SQLAlchemy `default=uuid.uuid4` for `id` and `server_default=func.now()` for `created_at` are populated at FLUSH time, not at __init__. Mocked `_FakeDB.flush()` must mirror this:
  ```python
  async def flush(self):
      from datetime import datetime, timezone
      for o in self._added:
          if getattr(o, "id", None) is None:
              o.id = uuid.uuid4()
          if getattr(o, "created_at", None) is None:
              o.created_at = datetime.now(timezone.utc)
  ```
- `asyncio.get_event_loop().run_until_complete(...)` is fragile under pytest-asyncio mode=auto. Use **`asyncio.run(...)`** instead.

**Stable W0 + W1 invariants (already merged) include:**
- Safety chain: `filter_plan_steps` → `filter_by_tier_flags` → `RiskFilter` → `WhitelistShim` → `KaliBackend` hardening → `socket_proxy_filter IMAGE_REGEX` → audit_kali.* events
- Image regex pinned to `^osa-kali(?:[:@].+)?$` (1 namespace). AST guards in `backend/tests/ast/` lock the shape.
- CODEOWNERS at `.github/CODEOWNERS` covers safety/sidecar/IMAGE_REGEX placeholders; `backend/tests/infra/test_codeowners_coverage.py` covers 16 guarded paths.
- 4 supported flag tuples T1..T4 enforced in `environment="production"` only (W0/PR0.4 `e07d4ef`).
- N=20 contextvars + LLMRouter + per-user Fernet vault all wired (W1).

---

## 4. W2a — Coordinator façade (fresh-plan ONLY) + Conversation + Scrubber

Per [.omc/plans/ralplan-osa-xbow-v1.md](.omc/plans/ralplan-osa-xbow-v1.md) §Phase 2a (lines ~253-262).

### PR list (6 + 1 measurement gate)

| PR | Scope | New files / key edits |
|----|-------|----------------------|
| **PR2a.1** feat(db) | `PentestSession.understanding_json` + `plan_of_work_json` + `coordinator_revision_no` + `llm_provider_pref` JSONB columns; `agent_family_instance` table | Alembic migration `010_xbow_w2_coordinator.py`; extend `backend/app/models/session.py`; new `backend/app/models/agent_family.py` |
| **PR2a.2** feat(orchestrator) | `CoordinatorService.run` + `UnderstandingBuilder` + `PlanOfWorkBuilder`; Pydantic `UnderstandingOfTarget` + `PlanOfWork` models; `topic='coordinator'` event schemas; `ReplayLaneViolation` defense-in-depth | `backend/app/orchestrator/coordinator.py` (placeholder CODEOWNERS already in place from W0/PR0.3) |
| **PR2a.3** feat(orchestrator) | Hook `CoordinatorService` into `OrchestratorService.run` AFTER Layer-1 whitelist; lane discriminator (fresh-plan OR opt-in saved-workflow per MF-CRITIC-1 v1.1); audit `coordinator.skipped_for_replay_lane` / `coordinator.replay_drift_detected` | Edit `backend/app/orchestrator/service.py` |
| **PR2a.4a** test(safety) NEW v1.1 | L2 Shannon-entropy FPR measurement on DVWA + Juice Shop golden corpus. **AC: L2 FPR < 1.0% MEASURED**. If ≥ 1%: raise L4 threshold with derivation OR defer L2 to v2.1 | `backend/tests/safety/test_l2_entropy_fpr.py` + 1h replay corpus from golden traces |
| **PR2a.4** feat(safety) | `backend/app/safety/conversation_scrubber.py` with L1 pattern + L2 Shannon-entropy + L3 per-session canary + L4 token-bucket circuit-breaker. Audit schemas `conversation.scrubbed` / `canary_leak` / `scrub_circuit_open`. Depends on PR2a.4a outcome. + `tests/unit/test_canary_determinism.py` (MF-CRITIC-9) | New `conversation_scrubber.py` + `tests/unit/test_conversation_scrubber.py` |
| **PR2a.5** feat(observability) | `Performer.run_session` publishes Role-turn messages to `topic='conversation'` (scrubbed) + `topic='raw_conversation'` (UNSCRUBBED, gated on `UserRole.TEAM_ADMIN` from W1/PR1.0). MsgChain persists scrubbed only. token-bucket rate-limiter 50 events/sec/session (oldest-dropped per SF-CRITIC-9). New endpoints: `GET /pentest-sessions/{id}/understanding` + `/plan-of-work` + `/agent-families` + admin `POST /enrich-understanding` | Edit `backend/app/orchestrator/performer.py`; new `backend/app/api/v1/coordinator.py` |
| **PR2a.6** feat(ui) | `/coordinator/:sessionId` page + LeftPane `UnderstandingPanel` + `PlanOfWorkPanel` cards + RightPane Conversation tab + raw_conversation tab gated to TEAM_ADMIN. Flag-gated by `osa_coordinator_enabled` (NO family tree yet — that's W2b) | New `frontend/src/pages/CoordinatorPage.tsx` + `frontend/src/components/coordinator/{UnderstandingPanel,PlanOfWorkPanel,ConversationTab,RawConversationTab}.tsx` + sidebar entry + featureFlags extension |

### W2a Gate (mandatory before W2b)

- `tests/integration/test_coordinator_safety_chain.py` — every Coordinator-spawned step still traverses the full safety chain
- `tests/integration/test_saved_workflow_coordinator_skipped.py` (MF1 default) — spy harness asserts `CoordinatorService.run` NEVER invoked when both opt-in conditions absent
- `tests/integration/test_coordinator_replay_opt_in.py` (MF1 opt-in, v1.1 NEW) — both flag+column set → run; saved `plan_json` byte-equal before/after; drift audit fires when Jaccard < 0.6
- `tests/integration/test_saved_workflow_coordinator_llm_unreachable.py` — replay on LLM-down gracefully no-ops
- `tests/integration/test_enrich_understanding_admin_endpoint.py` — admin-only audit
- `tests/unit/test_conversation_scrubber.py` (MF4) — all 4 layers + adversarial fixtures + L2 FPR < 1% measured
- `tests/unit/test_canary_determinism.py` (MF-CRITIC-9) — Coordinator output (stripping canary) byte-identical between canary on/off
- `tests/safety/test_understanding_json_prompt_injection.py` (SF2) — passive_recon/wappalyzer output cannot escape mode discrimination
- `tests/safety/test_raw_conversation_access_control.py` (SF4) — non-TEAM_ADMIN → close 4003, accept_raw=false → close 4003, no cross-topic bleed
- `tests/regression/test_v11_byte_identical.py` with T1 all green

**Staging soak (24h)**: `osa_coordinator_enabled=true` (NOT T3 yet — families OFF), 50 fresh-plan sessions across all 13 legacy slugs + 50 saved-workflow replays, zero shim_block bypass, zero L3 canary leaks.

---

## 5. W2a worker decomposition plan

Use the SAME pattern as W1 (5 workers, Lead handles Bash):

| Worker | PRs | Files |
|--------|-----|-------|
| worker-1 | PR2a.1 | `backend/app/models/session.py` (add 4 columns) + `backend/app/models/agent_family.py` (new) + Alembic 010 + tests |
| worker-2 | PR2a.2 + PR2a.3 | `backend/app/orchestrator/coordinator.py` (new) + Pydantic models + edits to `service.py` + `ReplayLaneViolation` + 5 tests |
| worker-3 | PR2a.4a + PR2a.4 (MF-CRITIC-5/7/9) | `backend/app/safety/conversation_scrubber.py` + golden corpus L2 FPR measurement + `test_canary_determinism` + `test_conversation_scrubber` (4 layers + adversarial) |
| worker-4 | PR2a.5 | Edit `performer.py` (conversation + raw_conversation publish), new `backend/app/api/v1/coordinator.py` (4 endpoints), token-bucket rate-limiter, scope-drift on raw_conversation subscribers, audit schemas |
| worker-5 | PR2a.6 | New `frontend/src/pages/CoordinatorPage.tsx` + 4 components in `frontend/src/components/coordinator/` + sidebar gated on `osa_coordinator_enabled` + featureFlags extension + App.tsx route |

### Worker brief boilerplate (W2a)

```
You are TEAMMATE "worker-N" in team "xbow-w2a". Report to "team-lead". Do NOT spawn subagents.

CRITICAL: Bash tool is BLOCKED for sub-agents. Do NOT attempt pytest, git, or any shell command.
Write all files cleanly. Team-lead will run pytest + git commit on your behalf.
Communicate completion via SendMessage (to=team-lead, summary≤10 words, content=full file checklist).

Plan reference: /Users/minsung.jung/myproject/offensive-security/.omc/plans/ralplan-osa-xbow-v1.md (W2a Phase 2a)
Branch: feat/kali-coexistence-v1 (single branch, append commits)
Test pattern: use AsyncMock/MagicMock; _FakeDB.flush() MUST mirror SQLAlchemy default-population
                (set obj.id=uuid.uuid4(), obj.created_at=datetime.now(timezone.utc) for missing fields)
Async pattern: use asyncio.run(...) — NOT asyncio.get_event_loop().run_until_complete(...)

═══ YOUR SCOPE ═══
<PR-specific brief>

═══ HARD RULES ═══
- Do NOT modify backend/app/safety/*.py UNLESS your scope explicitly includes conversation_scrubber.py
- All file paths are ABSOLUTE in Read/Write/Edit calls
- No Bash. No git. No pytest.
- SendMessage when done with full file checklist + paths + flag fields completed
```

---

## 6. Quick verify commands (Lead-side)

```bash
# Quick regression after each PR commit (Lead runs):
cd /Users/minsung.jung/myproject/offensive-security/backend && \
  .venv/bin/python -m pytest tests/ -q --ignore=tests/unit/test_planner_v2.py | tail -5

# W2a-specific gate matrix (run after all 7 PRs land):
cd /Users/minsung.jung/myproject/offensive-security/backend && \
  .venv/bin/python -m pytest \
    tests/integration/test_coordinator_safety_chain.py \
    tests/integration/test_saved_workflow_coordinator_skipped.py \
    tests/integration/test_coordinator_replay_opt_in.py \
    tests/integration/test_saved_workflow_coordinator_llm_unreachable.py \
    tests/integration/test_enrich_understanding_admin_endpoint.py \
    tests/unit/test_conversation_scrubber.py \
    tests/unit/test_canary_determinism.py \
    tests/safety/test_understanding_json_prompt_injection.py \
    tests/safety/test_raw_conversation_access_control.py \
    tests/safety/test_l2_entropy_fpr.py \
    tests/regression/test_v11_byte_identical.py \
    --no-header -q
```

---

## 7. Resume protocol after compaction

When the new context starts:
1. Read this file in full: `cat /Users/minsung.jung/myproject/offensive-security/.omc/sessions/W2A_RESUME.md`
2. Confirm branch + test count: `git log --oneline ^main | head -10` and `cd backend && .venv/bin/python -m pytest tests/ -q --ignore=tests/unit/test_planner_v2.py | tail -3`
3. Spawn `xbow-w2a` team with 5 workers per §5 above
4. After each worker reports completion via SendMessage, Lead absorbs files + commits per PR in dependency order
5. Run W2a gate matrix, shutdown + TeamDelete + state_clear when green
