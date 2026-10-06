# Phase 1 P0 security: independent gate review

<verdict>REJECT</verdict>
<confidence>high</confidence>
<summary>The captured backend suite passes, but the delivered artifact does not close the required security and lifecycle gaps. Alternate session routes still disclose another team's data; new conversation history and live message responses remain raw; rescope approval does not restart execution; paused execution can be re-entered or finalized as completed; structured history can be corrupted by masking. New diagnostics also contradict the claimed zero-new-error result.</summary>

recommendation: REJECT

originalIntent: Complete Phase 1 before Phase 2: enforce project-owner-team isolation for session history, protect stored and returned conversations without weakening the WebSocket raw/scrubbed contract, make the actual interview loop use the advertised ambiguity policy, and make both execution lanes pause safely and continue only after an operator's rescope decision.

desiredOutcome: A teammate can read sanitized history while outsiders cannot obtain the same data through another route. The displayed interview target controls the real Flow transition. A discovered out-of-scope host parks the run without a terminal report; approval actually continues the remaining work and rejection kills it. A paused run cannot dispatch later work or appear completed/failed.

userOutcomeReview: PARTIAL. The new pentest-session GET guards work and the actual Flow threshold is consistent. Normal first-entry execution now parks both lanes. Those improvements do not satisfy the complete outcome: sibling session routes bypass the guard, the persistence defect remains, and the approval-to-execution bridge is absent. The new tests prove only the covered subset, not completion of Phase 1.

## Scope and provenance

- Reviewed branch: `feat/phase-1-p0-security`.
- HEAD before and after review: `9414dad3097fc823d9bb882e435e9cd098df711d`.
- Inspected `GIT_PAGER=cat git diff HEAD -- backend/app backend/tests`; read every new untracked history-security and rescope-lifecycle test in full.
- Tracked scope: six production files and six test files, 213 insertions and 64 deletions. The five new test files are not included in that tracked-diff count.
- `GIT_PAGER=cat git diff HEAD --check -- backend/app backend/tests` passed.
- No implementation changes, staging, commits, branch changes, installs, history writes, or venv/site-packages changes were made by this reviewer. This report is the only authored file. Unrelated frontend and operational edits were left untouched.
- No JS eval tool is exposed. The provided SDK status operation was invoked through Node instead and returned `ULW_LOOP_PLAN_MISSING`, naming `.omo/ulw-loop/01a10e6d-ff63-7003-b3b3-82e75e7ccd26/goals.json`. The report therefore uses the requested fallback location.
- Criterion IDs below are reviewer labels for the supplied requirements, not existing repository IDs.

## Blocking issues / blockers

### B1 - Alternate session REST routes still expose another team's data

- Severity: critical.
- violatedCriterion: `P1A.AUTH` - session -> project -> owner-team authorization; cross-team session-scoped reads must return 403/404.
- evidencePointer: `backend/app/api/v1/sessions.py:168-204`, `backend/app/api/v1/sessions.py:218-235`, `backend/app/api/v1/sessions.py:52-77`, and router registration at `backend/app/main.py:169`.
- Observation: `GET /sessions/`, `GET /sessions/{id}`, and `GET /sessions/{id}/executions` do not authorize the project owner/team. `/sessions/{id}/terminal` trusts the session's cached `team_id`, contrary to the specified ownership source. These are mounted production routes, not unused compatibility code.
- Reproduction: Used the new real-DB `history_case` fixture, added the actual legacy sessions router to the ASGI app, and used its signed outsider JWT. All five protected `/pentest-sessions/{id}` GET variants returned 404. In the same fixture, `/sessions/` and `/sessions/{id}` returned 200 with the owner's secret prompt; `/executions` returned 200. After poisoning the cached session team exactly as the new authorization test does, `/terminal` returned 200 with the seeded secret line.
- Exact fix: Apply authoritative project-owner-team authorization to all exposed session readers, including a properly scoped collection query and the terminal reader. Apply the relevant response masking to alternate views of conversation/session content. Add signed-token regressions against these actual sibling routes, not just the new router.

