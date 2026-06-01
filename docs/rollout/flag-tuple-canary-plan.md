# Flag-Tuple Canary Rollout Plan — W5/PR5.4

## Overview

This document defines the staged rollout strategy for transitioning sessions from the
v1.1 baseline flag-tuple (T1) to the full XBOW flag-tuple (T4) via four discrete
tuples: T1, T2, T3, T4. Each forward transition is gated by a GA milestone and uses
deterministic cohort assignment so sessions are sticky throughout their lifetime.

Backward (rollback) transitions use the same SLA and cohort mechanics in reverse order.

---

## Tuple Definitions

| Tuple | Description                                      |
|-------|--------------------------------------------------|
| T1    | v1.1 baseline — provider routing only            |
| T2    | + W1 LLM gateway (credential audit enabled)      |
| T3    | + W2b coordinator (iteration cap, scrub circuit) |
| T4    | + W3/W4 full XBOW (IMAGE_REGEX, oob_callback, mitm) |

---

## Transition Matrix

| From | To | Trigger | Cohort progression | Watch metrics | Rollback trigger |
|------|----|---------|--------------------|---------------|------------------|
| T1 | T2 | W1 GA gate | 10% → 50% → 100% over 7 days | per-provider 5xx rate, p95 LLM latency, credential audit cleanliness | any non-zero credential leak; p95 > +25% baseline |
| T2 | T3 | W2b GA gate | Opt-in beta (per-team admin toggle) | coordinator iteration p95, conversation scrub circuit trip rate | any L3 canary leak; coordinator iteration cap hit rate > 1% |
| T3 | T4 | W3+W4 GA gate, security-review sign-off | 10% → 50% → 100% over 14 days | IMAGE_REGEX rejects, oob_callback correlation, mitm dropped frames | any IMAGE_REGEX bypass; oob mismatch > 0 |

---

## Cohort Selection Rules

Cohort assignment is deterministic and based on the session identifier:

```
cohort_bucket = sha256(session_id.bytes)[0] % 100
```

- **10% cohort**: sessions where `cohort_bucket < 10`
- **50% cohort**: sessions where `cohort_bucket < 50`
- **100% cohort**: all sessions (`cohort_bucket < 100`)

**Stickiness**: A session that begins on a given tuple stays on that tuple for its entire
lifetime regardless of subsequent cohort percentage changes. The tuple is resolved once at
session creation and stored in session state.

---

## SLA

| Metric | Target |
|--------|--------|
| Single tuple flip time (deploy → traffic on new tuple) | ≤ 10 minutes |
| Rollback flip time | ≤ 10 minutes |
| Minimum soak duration per cohort level | 24 hours before promoting to next cohort level |

The 10 minute SLA applies to both forward and reverse transitions. It measures wall-clock
time from the moment the new `active_percentage` value is written to configuration until
all new sessions are being assigned the target tuple.

---

## Soak Schedule: T1 → T2 (7-day example)

| Day | active_percentage | Cohort | Action |
|-----|-------------------|--------|--------|
| 0   | 0                 | 0%     | Deploy T2 code; no traffic yet |
| 1   | 10                | 10%    | Begin soak; monitor metrics 24 h |
| 2   | 10                | 10%    | Soak continues |
| 3   | 50                | 50%    | Promote if Day 1–2 metrics clean |
| 4   | 50                | 50%    | Soak continues |
| 5   | 50                | 50%    | Soak continues |
| 6   | 100               | 100%   | Promote if Day 3–5 metrics clean |
| 7   | 100               | 100%   | GA — T2 is now baseline |

---

## Soak Schedule: T3 → T4 (14-day example)

| Day  | active_percentage | Cohort | Action |
|------|-------------------|--------|--------|
| 0    | 0                 | 0%     | Deploy T4 code; no traffic yet |
| 1–3  | 10                | 10%    | Begin soak; 72 h minimum |
| 4–7  | 50                | 50%    | Promote if Day 1–3 metrics clean |
| 8–14 | 100               | 100%   | Promote if Day 4–7 metrics clean |
| 15   | 100               | 100%   | GA — T4 is now baseline |

