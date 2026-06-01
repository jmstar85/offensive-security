# Runbook: cost.budget_exceeded

**Severity:** PAGE
**Owner:** on-call SRE
**SLA:** 5 minutes to acknowledge, 15 minutes to mitigate

## Symptom

Budget guard layer-A or layer-B blocked a task spawn due to daily USD limit exhaustion.

Prometheus query:
```
increase(osa_budget_guard_layer_a_block_total[5m]) > 0
increase(osa_budget_guard_layer_b_block_total[5m]) > 0
```

Dashboard: `OSA / Budget & Cost` panel "Budget Guard Blocks".

## Likely causes

- Daily team pool budget (`workflow_daily_usd_budget_default`) set too low for current load.
- Runaway session consuming tokens without an iteration cap (check `coordinator.iteration_cap_hit` events).
- Estimator drift: `osa_budget_guard_estimator_drift{provider}` > 1.5 means actual cost is running higher than pre-spawn estimates.
- Misconfigured team pool budget — `workflow_team_pool_budget_enabled=True` but team budget row missing from DB.

## Triage steps

1. Confirm scope — query `audit_logs` for budget blocks in last 24h:
   ```sql
   SELECT actor_id, details_json, created_at
   FROM audit_logs
   WHERE action IN ('budget.layer_a_block', 'budget.layer_b_block')
   ORDER BY created_at DESC LIMIT 50;
   ```
2. Check estimator drift gauge:
   ```
   osa_budget_guard_estimator_drift{provider="anthropic"}
   ```
   Ratio > 1.5 = estimates are significantly under-counting real cost.
3. Identify the heaviest session:
   ```
   topk(5, osa_llm_cost_usd_total)
   ```
4. Check if `coordinator.iteration_cap_hit` fired for the same session — see [[coordinator-iteration-cap]].
5. Verify `workflow_daily_usd_budget_default` in `app/core/config.py` matches the environment's `.env`.

## Mitigation

- Immediate: Terminate the runaway session via `DELETE /api/v1/pentest-sessions/{id}` (admin token required).
- Raise daily budget temporarily: set `WORKFLOW_DAILY_USD_BUDGET_DEFAULT=<new_value>` in environment and restart service.
- Follow-up: Adjust estimator calibration if drift > 1.5 sustained over 1h.

## Rollback

- Revert budget env var to previous value and restart service.
- No DB migration needed — budget is a settings-layer concern.

## Related runbooks

- [[coordinator-iteration-cap]]
- [[credential-revoked]]