### B2 - A durable pause does not prevent execution re-entry or false completion

- Severity: critical.
- violatedCriterion: `P1C.FAIL_CLOSED` and `P1C.PAUSE_CLASSIFICATION` - later unapproved steps must not run, including late/duplicate dispatch, and a pause must never become completed/failed.
- evidencePointer: `backend/app/orchestrator/executor.py:66-81`, `backend/app/orchestrator/executor.py:342-349`, `backend/app/orchestrator/service.py:96-105`, and `backend/app/orchestrator/service.py:113-121`.
- Observation: `PlanExecutor.execute` sets a pause flag but never checks it on entry. `OrchestratorService.run` unconditionally replaces the persisted status with `running`, including a still-paused session. The Performer guards cover only the current in-memory instance.
- Reproduction A: A real PlanExecutor discovered `next.example`, persisted `paused_for_rescope`, and returned with `paused_for_rescope=True`. Calling the same executor with the later step reached the fake external adapter for `next.example` while the real approval row remained pending. The trace changed from `['origin.example']` to `['origin.example', 'next.example']`.
- Reproduction B: Ran the real autonomous launcher to its first pause, then invoked that same launcher again without deciding the approval. The session changed from `paused_for_rescope` to `completed` while its approval row remained pending. The persisted planner hint made the duplicate invocation enter the saved-workflow lane with no remaining steps; it finalized instead of refusing the paused run.
- Exact fix: Enforce the persisted paused/pending-approval state at execution entry and preserve it through finalization. Also reject same-instance executor re-entry while paused. Resume must be an explicit approved transition, not an unconditional reset to `running`. Add both deterministic re-entry and real-launcher duplicate-invocation regressions. This does not require implementing Phase 2 multi-worker leases.

### B3 - Storage masking and live response masking were not implemented

- Severity: high.
- violatedCriterion: `P1A.STORAGE` and `P1A.RESPONSE` - sensitive conversation data must be masked in stored history and returned responses, reusing ConversationScrubber while preserving raw WebSocket behavior.
- evidencePointer: `backend/app/orchestrator/performer.py:382-391`, `backend/app/orchestrator/ambiguity_loop.py:166-193`, and `backend/app/api/v1/pentest_sessions.py:360-366`.
- Observation: `_persist_msgchain_end` still writes `messages_json=result.messages`. The interview loop still persists raw user content and raw model envelopes. The new scrubber runs only while constructing three GET responses. `POST /pentest-sessions/{id}/messages` still returns raw assistant content.
- Reproduction: Persisted a real Performer role result containing `sk-abc123def456ghi789jkl`; a database SELECT found that exact secret in the newly committed MsgChain. Authorized GET correctly hid it, but a second SELECT still found it in storage. Separately, two real HTTP interview turns through WorkflowService -> AmbiguityLoop returned 200 with the secret in `assistant_content`, and WorkflowMessage storage contained it too.
- Exact fix: Scrub sensitive string content at the actual conversation persistence boundaries and live response boundary. Keep the unsanitized value separately for the existing privileged raw WebSocket publication; do not replace the raw topic with scrubbed content. Retain read-time protection for legacy rows. Test both persisted values and returned values through the real writers. This finding does not require an unrequested historical backfill migration: newly written rows already fail the criterion.

### B4 - Approval changes a status string but never resumes execution

