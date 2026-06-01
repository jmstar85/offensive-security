# STRIDE Deep Dive — Surface 1: Coordinator

> **Surface:** `CoordinatorService.run` + `run_with_iteration_cap`
> **Threat model version:** 2.0
> **Wave coverage:** W2a (PR2a.3), W4 (PR4.2)
> **Last updated:** 2026-06-01

---

## Overview

The Coordinator is the central orchestration component. It drives the LLM-in-the-loop attack
planning loop, enforces resource caps (iteration, wall-clock, token), and emits structured audit
events. As the highest-privilege internal service, it is the most critical surface in the system.

---

## Spoofing

### Threat S-1: Sub-agent forges coordinator identity to bypass iteration cap
- **Scenario:** A compromised or adversarially-prompted sub-agent sends messages claiming to
  originate from the coordinator, attempting to reset or bypass the iteration counter.
- **Likelihood:** Medium — prompt injection into sub-agents is a known LLM attack vector.
- **Impact:** High — bypass of iteration cap could allow unbounded compute/cost.
- **Existing v2.0 mitigation:** JWT sub-claim validated on every coordinator call; coordinator
  instance ID bound to session at creation time and re-verified on each iteration step.
  Proved by: `backend/tests/safety/test_adversarial_prompts.py` — includes coordinator impersonation
  adversarial corpus entries.
- **Residual risk:** Low. A compromised JWT signing key would break this; mitigated by KMS-backed
  JWT secret rotation.
- **Owner:** Security team

### Threat S-2: Replay of old coordinator token to resume a capped session
- **Scenario:** Attacker captures a coordinator session token before cap exhaustion and replays
  it after cap to continue attack execution.
- **Likelihood:** Low — requires token capture (MITM or memory dump).
- **Impact:** High — cap bypass restores unbounded execution.
- **Existing v2.0 mitigation:** Session nonce invalidated on cap exhaustion (nonce rotated and old
  nonce blocklisted); MF-CRITIC-1 coordinator-deleted-from-replay invariant prevents session
  records from being purged to cover tracks.
  Proved by: `backend/tests/e2e/test_attack_matrix.py` — session lifecycle tests.
- **Residual risk:** Low. Token capture via memory dump requires host-level compromise.
- **Owner:** Infra team

---

## Tampering

### Threat T-1: Adversarial LLM output mutates coordinator state between iterations
- **Scenario:** Crafted LLM response includes content that, when parsed, triggers unexpected state
  transitions in the coordinator (e.g., serialised object injection).
- **Likelihood:** Medium — LLM outputs are untrusted by definition.
- **Impact:** High — arbitrary state mutation could skip safety checks.
- **Existing v2.0 mitigation:** Immutable iteration log with HMAC chain; state transitions validated
  against schema before commit; LLM output never directly deserialised into state objects.
  Proved by: `backend/tests/safety/test_adversarial_prompts.py`.
- **Residual risk:** Medium. Novel serialisation gadget chains in new dependencies may not be covered.
  Quarterly SBOM review is the monitoring control.
- **Owner:** Backend team

### Threat T-2: Feature flag toggled mid-session to bypass safety checks
- **Scenario:** An operator or compromised service toggles a feature flag (e.g., disabling scrubber
  or raw_conversation gate) while a session is active.
- **Likelihood:** Low — feature flag mutation requires elevated access.
- **Impact:** Critical — could disable all safety controls for active session.
- **Existing v2.0 mitigation:** `feature_flag_validator` locks the pairwise feature tuple at session
  creation; mutations during a session are rejected with 409 Conflict; MF-CRITIC-8 pairwise matrix
  enforced at both session start and each iteration.
  Proved by: `backend/tests/e2e/test_attack_matrix.py` — feature flag mutation tests.
- **Residual risk:** Low.
- **Owner:** Backend team

---

## Repudiation

### Threat R-1: No audit trail for coordinator cap events
- **Scenario:** Coordinator hits iteration/wall-clock/token cap but no record is retained, making
  it impossible to investigate whether caps were legitimately reached or attacked.
- **Likelihood:** N/A (design question, not external attack).
- **Impact:** High — without audit, post-incident investigation is impossible.
- **Existing v2.0 mitigation:** Every cap event emits a structured audit log entry: event type,
  cap type, session ID, iteration count, token counts, wall-clock elapsed, UTC timestamp.
  Proved by: `backend/tests/observability/` — per-family token metrics tests (PR4.4).
- **Residual risk:** Low. Log tampering is mitigated by immutable log sink.
- **Owner:** Platform team

### Threat R-2: Coordinator events deleted from replay buffer
- **Scenario:** Attacker or malicious LLM output causes coordinator events to be purged from the
  session replay buffer, hiding coordinator actions from forensic review.
- **Likelihood:** Low-Medium — replay purge is a privileged operation but prompt injection
  could trigger it if the discriminator is not enforced.
- **Impact:** High — loss of replay fidelity undermines all post-incident investigation.
- **Existing v2.0 mitigation:** MF-CRITIC-1 opt-out lane discriminator tags all coordinator events
  with `_lane: "coordinator"`; purge logic filters on `_lane != "coordinator"` before deletion;
  scrubber pipeline skips coordinator-lane events entirely.
  Proved by: `backend/tests/safety/test_adversarial_prompts.py` — MF-CRITIC-1 corpus entry.
