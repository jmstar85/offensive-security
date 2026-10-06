# Phase 1 P0 security: independent gate re-review

<verdict>REJECT</verdict>
<confidence>high</confidence>
<summary>B1, B5, and B6 are resolved. B2, B3, B4, and B7 remain partially resolved: repeated dispatch can still finalize a paused run as failed; user conversations and legacy assistant conversations remain raw in storage; continuation loses execution progress; and the claimed import-cycle fix still produces a diagnostic. The independently reproduced suite passes, but does not establish these outcomes.</summary>

recommendation: REJECT

originalIntent: Complete Phase 1 before Phase 2: enforce authoritative project-owner-team isolation on session history, mask stored and returned conversations while preserving the privileged raw WebSocket stream, make the real interview use the advertised ambiguity target, and make both execution lanes durably pause and continue remaining work only after an operator decision.

desiredOutcome: Authorized teammates can read sanitized conversations; other teams cannot obtain them through either router. The displayed target controls the real interview transition. Discovery parks execution without a terminal report or failure. Approval continues the original engagement without dropping or repeating work, and rejection kills it.

userOutcomeReview: PARTIAL. All GET routes in both specified routers now enforce the same authoritative ownership source. JSON structure, role persistence, live interview responses, and paused role status are improved. Both lanes can reach a durable initial pause, and the approval endpoint now really schedules execution. However, masking is incomplete at the actual writers, the entry guard comes after a terminal failure path, and the resumed execution does not faithfully preserve progress. These are failures of stated outcomes, not requests for Phase 2 leases, crash recovery, or architecture changes.

## Per-item B1-B7 resolution

| Prior item | Resolved? | Independently checked evidence |
| --- | --- | --- |
| B1: sibling REST authorization bypass | RESOLVED | `backend/app/api/v1/_session_security.py:18-60`; `sessions.py:145-251`; all five GET readers in `pentest_sessions.py` call the shared authorization policy. The signed-token, poisoned-team regressions in `history_security/test_access.py` and `test_sibling_routes.py` pass in the independent full run. Collection queries join through Project.created_by -> User.team_id. |
| B2: paused re-entry / false completion | NOT RESOLVED; original single-duplicate scenarios fixed | Same-instance PlanExecutor and single duplicate launcher regressions pass. However, five immediate duplicate launches after the initial pause exhaust the existing rate limit and produce `failed`, `ended_at != None`, with the approval still pending. `backend/app/orchestrator/service.py:58-61,102-114,688-700`. |
| B3: storage and live response masking | NOT RESOLVED; assistant Flow/Performer and live POST improved | Real HTTP interview + committed SELECT: Flow-on user WorkflowMessage still contains the API key; Flow-off user and assistant WorkflowMessages remain raw, including assistant metadata. `workflow_service.py:441-446,740-748`. Performer stored transcript is now scrubbed; the live interview response and legacy GET are scrubbed. |
| B4: approval does not continue execution | NOT RESOLVED; scheduling bridge fixed, continuation semantics incomplete | Real signed HTTP POST `/rescope` runs background continuation. Ordinary deterministic trace is origin -> next. With two valid distinct step IDs sharing order 1, next is silently skipped and the session completes. A request-driven autonomous model receives identical initial context on resume and repeats origin. `executor.py:66-76,99-105`; `service.py:554-565`; lifecycle fake at `test_rescope_execution_lifecycle.py:91-100` hides the autonomous context loss. |
| B5: JSON envelope corruption | RESOLVED for the reported supported envelope | `backend/app/safety/history_masking.py:13-37`; password-envelope regression passes; independent HTTP turns with `password=supersecret123` remain parseable JSON with unchanged numeric ambiguity. |
| B6: paused role persisted/published as failed | RESOLVED | `backend/app/orchestrator/performer.py:387-416`; real autonomous lifecycle test records pentester `paused`. Independent real persistence and event-bus probe observes agents statuses `[running, paused]`, a masked stored transcript, scrubbed conversation publication, and raw privileged publication. |
| B7: new type diagnostics | NOT RESOLVED; tuple annotation fixed | Exact original six-production-file checker still reports 35 errors, including `reportImportCycles`. Eight additional attributable errors are in new/newly added tests. The msgchains fixture's tuple-size errors are gone. See diagnostic detail below. |