- Severity: high.
- violatedCriterion: `P1C.RESUME` - deterministic and autonomous request -> pause -> approval -> resume must work in actual execution.
- evidencePointer: `backend/app/api/v1/pentest_sessions.py:662-684`, `backend/app/orchestrator/rescope_service.py:337-375`, and `.omo/evidence/phase-1-evidence.md` under `Residual / not-tested`.
- Observation: The rescope endpoint only returns a decision. `_resume_or_kill` sets `status='executing'`; it neither schedules a continuation nor makes the accepted targets effective for subsequent execution. The original runner has already returned. There is no continuation call site among the real references to `decide_rescope`.
- Reproduction: For each lane, ran the actual launcher until the new lifecycle assertions passed, obtained its pending approval, called the real rescope route function with acceptance of `next.example`, committed, and reloaded. Status was `executing`, `ended_at` was null, but the adapter trace was still only `['origin.example']` and the effective target whitelist was still `{'domains': ['origin.example'], 'active_allowed': ['origin.example']}`. No remaining step was launched by the endpoint. Reject-all correctly produced `killed` instead.
- Exact fix: Connect the committed approval decision to a continuation that preserves the original lane/progress, consumes the accepted scope, and runs only remaining approved work. Add both-lane tests that observe the later adapter call and eventual correct completion, rather than only checking the status field. A Phase 1 continuation is required even if crash recovery, distributed leases, and durable worker re-drive remain Phase 2 work.
- The inspected `/tmp/osa-phase1-resume-check.py` only tests status changes on newly created sessions; it never launches either lane. It cannot establish this acceptance criterion. The Phase 2 brief's durable re-drive item concerns interview kickoff; it does not waive Phase 1's stated execution-resume requirement.

### B5 - Masking can destroy the JSON envelope's structure

- Severity: medium.
- violatedCriterion: `P1A.STRUCTURE` - remove secrets while preserving numeric and structural fields.
- evidencePointer: `backend/app/api/v1/pentest_sessions.py:242-255`, `backend/app/api/v1/pentest_sessions.py:445-454`, and `backend/app/safety/conversation_scrubber.py:49-52`.
- Observation: JSON stored inside a string is passed directly to the regex scrubber. The password pattern consumes adjacent JSON punctuation, so recursive processing of the outer response object does not preserve the inner envelope.
- Reproduction: Inserted a legacy WorkflowMessage envelope containing `reasoning='password=supersecret'`, `ambiguity=0.25`, and a draft plan. Authorized HTTP GET returned 200, but its `content` could not be parsed as JSON. Actual returned content:

```text
{"ambiguity": 0.25, "reasoning": "[REDACTED:email_password_pair] "draft_plan": {"steps": []}}
```

- Exact fix: At the known structured-envelope boundary, preserve parsed structure while scrubbing its string values, then serialize valid JSON. Do not blindly regex the serialized envelope. Add a behavioral regression covering a supported non-API-key secret and verifying the envelope is parseable with unchanged numeric/structural values.

### B6 - The autonomous paused role is still persisted and published as failed

- Severity: medium.
- violatedCriterion: `P1C.PAUSE_CLASSIFICATION` - a rescope pause must not be presented as a failure.
- evidencePointer: `backend/app/orchestrator/performer.py:252-260`, `backend/app/orchestrator/performer.py:382-400`, and `backend/app/orchestrator/roles/pentester.py:318-325`.
- Observation: The service now excludes `error='paused_for_rescope'` from its session failure decision, but Performer still classifies every role error as failed. The Agents history/event surface receives a failed pentester row for an ordinary approval pause.
- Reproduction: Normal autonomous discovery produced session status `paused_for_rescope` and chains `[('generator', 'finished'), ('pentester', 'failed')]`. It also logged `Role pentester failed after retries: paused_for_rescope. Halting loop.` This was reproduced before both approve and reject decisions.
- Exact fix: Propagate the pause outcome consistently through role persistence and emitted status, keeping a nonfailure pause distinct from a true role error. Add a regression for the user-visible MsgChain/event status alongside the session-level assertion.

### B7 - New diagnostics contradict the zero-new-error claim

