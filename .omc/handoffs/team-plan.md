## Handoff: team-plan → team-exec (Wave 1: Group A)

- **Decided**: Execute the APPROVED consensus plan `.omc/plans/ralplan-osa-flow-interactive-pentest-v1.md` in waves matching its flag-gated rollout: **A → migration 013 → C → B → D**. Task-storage fork resolved = **Option 1 (additive `task_events` for v1)**; do NOT collapse into AgentExecution (v2 only). Wave 1 = Group A only, verified live before Wave 2.
- **Wave-1 tasks (Group A, no migration, no flag)**:
  - A1 FlowIndex project routing + lightweight picker (`frontend/src/pages/FlowIndex.tsx:63-71,92-100`): both `navigate('/pentest-sessions/new')` calls must attach `?project=` (auto-select if exactly one project; picker if several; create-project if none).
  - A2 fail-loud submit guard (`frontend/src/pages/PentestWorkflow.tsx:400-403`): replace silent `return` with visible inline error.
  - A3 confirm Copilot soft-gate already dismissible (`CopilotConnectModal.tsx:155,209-211`; submit disabled only on `!draftPrompt.trim()` at `PentestWorkflow.tsx:894`).
  - A5 axios timeout (`frontend/src/api/client.ts:3`), e.g. 60s.
  - A4 (backend) graceful `CredentialNotFound` at first interview turn → mirror `ModelUnreachable`: because `get_db` rolls back on raise, persist `status='interview_paused'` on a **separate short-lived committed `async_session()`** BEFORE raising `HTTPException(503, credential_required)`. Files: `backend/app/orchestrator/workflow_service.py` (flag-ON branch ~372-408, flag-OFF ~464-491), `credential_resolver.py:24`.
- **Rejected**: collapsing task_events (v2); adding a migration inside Group A (Group A must work on existing schema — A4 uses existing `interview_paused` status; defer `resume_token`/`pending_asks` writes to when migration 013 lands).
- **Risks**: A1 project-fetch/picker must handle 0/1/many projects; A4 must actually COMMIT the paused state (a `flush()` under `get_db` is rolled back). A1+A2 both touch `PentestWorkflow.tsx` → single frontend owner to avoid conflicts.
- **Files**: FlowIndex.tsx, PentestWorkflow.tsx, api/client.ts (worker-1); workflow_service.py, credential_resolver.py (worker-2).
- **Remaining**: verify (tsc, backend suite flags-OFF, live smoke AC-1.1..1.5), then Waves 2-5.