- **Residual risk:** Low.
- **Owner:** Backend team

---

## Information Disclosure

### Threat I-1: Coordinator exposes internal LLM reasoning in error responses
- **Scenario:** Exception or error condition causes raw LLM response or internal state to be
  returned in a 500 error body visible to the operator.
- **Likelihood:** Medium — error handling is a common source of information leaks.
- **Impact:** Medium — reveals attack strategy internals; may expose PII from LLM context.
- **Existing v2.0 mitigation:** Error sanitisation layer strips LLM content from all API error
  responses; only safe error codes and messages returned; scrubber applied to any error
  body that references session content.
- **Residual risk:** Medium. Novel exception paths may bypass the sanitiser. Error path coverage
  is a monitoring gap; quarterly security review of error logs recommended.
- **Owner:** Backend team

### Threat I-2: Token usage leaks cost/capability information
- **Scenario:** Per-family token metrics returned in API responses expose information about which
  LLM families are being used and at what cost, aiding competitive intelligence or attack planning.
- **Likelihood:** Low — metrics are internal by default.
- **Impact:** Low-Medium.
- **Existing v2.0 mitigation:** Per-family token metrics behind TEAM_ADMIN gate; raw usage never
  in operator-visible responses; FlowConsole cost header only in TEAM_ADMIN sessions.
  Proved by: `backend/tests/observability/` (PR4.4).
- **Residual risk:** Low.
- **Owner:** Security team

---

## Denial of Service

### Threat D-1: Infinite loop exhausts compute/cost budget
- **Scenario:** Adversarial prompt engineering causes the LLM to enter a loop of self-reinforcing
  tool calls that never converge, exhausting token budget and incurring unbounded cost.
- **Likelihood:** High — well-documented LLM attack pattern.
- **Impact:** Critical — unbounded cost; potential platform unavailability.
- **Existing v2.0 mitigation:** `run_with_iteration_cap` enforces: hard iteration limit (default 50),
  wall-clock cap (default 30 min), token budget (per-family, configurable). Cap hit on ANY metric
  terminates the session and emits audit event. All three caps are enforced before each step.
  Proved by: `backend/tests/` — coordinator cap tests (PR4.2).
- **Residual risk:** Low. Cap values are configurable; misconfiguration could set them too high.
  Cap value ranges are validated at startup.
- **Owner:** Backend team

### Threat D-2: Prompt injection causes runaway tool calls
- **Scenario:** Injected content in a tool response triggers a cascade of additional tool invocations
  per iteration, exhausting token budget faster than the iteration cap can trigger.
- **Likelihood:** Medium.
- **Impact:** High — cost explosion; other sessions starved.
- **Existing v2.0 mitigation:** Tool-call count per iteration capped (default 10); coordinator aborts
  iteration if threshold breached and emits `coordinator.tool_call_cap_hit` audit event.
- **Residual risk:** Low-Medium. Cap interacts with token budget; a very high per-tool-call token
  cost could still exhaust budget before tool-call cap triggers.
- **Owner:** Backend team

---

## Elevation of Privilege

### Threat E-1: Sub-agent requests TEAM_ADMIN operation via crafted coordinator payload
- **Scenario:** Malicious sub-agent crafts a coordinator payload that requests a TEAM_ADMIN
  privileged action (e.g., raw_conversation access or credential vault write).
- **Likelihood:** Medium — sub-agents handle untrusted LLM output.
- **Impact:** High — TEAM_ADMIN access to raw conversations or credentials.
- **Existing v2.0 mitigation:** Role check re-evaluated per request at the API boundary; coordinator
  cannot elevate its own role; sub-agent requests are mediated by the coordinator which is bound to
  the operator's original role claim.
- **Residual risk:** Low.
- **Owner:** Security team

### Threat E-2: Compromised coordinator gains access to raw_conversation
- **Scenario:** A compromised coordinator component attempts to open the raw_conversation WebSocket
  channel, bypassing the TEAM_ADMIN gate.
- **Likelihood:** Low — coordinator compromise requires significant prior access.
- **Impact:** High — access to all unredacted session conversations.
- **Existing v2.0 mitigation:** `raw_conversation` channel gated exclusively on `accept_raw=true`
  + TEAM_ADMIN role claim; WebSocket close 4003 on failure; coordinator identity is not a TEAM_ADMIN
  by default; gate enforced in WebSocket middleware independent of coordinator.
  Proved by: E2E test suite WebSocket close-4003 tests.
- **Residual risk:** Low.
- **Owner:** Security team

---

## Residual Risk Summary

| ID | Category | Residual Risk | Owner | Monitoring |
|----|----------|---------------|-------|------------|
| RR-C1 | Tampering | Novel serialisation gadget in new dependency | Backend team | Quarterly SBOM diff review |
| RR-C2 | Info Disclosure | Novel exception path bypasses error sanitiser | Backend team | Quarterly error log security review |
| RR-C3 | DoS | Tool-call budget/cap interaction under adversarial load | Backend team | `coordinator.token_budget_exceeded_rate` alert |
