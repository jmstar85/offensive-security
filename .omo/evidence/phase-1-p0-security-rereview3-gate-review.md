# Phase 1 P0 security: independent gate re-review (round 3)

<verdict>APPROVE</verdict>
<confidence>high</confidence>
<summary>The four previously-unresolved blockers (B2/B3/B4/B7) are now genuinely fixed and independently reproduced from the artifacts, not accepted from prose. A paused run refused across more launches than the rate limit stays paused_for_rescope with its approval pending and ended_at null (never failed). User-turn and legacy-assistant conversation writes are scrubbed at the real persistence boundary in both flow modes. Approval through the real route resumes both lanes, runs only the remaining accepted work with no re-scan, and keeps prior findings in the report. The ambiguity import cycle is gone and the six production files total the baseline 34 errors with the previously-flagged test-file errors cleared. B1/B5/B6 remain resolved with their regressions green. Full suite: 1400 passed, 6 skipped, single run.</summary>

recommendation: APPROVE

originalIntent: Complete Phase 1 before Phase 2 — enforce authoritative project-owner-team isolation on session history, mask stored and returned conversations while preserving the privileged raw WebSocket stream, make the real interview use the advertised ambiguity target, and make both execution lanes durably pause and continue only remaining work after an operator decision.

desiredOutcome: Authorized teammates read sanitized conversations; other teams cannot obtain them through either router. A discovered out-of-scope host parks the run without a terminal report or failure, even under repeated/stale launches. Approval continues the original engagement without dropping or repeating work; rejection kills it. No new type diagnostics attributable to the diff.

userOutcomeReview: SATISFIED. Round 2 left four criterion-linked failures: a paused run could still be finalized `failed` by launches that exhausted the rate limit; the user-turn and flag-off assistant writes still stored secrets; continuation skipped work / restarted / dropped findings; and the import cycle plus new test-file type errors remained. Round-2b remediation addresses each at the correct seam and the fixes are independently reproduced below. The remaining items the earlier reviews named (optimal architecture, broader typing cleanup, live container/browser runs) are out of the stated Phase 1 criteria and are NOTES, not blockers.

## Scope and provenance

- Branch `feat/phase-1-p0-security`; HEAD `9414dad3097fc823d9bb882e435e9cd098df711d` (confirmed), all changes uncommitted in the working tree.
- Read both prior reviews, the executor evidence (`phase-1-evidence.md` round-2b section), `docs/phases/README.md`, and `docs/phases/phase-1-p0-security.md`.
- Inspected the working-tree diff (`GIT_PAGER=cat git diff HEAD -- backend`) and read the new untracked files in full: `backend/app/orchestrator/interview_policy.py`, `backend/app/safety/history_masking.py`, `backend/app/api/v1/_session_security.py`, the `backend/tests/integration/history_security/` suite, and `backend/tests/integration/test_rescope_execution_lifecycle.py`.
- No edits, staging, commits, branch changes, or installs by this reviewer. This report is the only authored file. `GIT_PAGER=cat` used throughout.
- Criterion IDs below are reviewer labels for the supplied requirements.

## B2/B3/B4/B7 resolution table

| Prior blocker | Resolved? | Independently checked evidence |
| --- | --- | --- |
| B2: paused re-entry / false completion under repeated launch | RESOLVED | `service.py` `run()` loads the session and refuses `paused_for_rescope` BEFORE the rate-limit branch (diff: paused-check returns with `run_refused_paused_for_rescope` audit, then `_check_rate_limit`). Direct reproduction: `max_prompts_per_minute=5`; one initial pause + 7 duplicate launches → statuses all `paused_for_rescope`, pending approvals = 1, `ended_at = None`. Never `failed`/`completed`. |
| B3: storage masking of user + legacy-assistant writes | RESOLVED | `workflow_service.py:433` user write `content=scrub_json_str(session.id, user_message)`; `:732-741` assistant content + `blockers_json.items`/`reasoning` scrubbed; `ambiguity_loop.py` and `performer._persist_msgchain_end` scrub `messages_json`. `test_conversation_masked_at_storage_both_modes` injects the secret in the USER message and asserts every committed WorkflowMessage/MsgChain + metadata is masked in BOTH flow-on and flag-off modes — passes. |
| B4: approval resumes both lanes, no skip/repeat/finding-loss | RESOLVED | Deterministic resume skips by stable completion COUNT (`executor._resume_progress`), not display `order`, and seeds `prior_findings`; autonomous seeds `prior_tool_results`+findings (`service._autonomous_prior`) and the Pentester gets a "do NOT repeat" continuation note. Lifecycle tests use a request-driven model fake that decides only from the supplied conversation. Direct reproduction (deterministic): approve via the real `decide_rescope` route → trace `[origin.example, next.example]` (no re-scan), status `completed`, committed Report contains BOTH findings (`total: 2`). Duplicate-order and autonomous cases pass in the suite. |
| B7: import cycle + new test-file type errors | RESOLVED | `interview_ambiguity_target` moved to neutral `interview_policy.py` imported by both `workflow_service` and `ambiguity_loop`. basedpyright over the six production files with `/tmp/osa-phase1-pyrightconfig.json`: **34 errors, 0 warnings**, no `reportImportCycles` present; all 34 are pre-existing weak-typing (bare generics, Literal.value, RescopeApproval attr assignment, str|None/datetime|None). The four previously-flagged test files (`test_history`, `test_sibling_routes`, `test_rescope_execution_lifecycle`, `test_workflow_service_flag_on`) + `test_msgchains_endpoint`: **0 errors**. |

## B1/B5/B6 regression re-confirmation