## Blocking issues / blockers

### B2 - The durable pause guard still permits terminal failure on duplicate launch

- Severity: high.
- violatedCriterion: `P1C.FAIL_CLOSED`, `P1C.PAUSE_CLASSIFICATION`.
- evidencePointer: `backend/app/orchestrator/service.py:58-61`, `backend/app/orchestrator/service.py:102-114`, `backend/app/orchestrator/service.py:688-700`; independent `DUPLICATE_PROBE` below.
- Observation: `run()` calls `_check_rate_limit` before loading or checking the paused session. `_fail` unconditionally writes `failed` and `ended_at`. Refused paused launches also consume the rate-limit allowance. The new guard therefore protects only dispatches that pass earlier checks.
- Reproduction: Enter the existing real `runtime` fixture, launch the autonomous session to its first actual discovery pause, then call the real launcher `settings.max_prompts_per_minute` more times without deciding its approval. No sleeps, clock manipulation, state-machine mock, or external I/O were used.

```json
{"statuses":["paused_for_rescope","paused_for_rescope","paused_for_rescope","paused_for_rescope","paused_for_rescope","failed"],"pending":1,"calls":["origin.example"],"ended":true}
```

- Exact fix: Reject a persisted paused/pending-approval invocation before rate-limit and other branches that can mutate terminal state. Preserve the parked state and null ended_at on every refused launch. Add a regression that exhausts the existing allowance while an actual approval remains pending, rather than checking only one duplicate. This is an entry-state invariant, not distributed lease work.

### B3 - The actual user-turn writer and legacy assistant writer still persist secrets

- Severity: high.
- violatedCriterion: `P1A.STORAGE`.
- evidencePointer: `backend/app/orchestrator/workflow_service.py:441-446`, `backend/app/orchestrator/workflow_service.py:740-748`; `backend/tests/integration/test_workflow_service_flag_on.py:236-253`; independent `STORAGE_PROBE` below.
- Observation: The user WorkflowMessage is created with `content=user_message` before the Flow switch. On the supported flag-off path, assistant content and blockers/reasoning are also persisted raw. The added test supplies user content `go` and inspects only the assistant WorkflowMessage plus MsgChain, so it cannot detect the outstanding user-write defect.
- Reproduction: Signed owner HTTP POST `/pentest-sessions/{id}/messages`, real WorkflowService and database, external model returning an API key and password. Commit, then select WorkflowMessage columns. Both live POST and authorized GET hide the key, but the new committed rows do not consistently do so:

| Mode | Stored user API key | Stored assistant API key/password | Stored assistant metadata API key | Live POST / GET key leak |
| --- | --- | --- | --- | --- |
| Flow on | YES | No | No | No / No |
| Flow off | YES | YES / YES | YES | No / No |

- Exact fix: Apply the shared structure-preserving scrubber at the actual user and legacy assistant WorkflowMessage persistence boundaries, including persisted assistant metadata. Preserve any needed raw value only in the appropriate live/in-memory path. Add real-writer regressions with a secret-bearing user message in both flag modes and inspect committed rows, not only responses. A historical backfill is not required to fix this finding.
- Positive evidence: Performer now masks `messages_json` on persistence without mutating its RoleResult messages or the raw event publication. The original Performer persistence scenario is fixed.

### B4 - Continuation can skip remaining work or repeat completed work

- Severity: high.
- violatedCriterion: `P1C.RESUME`, `P1C.FAIL_CLOSED` (no false completion).
- evidencePointer: `backend/app/orchestrator/executor.py:66-76,99-105`; `backend/app/orchestrator/service.py:429-438,478,554-565`; `backend/app/orchestrator/roles/pentester.py:193-210`; `backend/app/orchestrator/workflow_plan.py:88-128`; `backend/tests/integration/test_rescope_execution_lifecycle.py:91-100,268-272`.

#### Deterministic continuation mistakes ordering metadata for unique step identity

The newly added skip set uses `AgentExecution.step_order`, and every plan step with that order is skipped. The existing plan contract requires unique `id`, not unique `order`; normalization accepts two different IDs with order 1. This is also explicitly anticipated by `chat_draft_to_workflow_plan`, which generates IDs independently of possibly duplicated model orders.