- Severity: medium.
- violatedCriterion: `QA.DIAGNOSTICS` - assess against baseline and introduce no new changed-file errors.
- evidencePointer: `backend/app/orchestrator/ambiguity_loop.py:34`, `backend/app/orchestrator/workflow_service.py:474`, and `backend/tests/integration/test_msgchains_endpoint.py:22,76,81,98,109`.
- Observation A: The explicit six-production-file basedpyright command with the supplied `/tmp/osa-phase1-pyrightconfig.json` reports **35 errors**, not 34. The additional error is `reportImportCycles`: ambiguity_loop -> workflow_service -> ambiguity_loop. The reverse import was added by this diff.
- Observation B: The changed msgchains fixture now returns `(UUID, list[UUID], User)` while its annotation still promises two elements. The same configured checker reports **four errors**: one `reportReturnType` at line 76 and three `reportAssignmentType` tuple-size mismatches at lines 81, 98, and 109. Built-in LSP independently reports these four errors, in addition to its environment-resolution noise.
- Exact fix: Break the new import cycle without duplicating the ambiguity policy, update the fixture's return annotation to include User, and check all changed test files as well as production files. Preserve the disclosed unrelated baseline typing defects rather than expanding this into a typing cleanup.
- Exact baseline diagnostic output was not supplied or rerun in a separate checkout, so its 34-error total is not independently certified. Nevertheless, the new cycle edge and tuple-contract changes are directly attributable to the inspected diff. Equal claimed totals cannot establish zero new errors.

## Goal breakdown

| Criterion | Result | Evidence |
| --- | --- | --- |
| P1A.AUTH: authoritative project owner/team for the new pentest GET readers | ACHIEVED on those five routes | `_authorize_session` at `pentest_sessions.py:217-239`; signed outsider reads returned 404 even with poisoned cached team. Real owner/member/team-admin/global-admin coverage is in `history_security/test_access.py`. |
| P1A.AUTH: all session-scoped REST reads respect that boundary | MISSED | B1; production `/sessions` routes bypass it, including collection enumeration. |
| P1A.STORAGE: sensitive newly stored conversations are masked | MISSED | B3; direct committed MsgChain and WorkflowMessage reads retain the secret. |
| P1A.RESPONSE: legacy raw history is masked on GET | PARTIAL | The new three GET paths remove the API-key fixture and preserve its numeric values. B1/B3 leave alternate/live paths raw; B5 corrupts another supported secret's JSON envelope. |
| P1A.STRUCTURE: preserve numbers and structure | PARTIAL | API-key test preserves ambiguity 0.25 and token count 17; password-envelope probe fails JSON parsing. |
| P1A.WS: preserve scrubbed/raw contract | ACHIEVED for the existing Performer publisher | `_publish_role_turn` at `performer.py:274-317` still publishes scrubbed content to `conversation` and the original text to `raw_conversation`; this region is unchanged. Full suite passes. No live WebSocket/browser test was performed. |
| P1B.SOURCE: one effective policy for helper and actual Flow loop | ACHIEVED functionally | Both `_next_state_after_turn` and `_decide_next_state` call `interview_ambiguity_target`; only that policy reads the legacy threshold in the application Flow path. B7 remains a diagnostic defect in how the reuse was wired. |
| P1B.TRANSITION: boundaries and toggle | ACHIEVED | Eight new real-Flow cases cover below/equal/above 0.20 and 0.35, the 0.30 regression, and a nondefault 0.12 policy. Manual actual HTTP Flow returned interviewing at 0.30 and ready_for_review at 0.20. |
| P1B.UI_DOCS: displayed target matches policy | ACHIEVED at code/API level | `_serialize` returns the effective target; `PentestWorkflow.tsx:1173` passes it to `WorkflowChat`, which renders and compares it at `WorkflowChat.tsx:109-118`. Existing comments describe the autoblock/legacy defaults consistently. No frontend edit/build or visual claim is made. |
| P1C.VOCABULARY: running can request a rescope pause | ACHIEVED | `rescope_service.py:125` accepts running/executing; both actual lanes reached the durable pause in independent probes. |
| P1C.PARK: first-entry pause is durable, unfinished, report-free | ACHIEVED on the normal first invocation | Real launcher + DB + adapter-boundary fake passed `test_execution_pauses_before_later_steps` assertions for both lanes: paused status, null ended_at, one completed execution, no report, only the origin called. |
| P1C.FAIL_CLOSED: no late/nested/duplicate work while paused | PARTIAL | Same Performer instance is guarded at two dispatch seams and its new regression passes. Same PlanExecutor re-entry and duplicate real-launcher invocation fail, B2. |
| P1C.PAUSE_CLASSIFICATION: never failed/completed | PARTIAL | Initial session park is fixed; autonomous MsgChain still says failed, B6, and duplicate launch says completed with pending approval, B2. |
| P1C.RESUME: approval actually continues both lanes | MISSED | B4; the execution run has ended and the endpoint only changes database status. |
| P1C.REJECT: reject-all becomes killed, not failed | ACHIEVED in independent both-lane checks | Both actual paused runs became killed with ended_at set after a real decision/commit. |
| P1C.TUPLE: autonomous four-value contract is consistent | ACHIEVED | LSP references find the production unpack and both direct test calls; literal search finds updated stub sites. Full suite passes. The service docstring still describes three values, a note below. |
| QA.REGRESSION: new narrowly scoped behavioral coverage | PARTIAL | Added tests are meaningful, but omit persistence writes, complete execution resume, alternate routes, JSON-password structure, and duplicate/re-entry behavior. |
| QA.SUITE: full documented backend suite green in a single invocation | ACHIEVED | Captured independent run: 1385 passed, 6 skipped, 75 warnings in 5.22 seconds. |
| QA.DIAGNOSTICS: no new errors | MISSED | B7: production import cycle and four changed-test tuple errors. |

