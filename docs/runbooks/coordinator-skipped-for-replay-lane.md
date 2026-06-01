# Runbook: coordinator.skipped_for_replay_lane

**Severity:** INFO
**Owner:** on-call SRE
**SLA:** 30 minutes to acknowledge, 60 minutes to investigate if unexpected

## Symptom

The orchestrator service skipped the live coordinator run because the session was routed into the replay lane (`osa_coordinator_replay_enabled=True`). The coordinator's understanding and plan-of-work were served from the replay cache rather than a live LLM call.

Audit log action: `coordinator.skipped_for_replay_lane`

Prometheus query:
```
increase(osa_domain_agent_dispatch_total{result="replay_lane_skip"}[10m]) > 0
```

Dashboard: `OSA / Coordinator` panel "Replay Lane Events".

## Likely causes

- Expected: `osa_coordinator_replay_enabled=True` in environment — replay lane is intentionally active.
- Unexpected: flag enabled in production when live coordinator was expected; check [[flag-tuple-replacement-table]] for T3/T4 requirements.
- Coordinator replay drifted — `coordinator.replay_drift_detected` may have fired before this skip (Jaccard similarity < 0.6 threshold).
- LLM provider unreachable — service fell back to replay lane (`coordinator.run_failed_replay_lane` may also be present).

## Triage steps

1. Confirm event in audit_logs:
   ```sql
   SELECT target_id, details_json, created_at
   FROM audit_logs
   WHERE action = 'coordinator.skipped_for_replay_lane'
   ORDER BY created_at DESC LIMIT 20;
   ```
2. Check if `coordinator.run_failed_replay_lane` preceded the skip (LLM failure fallback):
   ```sql
   SELECT * FROM audit_logs
   WHERE action IN ('coordinator.skipped_for_replay_lane', 'coordinator.run_failed_replay_lane')
     AND target_id = '<session_id>'
   ORDER BY created_at;
   ```
3. Verify `osa_coordinator_replay_enabled` flag state:
   ```
   GET /api/v1/feature-flags
   ```
4. Check for `coordinator.replay_drift_detected` event indicating stale replay data.
5. If unexpected skip and LLM is reachable: verify `OSA_COORDINATOR_REPLAY_ENABLED` env var is not accidentally set to `true`.

## Mitigation

- If replay is intentional: no action required.
- If LLM failure caused the skip: check LLM provider health and see [[credential-revoked]].
- If replay drift detected: flush replay cache and force a live coordinator run by temporarily setting `OSA_COORDINATOR_REPLAY_ENABLED=false`.

## Rollback

- Set `OSA_COORDINATOR_REPLAY_ENABLED=false` in `.env` and restart to force live coordinator.

## Related runbooks

- [[coordinator-iteration-cap]]
- [[cost-budget-exceeded]]
- [[credential-revoked]]