Independent real-launcher -> signed HTTP approval -> background continuation result:

```json
{"lane":"duplicate_order","pause":"paused_for_rescope","http":200,"final":"completed","calls":["origin.example"],"executions":[[1,"completed"]],"reports":[{"findings":[],"severity_counts":{},"total":0}]}
```

The second, accepted `next.example` step never runs. The engagement is nevertheless reported completed with zero findings.

Exact fix: Resume against a stable unique execution-step identity or a uniquely derived execution position, not optional/nonunique display order. Preserve the accepted plan contract, and test two distinct valid step IDs with the same order. Require the later adapter call before successful finalization.

#### Autonomous continuation starts a new engagement context

The lane marker preserves lane selection, but `_run_autonomous_lane` constructs a new Performer and seeds only the original objective and plan. Pentester constructs a new initial messages list. Neither the completed tool/result context nor accepted discovery progress is restored.

The regression's external fake chooses its next action using `len(state.calls)` across launches. A real stateless model API only receives the messages supplied by production; it does not have access to that Python trace. I replaced only this external fake with one that decides from its supplied messages: first request scans origin, origin's tool result leads to next, next's result leads to done. The first Pentester request before and after approval was byte-for-byte equal.

```json
{"lane":"autonomous","pause":"paused_for_rescope","http":200,"final":"completed","calls":["origin.example","origin.example","next.example"],"executions":[[1,"completed"],[1,"completed"],[2,"completed"]],"autonomous_initial_requests_equal":true}
```

Exact fix: Continue from retained execution context/progress, carrying completed results and the approved discovered scope into the resumed model interaction. Do not rely on the external model/fake to remember previous calls. Change the regression to a request-driven model fake and require the exact remaining-work trace, not only membership of `next.example` somewhere in the calls.

#### Completed deterministic results disappear from the resumed report

With ordinary unique orders, the continuation correctly calls only the second adapter, but its `findings` collection starts empty and completed rows are only used for the skip set. The final report receives only the second run's findings. In the probe, the original discovery finding remains in its completed AgentExecution but is absent from the report; report total is 1 instead of the two execution findings.

Exact fix: Retain/aggregate prior completed execution results when continuing the same engagement, without rerunning completed tools. Verify final report findings across the pause boundary. This is part of preserving original execution progress, not a new reporting feature.

### B7 - The cycle remains, and new tests also introduce type errors

- Severity: medium.
- violatedCriterion: `QA.DIAGNOSTICS` (the supplied no-new-changed-file-error criterion).
- evidencePointer: `backend/app/orchestrator/ambiguity_loop.py:54`; `backend/app/orchestrator/workflow_service.py:474`; the exact basedpyright command below and newly added test locations listed here.
- Observation: Moving the import into the function does not remove the dependency cycle from basedpyright's graph. The exact six-file command reports **35 errors**, not 34, and `reportImportCycles` is still present. This is a new reverse dependency relative to HEAD, evident in the diff.

| New diagnostic location | Error |
| --- | --- |
| `backend/app/orchestrator/ambiguity_loop.py:54` | `reportImportCycles`: ambiguity_loop -> workflow_service -> ambiguity_loop |
| `backend/tests/integration/history_security/test_history.py:26,30,65` | Three `reportArgumentType` errors: mapped `__table__` typed as FromClause passed to insert |
| `backend/tests/integration/history_security/test_sibling_routes.py:26` | `reportMissingTypeArgument`: new bare dict return annotation |
| `backend/tests/integration/test_rescope_execution_lifecycle.py:263` | `reportArgumentType`: SimpleNamespace passed as Request |
| `backend/tests/integration/test_rescope_execution_lifecycle.py:268` | `reportCallIssue`: direct BackgroundTask.func call lacks its ParamSpec arguments |
| `backend/tests/integration/test_workflow_service_flag_on.py:209,236` | Two new `reportArgumentType` errors: StubClient/Leaky passed as ModelClient |