## Constraint compliance

- Correct Phase 0 base and Phase 1 branch: confirmed before and after review.
- Unrelated user edits and the existing venv/site-packages: preserved by this review; no installs or checkout operations were used.
- Current symbols: resolved/inspected current definitions and call sites rather than relying on the phase packet's historical line numbers.
- Narrow regression additions: no tests were deleted, skipped, or marked xfail by the diff. Existing kill/abort assertions remain.
- Response scaffolding correction: legitimate. `model_client.py:28-33` defines all four Response fields without defaults; supplying `tokens_in`, `tokens_out`, and `raw` makes the fake conform to the real constructor.
- Four-value lane scaffolding correction: legitimate. Stubs now match the actual return/unpack contract, and existing kill/abort assertions were retained.
- Authorized-reader updates: returning the seeded owner from the msgchains fixture is appropriate, except for its stale annotation. The three legacy message-history tests now use the established global-admin bypass; their history assertions are unchanged, and the new real-token matrix independently covers ordinary members. This is not an authorization-test weakening, though constructing a real project owner would make those fixtures more representative.
- Atomic Lore commit: not created and must remain withheld on this REJECT. A future verified commit must contain Constraint, Rejected, Confidence, Scope-risk, and Not-tested. Its future message cannot be approved here.
- Phase 2: no implementation of Phase 2 found in the scoped diff. Deferring the entire Phase 1 approval-to-execution continuation to Phase 2 is a goal omission, not an acceptable scope reduction.

## QA audit and commands

All Python runtime checks used the supplied interpreter and existing packages. External model/adapter I/O was faked; the router, signed authentication, ORM, services, state machine, launcher, Performer/PlanExecutor, and SQLite database were real. No sleeps or timing-based waits were added to probes.

### Captured complete suite

From `backend`:

```sh
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=.:.venv/lib/python3.13/site-packages \
OSA_E2E_DOCKER_SCANME=0 OSA_E2E_DVWA_URL='' OSA_E2E_JUICE_URL='' \
/Users/minsung.jung/.local/bin/python3.13 -m pytest -q -p no:cacheprovider \
  tests/unit tests/orchestrator tests/api tests/ast tests/infra \
  tests/regression tests/integration tests/safety --disable-warnings --tb=short
```