- B1 (sibling-route authorization): `_session_security.authorize_session` resolves session→project→owner.team_id (never trusts cached `team_id`, ADMIN bypass, cross-team 404); `accessible_session_ids` scopes collection listings via the owner-team join. `history_security/test_sibling_routes.py` + `test_access.py` green in the run below. No regression.
- B5 (JSON envelope preservation): `history_masking.scrub_text` parses JSON-string leaves, scrubs leaves, re-serializes; `scrub_payload` preserves numbers/bools/None. `test_history.py` password-envelope case green. No regression.
- B6 (paused role not failed): `performer._persist_msgchain_end` maps `error=='paused_for_rescope'` → status `paused` (info log, not error); `test_autonomous_paused_pentester_chain_not_marked_failed` asserts pentester chain `paused`, green. No regression.

## Verification commands and output

Full suite (single run, from `backend`):
```
tests/unit tests/orchestrator tests/api tests/ast tests/infra tests/regression tests/integration tests/safety
→ 1400 passed, 6 skipped, 80 warnings in 5.33s
```
Matches the claimed `1400 passed, 6 skipped`.

Targeted regressions (single run): `test_rescope_execution_lifecycle.py` + `test_workflow_service_flag_on.py` + `history_security/` → 61 passed.

Diagnostics (basedpyright, `/tmp/osa-phase1-pyrightconfig.json`):
- Six production files: `34 errors, 0 warnings, 0 notes`; no `reportImportCycles`.
- Five previously-flagged test files: `0 errors, 0 warnings, 0 notes`.

Direct reproductions (real DB/services/launcher/route, fake external model+adapter, no sleeps):
- B2: statuses `['paused_for_rescope'] × 8`, pending = 1, `ended_at = None` with `max_prompts_per_minute = 5`.
- B4 deterministic: calls `['origin.example','next.example']`, status `completed`, Report `total: 2` (origin discovery finding + next port finding both present).

## remove-ai-slops / programming pass (direct)

Applied both skills' criteria to the diff, new tests, and production consumers (cleanup procedures not executed — gate report only).

- Excessive/useless or deletion-only tests: none. The storage/route/ambiguity matrices distinguish real cases; no test merely pins a removal.
- Tautological / implementation-mirroring: the lifecycle fakes were the round-2 weakness (an external call-counter oracle). Round-2b replaces them with a request-driven model fake that decides ONLY from the supplied conversation, so a resume that failed to restore context would re-scan origin and fail. This closes the prior false-confidence gap. State machine/router/DB/launcher are real; the adapter/model seam is the correct mock boundary.
- Prose/prompt pinning: none; secrets and state tokens are machine-consumed values.
- Unnecessary extraction/parsing: `history_masking` and `_session_security` have multiple real callers (API + orchestrator). `scrub_text`'s JSON-leaf parsing is required for B5 structure preservation, not speculative. NOTE only: `scrub_payload` attempts JSON parse on every string leaf (broader than the single known envelope) — a maintenance note, no criterion failure.
- Typing: the 34 production errors are pre-existing and were preserved per the review's "do not expand into a typing cleanup"; new helper surfaces use `dict[str, Any]`/`Any` with no new `type: ignore` or suppression. The cycle fix duplicates no policy.
- Root-cause placement: B2 guard precedes the terminal `_fail` branch; B3 masking sits at the actual WorkflowService/Performer/AmbiguityLoop write boundaries; B1 authorization is shared across both routers. Correct seams.

Coverage note: the executor evidence (`phase-1-evidence.md`) documents the remediation but is not an independent code-review artifact and does not itself record the skill-perspective overfit pass; the round-1 review file does record it. This direct pass is the authoritative check and does not depend on upstream coverage.

## Notes (not blockers)

1. `_scrub_payload` parses every string leaf as potential JSON; broader normalization than the single envelope strictly needs. Maintenance note.
2. No live Docker/network scan, real external model, Postgres, browser, or WebSocket session exercised; SQLite + fake external I/O are the reproduced scope. The six suite skips remain skips. None of these are named Phase 1 criteria.
3. `service._run_autonomous_lane` docstring still says "Returns (findings, session_killed, abort_reason)" while the signature returns a 4-tuple — stale comment, no behavioral effect.
4. No commit is approved here; all exact-fix descriptions in prior reviews were recommendations. A future Lore commit must carry its trailers and is outside this review.

## Checked artifact paths

- `.omo/evidence/phase-1-p0-security-gate-review.md`, `.omo/evidence/phase-1-p0-security-rereview-gate-review.md`, `.omo/evidence/phase-1-evidence.md`
- `docs/phases/README.md`, `docs/phases/phase-1-p0-security.md`, `/tmp/osa-phase1-pyrightconfig.json`
- Production: `backend/app/api/v1/pentest_sessions.py`, `backend/app/api/v1/sessions.py`, `backend/app/api/v1/_session_security.py`, `backend/app/safety/history_masking.py`, `backend/app/orchestrator/interview_policy.py`, `backend/app/orchestrator/ambiguity_loop.py`, `backend/app/orchestrator/executor.py`, `backend/app/orchestrator/performer.py`, `backend/app/orchestrator/rescope_service.py`, `backend/app/orchestrator/service.py`, `backend/app/orchestrator/workflow_service.py`, `backend/app/orchestrator/roles/pentester.py`
- Tests: `backend/tests/integration/history_security/` (all), `backend/tests/integration/test_rescope_execution_lifecycle.py`, `backend/tests/integration/test_workflow_service_flag_on.py`, `backend/tests/integration/test_msgchains_endpoint.py`

Gate review complete. Recommendation: APPROVE.
