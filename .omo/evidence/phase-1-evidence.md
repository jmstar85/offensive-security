# Phase 1 (P0 security) verification evidence

Repo: /Users/minsung.jung/myproject/offensive-security
Base: 9414dad (verified Phase 0 commit) on feat/phase-0-repo-baseline
Work branch: feat/phase-1-p0-security
Env (all runs): cd backend; PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:.venv/lib/python3.13/site-packages OSA_E2E_DOCKER_SCANME=0 OSA_E2E_DVWA_URL='' OSA_E2E_JUICE_URL='' /Users/minsung.jung/.local/bin/python3.13

## Recovery context
Two deep-high children (1-a authz/masking, 1-c rescope) hit a gpt-6-astra usage limit and died leaving ONLY reproduction tests (no production edits). 1-b was complete. The reproduction tests were preserved as the contract and the production fixes implemented here. Two test-scaffolding bugs in the dead children's files were corrected (not weakenings): a fake Client.send built Response(text=...) missing its 3 required fields; and the lane-stub tuples were updated to the new 4-tuple.

## 1-a — session/project/team authorization + stored-history masking
Production: backend/app/api/v1/pentest_sessions.py
- _authorize_session(db, session_id, current_user): resolves session -> project -> project.created_by (owner) -> owner.team_id. Global ADMIN bypasses; any other cross-team caller gets 404 (never discloses existence). The session's cached team_id is deliberately NOT trusted (test poisons it).
- _scrub_payload/_scrub_model: recursive scrub of string leaves reusing ConversationScrubber on READ responses; numeric metadata (ambiguity, token usage) is preserved. Applied to get_session, list_messages, list_msgchains. Guard applied to those plus list_pending_rescopes and approval_preview.
- WS scrubbed/raw contract untouched.
Tests (real ASGI HTTP + signed JWT + real DB): tests/integration/history_security/ -> 33 passed. Covers cross-team 403/404 (outsider, other_team_admin) across ["", /messages, /msgchains, /rescope-pending, /approval-preview]; same-team owner/member/team_admin + global admin 200; missing session 404 on all child collections; pre-existing RAW rows masked on session/messages/msgchains with numeric fields (ambiguity 0.25, usage input_tokens 17) preserved.

## 1-b — single ambiguity threshold source
Production: backend/app/orchestrator/ambiguity_loop.py::_decide_next_state now calls workflow_service.interview_ambiguity_target() (the same effective policy the API/UI advertise) instead of reading settings.workflow_ambiguity_threshold directly. autoblock(0.20)/legacy(0.35) toggle honored at one source.
Tests: tests/unit/test_interview_autoblock.py + tests/integration/test_workflow_service_flag_on.py (added parametrized real-Flow target test) + tests/integration/test_ambiguity_loop_full.py -> green. Manual: real WorkflowService->AmbiguityLoop->SQLite, displayed target 0.20, score 0.30 interviewing -> 0.20 ready_for_review.

## 1-c — rescope pause -> approval -> resume (both lanes), no failed misclassification
Root defect: execution lanes persist status="running" but RescopeService.pause_for_rescope only accepted "executing", so the pause call 409'd and was swallowed; both steps ran to completed.
Production:
- rescope_service.py: pause guard now accepts {running, executing, paused_for_rescope} (vocabulary reconciliation).
- performer.py: PerformerSession.paused_for_rescope flag; _dispatch_tool fail-closes on it (no adapter reach after a pause); _execute_step_through_helper sets it when a pause fires and guards re-entry.
- service.py: _run_autonomous_lane returns a 4-tuple (…, paused); a Pentester error=="paused_for_rescope" is excluded from abort classification; run() PARKS the session (commits, audits session_paused_for_rescope, returns) without finalize/report when paused and not killed (kill still wins).
- executor.py (deterministic lane): PlanExecutor.paused_for_rescope set at the pause-return; run() reads it to park.
Tests: tests/integration/test_rescope_execution_lifecycle.py -> 3 passed (deterministic + autonomous pause-before-later-steps: status paused_for_rescope, ended_at None, calls==[origin.example], 1 completed AgentExecution, no Report; performer refuses late dispatch after pause). Manual (real RescopeService + DB): running->pause->approve->executing (ended_at None); reject-all->killed, never failed.

## Full suite (single run) + diagnostics
Full documented backend suite, single run: 1385 passed, 6 skipped, 0 failed.
Changed-file type diagnostics (standalone basedpyright 1.40.2, explicit site-packages config): modified tree = 34 errors; baseline HEAD = 34 errors; identical per-file class/count (executor 9, service 8, pentest_sessions 7, rescope_service 4, performer 6). ZERO new type errors introduced — all 34 are pre-existing repo-wide weak-typing (bare dict/list generics, Literal.value, RescopeApproval attr assignment, datetime|None, str|None), out of scope for this phase (Phase 0 precedent: preserve pre-existing, do not expand into a typing refactor).

## Changed files (production)
- backend/app/api/v1/pentest_sessions.py
- backend/app/orchestrator/ambiguity_loop.py
- backend/app/orchestrator/executor.py
- backend/app/orchestrator/performer.py
- backend/app/orchestrator/rescope_service.py
- backend/app/orchestrator/service.py
## Changed files (tests)
- backend/tests/integration/history_security/ (new: __init__, conftest, test_access, test_history)
- backend/tests/integration/test_rescope_execution_lifecycle.py (new)
- backend/tests/integration/test_workflow_service_flag_on.py (added real-Flow target test)
- backend/tests/integration/test_ambiguity_loop_full.py (threshold anchor)
- backend/tests/api/test_pentest_sessions_create.py, tests/api/test_pentest_execution_launcher.py (4-tuple lane contract)
- backend/tests/integration/test_msgchains_endpoint.py, tests/integration/test_pentest_messages_history.py (authorized reader)