Observed: `1385 passed, 6 skipped, 75 warnings in 5.22s`. This was one complete captured invocation, without rerun-failures, test ordering overrides, or edits to get it green. An earlier background invocation returned only a handle; its inaccessible result is not counted as verification. This child exposes no bash_output/monitor tool, so the short foreground invocation supplied observable evidence.

### Diagnostics

```sh
cd backend
PYTHONDONTWRITEBYTECODE=1 /Users/minsung.jung/.local/bin/basedpyright \
  --level error --project /tmp/osa-phase1-pyrightconfig.json \
  app/api/v1/pentest_sessions.py app/orchestrator/ambiguity_loop.py \
  app/orchestrator/executor.py app/orchestrator/performer.py \
  app/orchestrator/rescope_service.py app/orchestrator/service.py
```

Observed: exit 1, `35 errors, 0 warnings, 0 notes` (warnings hidden by the requested level). Per-file errors: pentest_sessions 7, ambiguity_loop 1 import cycle, executor 9, performer 6, rescope_service 4, service 8.

```sh
PYTHONDONTWRITEBYTECODE=1 /Users/minsung.jung/.local/bin/basedpyright \
  --project /tmp/osa-phase1-pyrightconfig.json \
  tests/integration/test_msgchains_endpoint.py
```

Observed: exit 1, `4 errors, 31 warnings, 0 notes`; all four errors are the changed tuple contract. Built-in LSP also found them. The built-in LSP configuration cannot resolve the backend environment cleanly, so its missing-import/implicit-relative-import noise was not attributed to this change.

### Manual real-path matrix

The commands were executed from `backend` as Python stdin programs using the same environment. They directly entered `tests.conftest.engine.__wrapped__()`, `history_case.__wrapped__(engine)`, and `runtime.__wrapped__(engine, monkeypatch)` with proper generator cleanup. The exact executed programs and outputs are retained in the child-session artifact below.

| Probe | Actual path | Observation |
| --- | --- | --- |
| Cross-team denial on changed GET routes | signed JWT -> ASGI -> actual pentest router -> DB | Five variants returned 404. |
| Sibling-route isolation | signed outsider JWT -> actual sessions router -> DB | Collection/detail/executions returned 200; collection/detail exposed secret prompt. Cached-team-poisoned terminal returned 200 with secret line. |
| New stored role transcript | actual Performer start/end persistence -> committed SELECT | Secret remained in messages_json while authorized GET masked it. |
| Live interview secret | HTTP POST -> WorkflowService -> AmbiguityLoop -> injected external model | Both 0.30/0.20 turns returned raw secret; stored WorkflowMessage also contained it. |
| Interview policy | same actual HTTP path, autoblock 0.20 and legacy 0.35 configured | 0.30 interviewing; 0.20 ready_for_review; GET advertised 0.20. |
| Structured legacy history | raw envelope row -> authorized GET /messages | 200 response, but password redaction made content invalid JSON. |
| First pause, both lanes | actual execution launcher -> service -> real execution lane | paused_for_rescope, ended_at null, one origin call, one completed AgentExecution, no report. |
| Approval, both lanes | real paused run -> actual rescope route function -> commit/reload | executing but no continuation; calls remained origin-only and accepted host was absent from effective whitelist. |
| Reject-all, both lanes | same real path with rejection | killed, ended_at set, never failed. |
| Same deterministic executor after pause | execute(first) -> pending approval -> execute(later) | Later next.example adapter call occurred while approval stayed pending. |
| Duplicate launcher after autonomous pause | launcher -> pause -> launcher again without decision | Session completed while rescope approval stayed pending. |
| Autonomous role status during normal pause | real role persistence after pause | Pentester MsgChain failed; pause failure log emitted. |