There are **nine directly attributable errors** in this table: one production cycle and eight new test errors. The old msgchains fixture's four tuple errors are resolved. The two new production modules produce zero errors under the supplied configuration. Existing bare generics and other older errors are not additional blockers.

Exact fix: Share the ambiguity policy without a reverse module dependency, keeping one effective policy. Correct the new test contracts: typed SQLAlchemy insert target, `dict[str, str]` headers, real Request/ASGI surface, invoke the BackgroundTasks object through its public async call, and a client double conforming to the existing ModelClient contract. Run the checker over changed tests as well as production; do not suppress diagnostics or duplicate the threshold.

## goal_breakdown

| Requirement | Result | Evidence |
| --- | --- | --- |
| 1-a: authoritative owner-team access across both routers | PASS | Shared ownership helper, scoped collection join, passing actual-user/token matrix with deliberately poisoned cached team_id. |
| 1-a: storage masking | FAIL | B3: new user rows remain raw; flag-off assistant rows and metadata remain raw. |
| 1-a: history/live interview response masking | PASS for tested session/message/chain/terminal surfaces | Signed HTTP tests and independent POST/GET probes remove secrets. Legacy password envelopes remain parseable. |
| 1-a: JSON/numeric structure | PASS for specified envelope regression | Actual password response JSON parses; ambiguity values 0.30/0.20 survive. History tests preserve 0.25 and usage input_tokens 17. |
| 1-a: raw/scrubbed WebSocket split | PASS at real publisher boundary | Actual event bus subscriptions receive scrubbed conversation, original raw_conversation, and role persistence does not alter the original result. No live socket/browser claim. |
| 1-b: one actual policy source | PASS functionally | LSP references resolve helper, actual AmbiguityLoop and API serializer to `interview_ambiguity_target`. Its wiring still fails QA.DIAGNOSTICS. |
| 1-b: real Flow boundary transitions and display | PASS | Eight boundary/toggle/nondefault-target regressions pass. Independent HTTP turns at 0.30 and 0.20 yield interviewing then ready_for_review; GET advertises 0.20. Frontend reads the returned target. |
| 1-c: initial discovery pause, both lanes | PASS | Real-launcher tests and independent probes park at paused_for_rescope, no terminal report, ended_at null, origin-only trace. |
| 1-c: same-instance/one-duplicate re-entry | PASS for original examples | New executor and launcher regressions pass. |
| 1-c: durable parked state under repeated duplicate launch | FAIL | B2: rate-limit branch changes it to failed while approval remains pending. |
| 1-c: paused role, not failed | PASS | Actual autonomous chain and real agents publication use paused. |
| 1-c: approval changes effective scope and runs a continuation | PASS for ordinary unique-order deterministic plan | Signed HTTP decision launches accepted next.example through the actual background-task surface. |
| 1-c: continue remaining work faithfully in both lanes | FAIL | B4: duplicate order skips work, autonomous restarts prior work, deterministic report loses prior findings. |
| 1-c: reject ends as killed | PASS | Both actual paused lanes -> signed HTTP reject -> killed, ended_at set, origin-only trace. |
| QA: full documented suite | PASS | Independent single run: 1398 passed, 6 skipped, 78 warnings in 5.35 seconds. |
| QA: no attributable new diagnostics | FAIL | B7: one new production cycle and eight new test errors. |
| QA: existing test changes reflect contract | PASS | Authorized-reader fixtures, 403 -> 404, threshold boundary and four-value tuple changes match the requested behavior; kill/abort assertions retained. |

## Verification evidence and manual QA matrix

### Full suite

Executed once from `backend`, observed exit code 0:

```sh
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=.:.venv/lib/python3.13/site-packages \
OSA_E2E_DOCKER_SCANME=0 OSA_E2E_DVWA_URL='' OSA_E2E_JUICE_URL='' \
/Users/minsung.jung/.local/bin/python3.13 -m pytest -q -p no:cacheprovider \
  tests/unit tests/orchestrator tests/api tests/ast tests/infra \
  tests/regression tests/integration tests/safety --disable-warnings --tb=short
```

Observed: `1398 passed, 6 skipped, 78 warnings in 5.35s`.

### Diagnostics

Executed the supplied configuration after reading `/tmp/osa-phase1-pyrightconfig.json`:

```sh
cd backend
PYTHONDONTWRITEBYTECODE=1 /Users/minsung.jung/.local/bin/basedpyright \
  --level error --project /tmp/osa-phase1-pyrightconfig.json \
  app/api/v1/pentest_sessions.py app/orchestrator/ambiguity_loop.py \
  app/orchestrator/executor.py app/orchestrator/performer.py \
  app/orchestrator/rescope_service.py app/orchestrator/service.py
```

Observed exit 1: `35 errors, 0 warnings, 0 notes`. Per-file errors: pentest_sessions 7, ambiguity_loop 1, executor 9, performer 6, rescope_service 4, service 8.

Also checked those files plus `app/api/v1/sessions.py`, both new production modules, the entire new history_security directory, the new lifecycle file, and all seven tracked changed test files. Observed exit 1: **126 errors**, comprising existing errors and the attributable findings above. This larger count is not presented as 126 regressions. `sessions.py` has its two existing bare-dict annotations. Both new production modules and `test_msgchains_endpoint.py` have no errors in this configured run.

Built-in LSP independently finds no remaining tuple-size diagnostics in the msgchains fixture; its missing-pytest and implicit-relative-import environment noise is not counted as a product regression. The configured standalone checker supplies the attribution above. A pristine baseline checker run was not performed or fabricated; the new import edge and newly added test lines establish the cited regressions directly.

### Independent real-path probes

All probes used the supplied Python environment, real SQLAlchemy/SQLite fixtures, real services/routers/state machine/launcher, signed JWTs for HTTP paths, and fake external model/adapter/PDF I/O. Fixture generators were entered through `asynccontextmanager(fixture.__wrapped__)`, with proper cleanup and MonkeyPatch restoration. No files were created by the probes, and no sleeps/polling were used.

| Probe | Observed result |
| --- | --- |
| Actual POST conversation, Flow on, secret-bearing user | 200 and scrubbed live response; committed user WorkflowMessage contains API key; assistant row scrubbed. |
| Actual POST conversation, Flow off | 200 and scrubbed live response; committed user and assistant messages raw; assistant metadata raw. |
| Performer transcript persistence and publication | Storage masked, original RoleResult unchanged, raw topic retains key, conversation topic removes it. |
| Paused role persistence/event | Chain status paused; agents events running then paused. |
| Actual HTTP interview policy | 0.30 -> interviewing; 0.20 -> ready_for_review; session GET advertises 0.20; password envelopes remain valid JSON. |
| Deterministic pause -> HTTP approve -> background continuation | calls origin,next; completed; report only includes next's finding. |
| Autonomous continuation with request-driven external model | calls origin,origin,next; identical first model request across restart; completed. |
| Distinct valid step IDs, repeated order 1 | origin only; accepted next step never executes; completed, empty final report. |
| Repeated paused launcher entry | fifth duplicate reaches rate-limit branch; failed with ended_at set and pending approval retained. |
| Both lanes reject via signed HTTP | 200, killed, ended_at set, no later adapter call. |

An initial HTTP probe mistakenly used `/rescope-decide` and received router-level 404s. Those outputs were not attributed to the implementation. The probe was corrected to the inspected `/rescope` route and the approval/rejection matrix above was reproduced with 200 responses. The duplicate-launch reproduction in that initial command was independent of the HTTP path and remains valid.

Exact executed probe programs and tool outputs are in this child session's transcript. Locator:
`/Users/minsung.jung/.omo/agent/projects/offensive-security-963b73057cac/senpi-task/children/st_01a10e98/sessions/st_01a10e98/2026-10-06T00-23-12-012Z_01a10e97-cd8c-73c2-94a0-7238483c0b2c.jsonl`.

## Direct remove-ai-slops and programming review

Loaded and independently applied:

- `/Users/minsung.jung/.omo/binary-runtime/5.1.19/plugin/skills/remove-ai-slops/SKILL.md`
- `/Users/minsung.jung/.omo/binary-runtime/5.1.19/plugin/skills/programming/SKILL.md`
- `/Users/minsung.jung/.omo/binary-runtime/5.1.19/plugin/skills/programming/references/python/README.md`

