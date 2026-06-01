# Runbook: unsupported_flag_topology

**Severity:** PAGE
**Owner:** on-call SRE
**SLA:** 5 minutes to acknowledge, 10 minutes to remediate

## Symptom

`validate_flag_topology` in `app/core/feature_flag_validator.py` raised `UnsupportedFlagTopology` because the active flag combination does not match any of the supported tuples T1–T4. This check only raises in `environment=production`.

Prometheus query:
```
increase(osa_domain_agent_dispatch_total{result="topology_error"}[2m]) > 0
```

Dashboard: `OSA / Feature Flags` panel "Topology Violations".

Audit log action: `unsupported_flag_topology`

## Likely causes

- A flag was toggled independently without satisfying prerequisites (see [[flag-tuple-replacement-table]]).
- Partial deployment: new env vars applied without completing the T1→T2→T3→T4 transition order.
- Infrastructure-as-code drift: Terraform/Helm values out of sync with the supported tuple set.
- Accidental `osa_traffic_via_mitm=True` without `osa_mitm_proxy_enabled=True` (prerequisite violation).

## Triage steps

1. Identify which flags are currently ON:
   ```
   GET /api/v1/feature-flags
   ```
2. Compare against supported tuples from `app/core/feature_flag_validator.py`:
   - T1: all 7 flags False
   - T2: `osa_multi_provider_llm=True` only
   - T3: `osa_multi_provider_llm`, `osa_coordinator_enabled`, `osa_xbow_families_enabled` = True; rest False
   - T4: all 7 flags True
3. Identify which flag violates the prerequisite matrix — see [[flag-tuple-replacement-table]].
4. Check recent deployment logs for which env var changed last.
5. Confirm `environment=production` is set — topology check is a no-op in `dev`/`staging`.

## Mitigation

- Immediate: Set environment variables to match the closest valid tuple (use "closest supported tuple" from the error message).
- Follow transition order: T1→T2→T3→T4 with rollout percentages 10%/50%/100%.
- Restart the backend service after correcting env vars.
- Never skip tuples (e.g. T1→T4 directly) — see [[flag-tuple-replacement-table]] Tuple transitions section.

## Rollback

- Revert to the previous tuple (e.g. T3→T2) by unsetting the flags that were added.
- Reverse rollback ordering: T4→T3→T2→T1, each within 10-minute SLA.

## Related runbooks

- [[flag-tuple-replacement-table]]
- [[coordinator-iteration-cap]]
- [[mitm-shim-block]]
- [[headless-shim-block]]
