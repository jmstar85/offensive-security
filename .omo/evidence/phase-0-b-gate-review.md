# Phase 0-b independent gate review

recommendation: APPROVE

blockers: []

originalIntent: Establish a trustworthy Phase 0 backend baseline by removing cross-test provider identity interference and separating genuine Docker unavailability from product failures.

desiredOutcome: The documented suite completes green in one invocation, normalization still exercises real provider constructors, router mocks bind to the consumed class, and live replay remains sensitive to row count, order, and contents without depending on elapsed wall time.

userOutcomeReview: The eight-file candidate satisfies the requested behavior. No criterion-linked implementation defect was found. Approval covers this staged candidate, not a future commit or a real daemon-present execution that this machine cannot provide.

## Scope and provenance

- Branch: `feat/phase-0-repo-baseline`.
- HEAD and merge-base with `c909c41`: `c909c416442be4a510a6b2ee7df9b83a372fceda`.
- Exactly eight staged files; six modifications and two additions. Both additions were read in full.
- Inspected the scoped diff against `c909c41`, then `git diff HEAD` for the newly staged additions. Scoped `git diff HEAD --check` was clean.
- `git diff HEAD --name-only -- backend/app backend/tests/conftest.py` produced no paths. Production and root test fixtures are unchanged.
- No implementation edits, installs, branch changes, staging, commits, or history writes were performed by this reviewer. Unrelated frontend and operational changes were not reviewed.
- No JS eval tool is exposed in this child. The local `.omo` directory contained no ULW plan or attempt directory, so this report uses the requested fallback evidence location.

## Acceptance breakdown

The IDs below map the supplied requirements; they are reviewer labels, not pre-existing repository IDs.

| Criterion | Result | Evidence and reasoning |
| --- | --- | --- |
| C1: Remove stale Anthropic identity and unintended external requests | PASS | `backend/tests/unit/test_provider_response_normalization.py:33-38` patches the SDK constructor used by the existing class rather than reloading its module. Both explicit provider/routing file orders independently passed 16 tests. Manual normalization followed by `LLMRouter.get_client` retained the original class and consumed the patch on its `send` method. |
| C2: Preserve normalization coverage and constructor paths | PASS | All three original response type/text/token assertions remain. Anthropic, OpenAI, and Google use their real constructors; the SDK calls and raw response identity are additionally checked. OpenAI/Google no longer bypass construction with `__new__`. Manual calls to all three normalization tests confirmed scoped SDK/module restoration. |
| C3: Three Docker tests use configured daemon availability without hiding SDK/product defects | PASS for locally available paths | `backend/tests/unit/conftest.py:17-23` calls the same `docker.from_env` configuration seam as the real Docker backend. It skips only Docker exceptions caused by Requests connection failures/timeouts; other causes propagate. Actual local missing-socket execution skipped precisely the three named tests. Five guard tests passed, including available-client closure and non-connection exception propagation. Product assertions execute outside the guard's exception handler. Real daemon-present execution remains unavailable and is not claimed. |
| C4: Documented full suite green in one final invocation | PASS | Independent captured run: **1142 passed, 6 skipped, 51 warnings in 4.87s**. No retry, rerun-failures option, test removal, or ordering override was used within that invocation. Three skips were the new Docker guards; three were existing scrubber/staging/opt-in exclusions. |
| C5: Real public API and executor paths manually verified | PASS | Independent direct `LLMRouter.get_client -> AnthropicProvider.send` call returned normalized text/tokens/raw through a fake SDK transport; the original class's send mock was consumed and SDK/module bindings restored. Two `run_saved_workflow_once` calls used the real `PlanExecutor` and real in-memory SQLite fixture. Both completed `nmap -> httpx`. |
| C6: Replay fix removes wall-clock luck while preserving regression visibility | PASS | `backend/tests/regression/_live_replay_harness.py:185-193` scopes the clock to the executor during each run and advances it per call. Observed starts were `2026-01-01T00:00:00` and `2026-01-01T00:00:00.003000`, identical across runs and strictly increasing within a run. The original executor datetime binding was restored afterward. The owner comparator uses `tolerance_ms=0` at `test_planexecutor_refactor_byte_identical.py:57-59`. Existing explicit count, plan-order, and completed-status assertions remain. |
| C7: Requested base, narrow scope, and approval before commit | PASS at review boundary | Branch/HEAD/merge-base checks match the requested base, with exactly eight staged paths. No commit exists yet. The future commit must retain all five requested Lore trailers: `Constraint`, `Rejected`, `Confidence`, `Scope-risk`, and `Not-tested`. Its actual message is not yet verifiable. |
| C8: Diagnostics assessed against baseline, without unrelated cleanup | ACCEPT disclosed baseline | The supplied final/baseline LSP result is seven files with zero errors and the harness with the same ten `reportMissingTypeArgument` errors and 34 warnings. These are not characterized as new errors or zero total errors. The harness diff leaves its raw-dict annotations unchanged. This child's LSP tool returned a cached missing-server error; the raw parent JSON-RPC diagnostic outputs were not supplied as readable artifacts, so those exact diagnostic counts were not independently reproduced here. |