The skills' cleanup instructions were not executed: this task explicitly permits only a gate report. Findings are classified against the supplied outcome criteria, not architecture preferences.

| Criterion / perspective | Direct assessment |
| --- | --- |
| Excessive/useless tests | The ownership/route matrix and target boundary matrix exercise distinct cases. No volume-based blocker. The extra `!= failed` assertion after `== paused` is redundant but harmless. |
| Deletion-only / requested-removal tests | None introduced. No test asserts that a particular implementation symbol or old code text disappeared. |
| Tautologies / false confidence | The autonomous model fake's global adapter-call counter acts as an external progress oracle that production cannot access. It masks B4's missing continuation state. The assertion only requiring next somewhere in calls also permits repeated completed work. This is a concrete false-confidence issue tied to P1C.RESUME. |
| Implementation-mirroring | Actual state machine, router, database and execution lanes are generally exercised rather than mocked. Invoking a BackgroundTask's stored func/args couples the test to framework internals and introduces a diagnostic; the independent HTTP test exercises the real surface instead. |
| Narrowness of masking tests | Legacy-row GET tests are useful. The added storage test covers assistant-only user content `go`, leaving the named user-write boundary untested; B3 reproduces the missed regression. |
| Prose/prompt pinning | No new natural-language phrase, prompt snapshot, or removal-copy tests found. State tokens and secret fixtures are machine-consumed behavior. |
| Nondeterminism | No added sleeps, polling delays, retry-to-green behavior, or timing-luck synchronization. New fixture UUIDs separate users and sessions; the actor-based rate bucket does not explain the full-suite pass/fail findings. |
| Root-cause placement / boundary completeness | Shared authorization across both routers fixes B1 at the right seam. Masking remains incomplete because the WorkflowService writers were not changed. The pause check is below an earlier mutation path. |
| Unnecessary extraction | Shared authorization and safety-layer masking have real multiple callers. In contrast, new pentest router wrappers are pass-throughs; `_scrub_payload` at line 236 has no references other than its declaration according to LSP. These are maintenance NOTES, not criterion failures. |
| Parsing / normalization | Parsing known serialized conversation envelopes is necessary for B5. The helper also attempts JSON parsing on every string leaf and reserializes all JSON containers; this is broader normalization than the known envelope seam requires. No additional demonstrated criterion failure, so NOTE only. |
| Type discipline | New `Any`/unannotated helper surfaces reduce static coverage despite zero configured errors in the two modules. The actual new errors, not stylistic typing preferences, block under B7. No new type-ignore or checker suppression was added. |
| Error handling / variants | Existing broad observability/rescope catches and string states remain. The diff distinguishes paused role errors correctly. Remaining repeated-entry misclassification is B2. No unrelated exception-hardening demand is added. |
| Scope / maintenance | Changes address the three named tasks; no unrelated feature implementation or Phase 2 lease system found in the scoped diff. Existing large modules and older weak typing do not justify a refactor gate. Repeated explanatory comments, stale three-value autonomous docstring, and unused imports are notes only. |

The prior `.omo/evidence/phase-1-p0-security-gate-review.md` explicitly records both skill perspectives and overfit/slop coverage, including excessive/useless tests, deletion-only tests, tautologies, implementation mirroring, and parsing/normalization. That report predates remediation. No separate round-2 code-review artifact or notepad path was supplied; `.omo/evidence/phase-1-evidence.md` is executor evidence and does not document a round-2 skill-perspective pass. This is an evidence NOTE, not an invented success criterion. Its absence does not substitute for or invalidate the direct review above.

## Constraint compliance and provenance