## Residual / not-tested
- Real Docker-daemon-present execution not exercised (no socket locally; Phase 0 guard skips).
- 34 pre-existing basedpyright errors retained unchanged.
- decide_rescope resumes the session to status="executing"; actual re-drive of remaining steps by a background worker is Phase 2 (durable re-drive) scope.


---

## Gate-review remediation (REJECT -> fixes) — round 2

The first separate gate review REJECTed with 7 blockers; all are addressed:

- B1 (alt session routes leaked cross-team): the legacy /sessions router now enforces the SAME authoritative project-owner-team authz + masking as /pentest-sessions, via one shared module app/api/v1/_session_security.py. get_session/get_executions/get_terminal authorize + mask; list_sessions is scoped to accessible_session_ids; the obsolete cached-team helper was removed. New test: history_security/test_sibling_routes.py (cross-team 404 even with a POISONED session.team_id, list excludes other team, member reads masked, terminal masked).
- B2 (paused re-entry / duplicate launch false-completed): OrchestratorService.run refuses a paused_for_rescope session at entry (no reset to running); PlanExecutor.execute fail-closes on a re-entered paused instance. Tests: test_same_executor_reentry_after_pause_is_fail_closed, test_duplicate_launch_while_paused_never_completes.
- B3 (storage + live response unmasked): masking now also runs at the persistence boundaries (Performer._persist_msgchain_end, AmbiguityLoop WorkflowMessage/MsgChain) and the live POST /messages response, via the safety-layer app/safety/history_masking.py (reused by api + orchestrator; no orchestrator->api import). The raw WebSocket topic is untouched (in-memory raw_text, published before persistence). Test: test_flow_turn_scrubs_persisted_conversation.
- B4 (approval never resumed execution): decide_rescope endpoint, on an approved resume (status executing), merges accepted hosts into the project whitelist's tier allow-field (RescopeService._merge_accepted_scope) and schedules the shared launcher; the deterministic lane skips already-completed steps (resume-from-offset, caller-injected so mock/replay callers are unaffected), the autonomous lane re-drives (plan_json tagged _autonomous_lane so a resume re-enters the autonomous lane instead of flipping to saved-workflow). Test: test_approved_rescope_resumes_and_completes[deterministic|autonomous] observes the later adapter call + completion; reject-all still kills.
- B5 (masking corrupted JSON envelopes): scrub_text parses a JSON-string leaf, scrubs its leaves, and re-serializes, so an envelope stays valid JSON with numbers preserved. Test: test_history_masking_preserves_json_for_password_secret.
- B6 (paused role persisted as failed): Performer marks a paused role chain status "paused" (not "failed") and logs info, not error. Test: test_autonomous_paused_pentester_chain_not_marked_failed.
- B7 (new diagnostics): the ambiguity_loop->workflow_service import cycle is broken with a function-local import (reportImportCycles now 0); the msgchains fixture return annotation is a 3-tuple (test file 0 errors); new bare set/dict annotations in executor were parameterized.

Final verification (round 2):
- Full backend suite single run: 1398 passed, 6 skipped (1385 + 13 new blocker regressions).
- Changed-file diagnostics (basedpyright, /tmp/osa-phase1-pyrightconfig.json): original six files back to 34 (== baseline, zero new); two new modules 0 errors; app/api/v1/sessions.py has 2 PRE-EXISTING bare-dict model annotations (present before this diff, preserved per the review's "do not expand into a typing cleanup"). reportImportCycles = 0.
- Both execution lanes: request -> pause -> approve -> resume-to-completion and reject -> killed verified by the real-launcher lifecycle tests; pause never classified failed/completed.


---

## Re-review remediation (round 2 REJECT -> fixes) — B2/B3/B4/B7

- B2: run() now loads the session and refuses a paused_for_rescope invocation BEFORE the rate-limit branch, so repeated duplicate launches (even past the rate limit) leave the session paused with its approval pending, never finalized failed. Test: repeated/duplicate launch stays paused.
- B3: the user-turn write and the legacy (flag-off) assistant write + its blockers/reasoning metadata are now scrubbed at persistence via app/safety/history_masking.scrub_json_str. Test: test_conversation_masked_at_storage_both_modes injects a secret in the USER message and asserts every committed WorkflowMessage/MsgChain row + metadata is masked in BOTH flow and legacy modes.
- B4: deterministic resume skips by stable completion COUNT (position), not the non-unique display 'order', so two distinct steps sharing order 1 both run; prior completed findings are carried into the resumed report. Autonomous resume seeds prior completed tool-results + findings (service._autonomous_prior) so the Pentester CONTINUES (a resume note lists completed work) instead of restarting. Tests use a request-driven model fake (decides only from the supplied conversation) and assert the EXACT trace [origin, next] with no re-scan, plus a duplicate-order case.
- B7: interview_ambiguity_target moved to a neutral module app/orchestrator/interview_policy.py imported by both workflow_service and ambiguity_loop, so the module dependency cycle is gone (reportImportCycles = 0). The B7-table test errors (typed inserts, dict[str,str] headers, Request/BackgroundTasks, ModelClient doubles) are corrected; new production helper annotations are parameterized (dict[str, Any]) with typing.Any imported.

Final verification (round 2b): full backend suite 1400 passed, 6 skipped in a single run. Changed-file diagnostics: the six pre-existing production files total 34 (== baseline, zero new), import cycle 0, the four previously-flagged test files 0 errors; remaining errors in other changed test files (test_pentest_sessions_create, test_pentest_messages_history, test_terminal_replay, test_pentest_execution_launcher) are pre-existing untyped-mock patterns not introduced by this diff.
