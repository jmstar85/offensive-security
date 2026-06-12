# C7 Safety-Chain Decomposition — Sign-off (Residual Concern #3)

**Scope:** the OSA→XBOW autonomous lane (`osa_xbow_autonomous_enabled`).
**Status:** the immutable safety chain is a **distributed, test-enforced property** — no
single function runs the full spec-ordered chain end-to-end. This document records why
that is correct and how it is enforced, per Residual Concern #3 of
`.omc/plans/ralplan-osa-xbow-autonomous-v1.md`.

## The spec chain vs. the as-built decomposition

Spec (single conceptual chain):
`filter_plan_steps → filter_by_tier_flags → RiskFilter → shims → backend hardening → IMAGE_REGEX → egress → kill-reg → rescope → shim-audit`

As-built, this is split into **two seams** so the deterministic lane stays
byte-identical and both lanes share one audited runtime choke point:

1. **Plan-time filter trio** (`filter_plan_steps → filter_by_tier_flags → RiskFilter`),
   run at *plan cardinality per lane*:
   - deterministic lane: `OrchestratorService.run` (`service.py:268-291`), unchanged.
   - autonomous lane: per-dispatch in `Performer._dispatch_tool` (the tier gate added
     in PR4a), so an unapproved active/exploit-tier dispatch is blocked on
     `session.approval_flags`.
2. **Runtime brake envelope**, owned by the ONE shared helper
   `safety_exec.execute_tool_through_safety_chain` (the only sanctioned
   `adapter.execute` call site): shims/IMAGE_REGEX → per-log `EgressMonitor` + kill →
   container-id kill registration → `SafetyViolation`/`persist_kali_shim_block`. The
   rescope harvest + `RescopeService.pause_for_rescope` runs in each caller *after*
   row finalization (preserving v1.1 ordering).

## Why the decomposition is safe

- **No tool container is reached except through the runtime helper** — enforced
  structurally by `tests/ast/test_adapter_execute_only_via_safety_helper.py` (adapter
  `.execute` may appear ONLY in `safety_exec.py::execute_tool_through_safety_chain`).
- **The tier gate is a per-lane single-source-of-truth**, not physical co-location:
  deterministic at `service.py:274`; autonomous per-dispatch in `_dispatch_tool`.
- **Exploit execution stays human-gated (D4):** active-exploit-tier steps require
  `approved_active_exploit`; a new-host discovery pauses for human approval (rescope).

## Test enforcement (the invariant is asserted, not assumed)

| Property | Test |
|----------|------|
| Adapter-execute only in the helper | `tests/ast/test_adapter_execute_only_via_safety_helper.py` |
| Runtime envelope order (deterministic path) | `tests/safety/test_safety_chain_full_envelope_spy.py` |
| Autonomous per-dispatch trio incl. tier gate, then helper | `tests/safety/test_safety_chain_full_envelope_spy.py::test_autonomous_dispatch_runs_filter_trio_with_tier_gate_then_runtime_helper` |
| Tier gate blocks unapproved active-tier dispatch | `tests/integration/test_autonomous_dispatch_safety.py::test_autonomous_tier_gate_blocks_unapproved` |
| Egress kill / kill-reg / rescope / shim-audit on the autonomous path | `tests/integration/test_autonomous_dispatch_safety.py` |
| Egress detection widened (IPv4 verbs / IPv6 / SNI / Host) | `tests/safety/test_live_path_safety_verification.py` |
| Conversation scrubber on the live role-turn publish | `tests/safety/test_live_path_safety_verification.py::test_scrubber_runs_on_live_role_turn_publish` |
| Deterministic lane byte-identical (flags off) | `tests/regression/test_planexecutor_refactor_byte_identical.py`, `test_deterministic_lane_unchanged_with_xbow_off.py` |

## Residual gaps explicitly accepted for the recon-only milestone

- **Egress is log-pattern based, not full DPI.** The widened patterns are anchored to
  connection-indicating contexts (Connecting/CONNECT/SNI/Host/DNS-query). Host checking
  only engages when a domain scope is defined (no false-positive kills otherwise). True
  packet-level egress (a sidecar firewall / MITM enforce) remains future work.
- **MITM egress routing** is Attack-family-only and flag-gated (`osa_traffic_via_mitm`);
  verified at the role level, not yet end-to-end through a live mitmproxy sidecar.

**Sign-off:** the distributed chain above is the accepted C7 design for the autonomous
lane. Acceptance is contingent on the listed tests remaining green in CI.