The manual approval invocation called the route function directly with a real Request/DB/user, not a running browser. It proves that the endpoint has no continuation side effect; no elapsed-time inference was used. It does not claim a real container or external network scan.

## Direct programming and remove-ai-slops assessment

Loaded and applied both skills independently:

- `/Users/minsung.jung/.omo/binary-runtime/5.1.19/plugin/skills/remove-ai-slops/SKILL.md`
- `/Users/minsung.jung/.omo/binary-runtime/5.1.19/plugin/skills/programming/SKILL.md`
- `/Users/minsung.jung/.omo/binary-runtime/5.1.19/plugin/skills/programming/references/python/README.md`

Applied their review criteria to the diff, complete new tests, and the actual production consumers. Their cleanup/refactoring procedures were not executed because the explicit task permits only a gate report.

- Excessive/useless tests: no new test proliferation warrants rejection. The token/team matrix distinguishes roles and routes; the ambiguity matrix distinguishes both policy sources and a nondefault target.
- Deletion-only or requested-removal-pinning tests: none added.
- Tautological tests: the new HTTP history tests and launcher tests exercise actual production logic with real persisted state; their expected results are independent fixture values. They are not tautologies. Their incompleteness is substantive: read-only masking assertions cannot prove storage masking, and pause-only assertions cannot prove resume.
- Implementation-mirroring: the new lifecycle tests mock the external adapter/model rather than the state machine or executor. This is an appropriate seam. The lane tuple scaffolding tests retain observable kill/abort assertions.
- Prose/prompt pinning: none introduced in the diff. Secret strings and state tokens are machine-consumed data, not pinned natural-language copy.
- Unnecessary extraction/parsing/normalization: the authorization and scrub helpers have multiple real callers and are not speculative layers. No unnecessary production parser or normalizer was added. The scrubber's opaque-string treatment is a correctness gap at an actual structured boundary (B5), not a request to add generic parsing infrastructure.
- Root-cause placement: the authorization fix stops at one router, and masking stops at response serialization rather than the specified persistence seam. The sibling leaks and raw writers are concrete examples of partial fixes, B1/B3.
- Typing: untyped scrub helpers reduce checker coverage, and the stale tuple annotation/new import cycle produce actual diagnostic failures, B7. No new type-ignore or lint suppression was added by the diff.
- State representation: the four-value return consistently propagates an instance flag, but the durable paused state is not authoritative on re-entry, B2. A status-only decision is not a running continuation, B4.
- Error handling: no new broad catch was introduced. Existing catch-and-audit paths around rescope still continue after errors, and existing role-status mapping conflates pause with error. The concrete normal-pause classification failure is B6; no hypothetical exception-injection requirement is added.
- Maintenance notes: the new park branch commits again immediately after the preceding commit, and several explanatory comments repeat the intended guarantees that the implementation does not yet enforce. `_run_autonomous_lane` still documents a three-value return at `service.py:492`, despite returning four. These are notes, not independent blockers.
- Scope/style: existing oversized modules, raw generics, and inherited async style are not used to demand an unrelated refactor. No Phase 2 architecture or speculative hardening is required by this review.

No separate Phase 1 code-review report or notepad path was supplied. `.omo/evidence/phase-1-evidence.md` is executor evidence, not an independent code-review report, and it does not explicitly document the requested programming/remove-ai-slops overfit pass. Another reviewer's coverage therefore cannot be confirmed. This report contains the direct check; the missing upstream review input is an evidence NOTE rather than an invented implementation blocker.

## Exact evidence gaps and notes