## Direct clock/regression analysis

The new clock supplies timestamps at the existing production call sites; it does not rewrite captured rows, sort by expected plan order, fabricate findings, or replace the executor/database. `_agent_execution_rows` still orders actual persisted rows by `(started_at, id)` at `backend/tests/regression/_live_replay_harness.py:137-140`. Distinct advancing timestamps avoid random UUID tie-breaking that a frozen clock would introduce. The owner test still checks expected plan order explicitly at `backend/tests/regression/test_planexecutor_refactor_byte_identical.py:76-99`.

The manual review also passed altered captured rows into the unchanged comparator and confirmed it reports reversed order, removed rows, changed findings, and a 1 ms timestamp difference with zero tolerance. These probes demonstrate comparator sensitivity; they are not represented as mutations of production code. The clock does not promise to test real latency, and actual elapsed time is outside this replay criterion. Existing two-current-run comparisons are determinism tests rather than universal golden-output tests; this pre-existing limitation does not become a new blocker from removing wall-clock noise.

## Independent programming and remove-ai-slops pass

Loaded both skills from `/Users/minsung.jung/.omo/binary-runtime/5.1.19/plugin/skills/`, including `programming/references/python/README.md`, and applied them directly to the diff, complete scoped tests, and the consumed production seams.

- Excessive/useless tests: none introduced. The five guard cases cover distinct availability, failure propagation, and cleanup behavior. The three provider tests remain three tests.
- Deletion-only/removal-pinning tests: none. No test asserts that reload text or a removed symbol is absent.
- Tautologies: the provider tests execute actual normalization and compare independent fixture values. The guard tests invoke the real pytest fixture. The replay path reads actual database rows rather than comparing supplied fakes to themselves.
- Implementation-mirroring: SDK constructor/request assertions check the requested construction and transport boundary, alongside observable normalized outputs. They do not replace those output assertions. Guard factory/close assertions establish the configured endpoint probe and resource lifecycle.
- Unnecessary extraction/parsing/normalization: none added to production. The shared fixture has three real callers; the clock is inline in the existing harness. No new generic helper, fallback layer, dependency, or production parser was introduced.
- Error handling and resource ownership: the fixture narrows connection failures, rethrows other causes, and closes a successful probe through `contextlib.closing`. It does not wrap the product assertions in a skip handler.
- Async/isolation: normalization now awaits through the existing pytest async setup. Monkeypatch restoration replaces module reload and constructor bypass. No sleep, polling delay, or widened time tolerance was added.
- Typing/scope: previous test type-ignore assignments were removed; no suppression was added. Existing raw-dict harness annotations were not expanded into an unrelated typing migration.
- No new maintenance-burden or scope-drift finding warrants rejection.

No separate upstream code-review report or notepad path was supplied. Consequently, another report's explicit skill/overfit coverage cannot be confirmed. This report records the independent check rather than claiming that absent report was inspected. Neither missing input is identified as a required phase acceptance artifact, so it is an evidence NOTE, not a blocker.

## Findings and residual risks, severity-ranked

No blocking findings.