---

## Reverse Rollback Path

Full rollback path in reverse order:

```
T4 → T3 → T2 → T1
```

Each reverse step is the exact inverse of its forward counterpart:

- Same cohort mechanics (hash-based determinism)
- Same ≤ 10 minute flip SLA
- Cohort steps are reversed: 100% → 50% → 10% → 0%
- Sessions already in flight on the higher tuple complete on that tuple;
  only newly created sessions are assigned the lower tuple

**Rollback is never partial across non-adjacent tuples.** T4 must roll back through T3
before reaching T2; skipping tuples is not permitted.

---

## Audit Signals

All tuple transition events emit structured audit log entries via the existing
`AuditLogger` infrastructure.

| Event name | Emitted when |
|------------|-------------|
| `feature_flag.tuple_transition_started` | `active_percentage` changes from prior value |
| `feature_flag.tuple_transition_completed` | 100% cohort is live on the target tuple |
| `canary.cohort_promoted` | cohort level advances (10% → 50%, 50% → 100%) |
| `canary.cohort_rollback` | cohort level decreases during a rollback |
| `canary.sla_breach` | flip time exceeds MAX_FLIP_SECONDS (600 s) |

All events include: `session_id`, `from_tuple`, `to_tuple`, `active_percentage`,
`cohort_bucket`, `timestamp_utc`.

---

## Decision Matrix: Promote / Hold / Rollback

| Decision | Condition |
|----------|-----------|
| **Promote** | All soak metrics within threshold AND zero critical pages during soak window |
| **Hold** | Any WARN-level metric breach (no page yet); extend soak by 24 h and re-evaluate |
| **Rollback** | Any CRITICAL page OR any paged audit event (e.g., credential leak, IMAGE_REGEX bypass) |

### Metric thresholds by transition

**T1 → T2**

| Metric | WARN | CRITICAL |
|--------|------|----------|
| per-provider 5xx rate | > +10% relative | > +25% relative |
| p95 LLM latency | > +15% relative | > +25% relative |
| credential audit cleanliness | any warning-level entry | any non-zero leak |

**T2 → T3**

| Metric | WARN | CRITICAL |
|--------|------|----------|
| coordinator iteration p95 | > cap × 0.8 | cap hit rate > 1% |
| conversation scrub circuit trips | any trip in 10% cohort | L3 canary leak |

**T3 → T4**

| Metric | WARN | CRITICAL |
|--------|------|----------|
| IMAGE_REGEX rejects (unexpected) | any unexpected bypass attempt logged | confirmed bypass |
| oob_callback correlation | mismatch rate > 0 over 1 h | mismatch rate > 0 over 10 min |
| mitm dropped frames | > 0.1% of frames | > 1% of frames |

---

## Operator Runbook Summary

1. Confirm GA gate is signed off (JIRA ticket + security-review approval for T3→T4).
2. Set `active_percentage` to 10 via config update; verify audit log emits
   `feature_flag.tuple_transition_started`.
3. Monitor dashboards for 24 h minimum soak.
4. If metrics are clean, advance `active_percentage` to 50; soak again.
5. If metrics are clean, advance `active_percentage` to 100.
6. Verify audit log emits `feature_flag.tuple_transition_completed`.
7. Update baseline_tuple in config to the new tuple.
8. Archive soak metrics snapshot in rollout log.

For rollback: reverse steps 7 → 1, setting `active_percentage` back to 0 and
`baseline_tuple` to the previous value. Rollback must complete within ≤ 10 minutes.

---

## References

- `backend/app/core/flag_tuple_progression.py` — cohort assignment and tuple resolution
- `backend/app/core/feature_flag_validator.py` — supported tuple registry
- `backend/app/safety/audit.py` — AuditLogger for transition events
- `docs/observability/` — dashboard definitions
- `docs/runbooks/` — incident response procedures