1. Full baseline diagnostic JSON/log was not provided. Current production diagnostics were independently captured and contradict the claimed 34 count. The test-file diagnostics were omitted from the supplied evidence.
2. The supplied manual resume script checks only database state strings and no real lane continuation. Independent real-lane probes show that gap is an actual failed criterion, B4.
3. No separate code-review artifact, named manual QA matrix artifact, or notepad path was supplied. Executor prose was cross-checked against actual files and the real paths above; it was not accepted as proof by itself.
4. Real daemon-present/container execution and a live browser/WebSocket session were not exercised. SQLite and fake external I/O are explicitly the scope of the reproduced real service/router paths. The full suite's six skips remain skips, not successful live-environment tests.
5. Initial background commands returned handles without accessible result/session tools. Their outputs were not assumed. Captured foreground commands supply all runtime/type-check conclusions cited here.
6. Existing POST authorization behavior outside the stated read-boundary work was not expanded into a separate authorization audit. The demonstrated read bypasses alone fail the requested criterion.
7. The report does not approve any future commit, nor infer that preserving the working-tree base proves historical ownership of every unrelated user edit.

## Checked artifact paths

Briefs and supplied evidence:
- `docs/phases/README.md`
- `docs/phases/phase-1-p0-security.md`
- `docs/phases/phase-2-interactive-flow.md` (read only to check the claimed rescope deferral)
- `.omo/evidence/phase-1-evidence.md`
- `/tmp/osa-phase1-pyrightconfig.json`
- `/tmp/osa-phase1-resume-check.py`
- `.omo/evidence/phase-0-b-gate-review.md` (baseline/provenance context, not accepted as current implementation proof)

All six changed production files:
- `backend/app/api/v1/pentest_sessions.py`
- `backend/app/orchestrator/ambiguity_loop.py`
- `backend/app/orchestrator/executor.py`
- `backend/app/orchestrator/performer.py`
- `backend/app/orchestrator/rescope_service.py`
- `backend/app/orchestrator/service.py`

New tests read in full:
- `backend/tests/integration/history_security/__init__.py`
- `backend/tests/integration/history_security/conftest.py`
- `backend/tests/integration/history_security/test_access.py`
- `backend/tests/integration/history_security/test_history.py`
- `backend/tests/integration/test_rescope_execution_lifecycle.py`

Changed tests inspected through the working-tree diff and relevant current source:
- `backend/tests/integration/test_workflow_service_flag_on.py`
- `backend/tests/integration/test_ambiguity_loop_full.py`
- `backend/tests/api/test_pentest_sessions_create.py`
- `backend/tests/api/test_pentest_execution_launcher.py`
- `backend/tests/integration/test_msgchains_endpoint.py`
- `backend/tests/integration/test_pentest_messages_history.py`

Supporting current behavior inspected:
- `backend/app/api/v1/sessions.py`
- `backend/app/main.py` (router registration)
- `backend/app/models/{__init__,msgchain,project,user}.py`
- `backend/app/orchestrator/workflow_service.py` (shared target policy and consumed call sites)
- `backend/app/orchestrator/execution_launcher.py`
- `backend/app/orchestrator/safety_exec.py`
- `backend/app/orchestrator/assistant_service.py` (writer/Performer construction)
- `backend/app/orchestrator/model_client.py` (Response contract)
- `backend/app/orchestrator/roles/{pentester,reflector}.py`
- `backend/app/safety/conversation_scrubber.py`
- `backend/tests/conftest.py`
- `backend/tests/integration/test_rescope_state_machine.py` (approval/rejection coverage)
- `frontend/src/components/WorkflowChat.tsx` (target rendering)
- `frontend/src/pages/PentestWorkflow.tsx` (target prop)

Independent command and tool-output provenance is retained in this child session:
`/Users/minsung.jung/.omo/agent/projects/offensive-security-963b73057cac/senpi-task/children/st_01a10e6d/sessions/st_01a10e6d/2026-10-05T23-37-32-259Z_01a10e6d-ff63-7003-b3b3-82e75e7ccd26.jsonl`.

The exact fix descriptions above are recommendations only. No fixes were implemented. Gate review is complete; approval is withheld.