1. **NOTE - Real daemon-present path not exercised.** `backend/tests/unit/conftest.py:18` and the three guarded tests depend on a reachable configured daemon. Local execution proves missing-socket skipping; `backend/tests/unit/test_docker_daemon_guard.py:37-47` proves the success/closure branch with a scoped fake. Preserve this limitation in the commit's `Not-tested` trailer.
2. **NOTE - Diagnostic transport/artifact gap.** The parent reports an independently matched baseline/final harness result of ten errors and 34 warnings. This child's built-in LSP endpoint failed before analysis, and no raw diagnostic artifact path was provided in `/tmp/osa-phase0-evidence.md`. Do not describe the change as zero total LSP errors. No unrelated typing cleanup is requested.
3. **NOTE - Existing test warning remains.** Both explicit provider-order runs emitted the existing unawaited AsyncMock warning at `backend/app/orchestrator/performer.py:334`, exercised by `tests/orchestrator/test_per_role_routing.py::test_full_topological_chain_completes_through_launch_site`. It does not fail the requested checks and is outside this diff.
4. **NOTE - Prior-review provenance unavailable.** `/tmp/osa-phase0-evidence.md` contains a QA matrix and parent session handles, but not readable raw logs for those handles, a separate code-review artifact, or a notepad path. Runtime claims relevant to approval were reproduced directly instead of trusting their prose. The exact parent diagnostic counts remain disclosed evidence, not an independent result of this child.

## Commands and observed verification

Full suite, from `backend`:

```sh
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=.:.venv/lib/python3.13/site-packages \
OSA_E2E_DOCKER_SCANME=0 OSA_E2E_DVWA_URL='' OSA_E2E_JUICE_URL='' \
/Users/minsung.jung/.local/bin/python3.13 -m pytest -q -rs -p no:cacheprovider \
  tests/unit tests/orchestrator tests/api tests/ast tests/infra \
  tests/regression tests/integration --disable-warnings --tb=short
```

Observed: 1142 passed, 6 skipped, 51 warnings; command returned successfully. The separate forward/reverse/guard command chain printed `GATE_ORDER_AND_GUARD_EXIT=0`, with 16 passed, 16 passed, and 5 passed respectively.

Manual public-path command printed:

```text
PASS real normalization -> router -> original provider; SDK and imported modules restored; send mock consumed
PASS real SQLite PlanExecutor double replay; exact timestamps, strict order, clock restored; comparator detects order/count/findings/timestamp changes
timestamps: ['2026-01-01T00:00:00', '2026-01-01T00:00:00.003000']
```

Initial background test launches returned handles without accessible output/session tools in this child. Their results are not counted as evidence. The captured foreground invocations above supply the independently observed results, rather than inferring success from those handles.

## Checked artifact paths

Required briefs/evidence:
- `docs/phases/README.md`
- `docs/phases/phase-0-repo-baseline.md`
- `/tmp/osa-phase0-evidence.md`

Complete scoped files:
- `backend/tests/unit/conftest.py`
- `backend/tests/unit/test_docker_daemon_guard.py`
- `backend/tests/unit/test_katana_zap_adapters.py`
- `backend/tests/unit/test_registry_palette.py`
- `backend/tests/unit/test_kali_exec_adapter.py`
- `backend/tests/unit/test_provider_response_normalization.py`
- `backend/tests/regression/_live_replay_harness.py`
- `backend/tests/regression/test_planexecutor_refactor_byte_identical.py`

Supporting code inspected only to trace the requested behavior:
- `backend/app/orchestrator/llm/anthropic_provider.py`
- `backend/app/orchestrator/llm/openai_provider.py`
- `backend/app/orchestrator/llm/google_provider.py`
- `backend/app/orchestrator/llm/router.py`
- `backend/app/orchestrator/executor.py`
- `backend/app/agents/backends/docker.py` (constructor section)
- `backend/.venv/lib/python3.13/site-packages/docker/api/client.py` (API negotiation/error-chaining section)
- `backend/tests/conftest.py`
- `backend/tests/_regression/v11_comparator.py`
- `backend/tests/regression/test_deterministic_lane_unchanged_with_xbow_off.py`
- `backend/tests/orchestrator/test_per_role_routing.py` (routing/identity cases)

Independent tool-output provenance is retained in this child session:
`/Users/minsung.jung/.omo/agent/projects/offensive-security-963b73057cac/senpi-task/children/st_01a10c01/sessions/st_01a10c01/2026-10-05T12-19-36-170Z_01a10c01-546a-758e-8491-735287d96153.jsonl`.
