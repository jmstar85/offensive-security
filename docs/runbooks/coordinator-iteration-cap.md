# Runbook: coordinator.iteration_cap_hit

**Severity:** WARN
**Owner:** on-call SRE
**SLA:** 15 minutes to acknowledge, 30 minutes to mitigate

## Symptom

The coordinator service hit its maximum allowed iterations (`max_coordinator_iterations`) or wall-clock cap (`max_coordinator_wall_clock_seconds`) or total token cap (`max_coordinator_total_tokens`) for a session.

Prometheus query:
```
increase(osa_domain_agent_dispatch_total{result="cap_hit"}[10m]) > 0
```

Dashboard: `OSA / Coordinator` panel "Iteration Cap Events".

Audit log action: `coordinator.iteration_cap_hit`

## Likely causes

- Target scope too broad — coordinator iterating over too many sub-tasks.
- Token-heavy prompts causing `max_coordinator_total_tokens=200000` to be hit before completion.
- Wall-clock cap (`max_coordinator_wall_clock_seconds=600`) hit due to slow LLM provider responses.
- Bug causing coordinator to loop without progress (check for repeated identical steps in audit details).

## Triage steps

1. Confirm event in audit_logs:
   ```sql
   SELECT target_id, details_json, created_at
   FROM audit_logs
   WHERE action = 'coordinator.iteration_cap_hit'
   ORDER BY created_at DESC LIMIT 20;
   ```
2. Check the `details_json` — it includes `iterations`, `wall_clock_seconds`, `total_tokens`, and `cap_reason`.
3. Look for replay drift correlation:
   ```sql
   SELECT * FROM audit_logs
   WHERE action = 'coordinator.replay_drift_detected'
     AND target_id = '<session_id>'
   ORDER BY created_at DESC;
   ```
4. Check token spend for session:
   ```
   osa_family_tokens_total{session_id="<id>"}
   ```
5. Determine if the cap prevented a valid or runaway execution.

## Mitigation

- Immediate: If session is stuck, terminate via `DELETE /api/v1/pentest-sessions/{id}`.
- Raise `MAX_COORDINATOR_ITERATIONS` or `MAX_COORDINATOR_WALL_CLOCK_SECONDS` in `.env` if legitimate workload exceeds defaults.
- If token cap hit: raise `MAX_COORDINATOR_TOTAL_TOKENS` cautiously — check budget guard first (see [[cost-budget-exceeded]]).

## Rollback

- Revert any cap environment variable changes and restart the backend service.

## Related runbooks

- [[cost-budget-exceeded]]
- [[coordinator-skipped-for-replay-lane]]
- [[unsupported-flag-topology]]