- Confirmed branch `feat/phase-1-p0-security`, HEAD `9414dad3097fc823d9bb882e435e9cd098df711d` before and after checks.
- Inspected `GIT_PAGER=cat git diff HEAD -- backend`. The first large output was truncated at its beginning; the missing pentest router diff was obtained separately. Read every new untracked history_security file and both new production helpers in full, plus the complete new lifecycle test.
- `GIT_PAGER=cat git diff HEAD --check -- backend/app backend/tests` exits 0.
- Existing test changes are contract adjustments: correct authorized users, authoritative project-owner fixtures, permitted 404 instead of 403, effective 0.20 threshold, actual Response fields, and the four-value lane result. No deleted, skipped, xfailed, or weakened kill/abort assertion was found in the diff. The new continuation assertion is incomplete, as detailed in B4, rather than an existing test removed to turn green.
- No implementation edits, staging, commits, checkout, branch changes, installs, or git-history writes were performed. The only authored file is this report. Unrelated frontend and operational edits were left untouched.
- No JS eval tool is exposed. Invoked the supplied SDK status operation through Node; it returned `ULW_LOOP_PLAN_MISSING` at `.omo/ulw-loop/01a10e97-cd8c-73c2-94a0-7238483c0b2c/goals.json`. Used the fallback evidence location with a re-review goal name so the prior report remains intact.
- No todo, monitor, or bash-output tool is exposed. Short captured foreground checks supplied exit codes and outputs; no inaccessible background handle is counted as evidence.

## Checked artifact paths

Brief/evidence/configuration:
- `.omo/evidence/phase-1-p0-security-gate-review.md` (prior review, retained unchanged)
- `.omo/evidence/phase-1-evidence.md`, including round-2 remediation
- `docs/phases/README.md`
- `docs/phases/phase-1-p0-security.md`
- `/tmp/osa-phase1-pyrightconfig.json`
- `.github/copilot-instructions.md`

Changed production diff/current referenced sections:
- `backend/app/api/v1/pentest_sessions.py`
- `backend/app/api/v1/sessions.py`
- `backend/app/api/v1/_session_security.py` (full)
- `backend/app/safety/history_masking.py` (full)
- `backend/app/orchestrator/ambiguity_loop.py` (full)
- `backend/app/orchestrator/executor.py`
- `backend/app/orchestrator/performer.py`
- `backend/app/orchestrator/rescope_service.py`
- `backend/app/orchestrator/service.py`

New tests, full contents:
- `backend/tests/integration/history_security/__init__.py`
- `backend/tests/integration/history_security/conftest.py`
- `backend/tests/integration/history_security/test_access.py`
- `backend/tests/integration/history_security/test_history.py`
- `backend/tests/integration/history_security/test_sibling_routes.py`
- `backend/tests/integration/test_rescope_execution_lifecycle.py`

Tracked changed tests, complete diff and checker/test execution:
- `backend/tests/api/test_pentest_execution_launcher.py`
- `backend/tests/api/test_pentest_sessions_create.py`
- `backend/tests/integration/test_ambiguity_loop_full.py`
- `backend/tests/integration/test_msgchains_endpoint.py`
- `backend/tests/integration/test_pentest_messages_history.py`
- `backend/tests/integration/test_terminal_replay.py`
- `backend/tests/integration/test_workflow_service_flag_on.py`

Supporting current behavior, read relevant sections:
- `backend/tests/conftest.py`
- `backend/app/orchestrator/workflow_service.py`
- `backend/app/orchestrator/roles/pentester.py`
- `backend/app/orchestrator/workflow_plan.py`
- `backend/app/safety/whitelist.py`
- `backend/app/core/events.py`
- `backend/app/core/config.py` (settings search)
- `backend/app/models/report.py`
- `backend/app/reports/generator.py`
- `frontend/src/components/WorkflowChat.tsx`
- `frontend/src/pages/PentestWorkflow.tsx`

## Exact evidence gaps and notes

1. No pristine baseline diagnostic run was supplied as an inspectable artifact or reproduced in a second checkout. The cited production cycle and eight new-test errors are directly attributable from the current diff and configured checker. Older diagnostics were not repackaged as new failures.
2. No live Docker/network scan, actual external model, Postgres deployment, browser, or WebSocket connection was exercised. The event-bus publisher and real ASGI HTTP boundaries were exercised; six environmental suite skips remain skips.
3. No separate remediation code-review artifact, named manual-QA artifact, or notepad path was supplied. This report supplies the independent manual matrix and direct skill review; the missing inputs are not blockers by themselves.
4. Frontend target wiring was inspected, not built or visually verified; no frontend implementation change was requested in this review.
5. The report approves no future commit. All exact-fix descriptions are recommendations only. Gate review is complete; implementation remains rejected for the four criterion-linked blockers above.
