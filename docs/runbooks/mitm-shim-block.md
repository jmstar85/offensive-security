# Runbook: mitm_exec.shim_block

**Severity:** WARN
**Owner:** on-call SRE
**SLA:** 15 minutes to acknowledge, 30 minutes to mitigate

## Symptom

The MITM allowlist shim blocked an AttackAgent tool call because the tool slug or arguments failed the `mitm_exec_allowlist` check in `app/safety/mitm_allowlist.py`.

Prometheus query:
```
increase(osa_kali_shim_block_total[5m]) > 0
```

Dashboard: `OSA / Safety` panel "Shim Block Events".

Audit log action: `mitm_exec.shim_block`

## Likely causes

- Tool slug not in `ALLOWED_TOOLS` list in `app/safety/mitm_allowlist.py`.
- Arguments contain a disallowed pattern (e.g. target not in scope, unsafe flag).
- `osa_traffic_via_mitm=True` but target host not whitelisted in `passive_egress_allowlist`.
- New tool added to agent families without updating the MITM allowlist.

## Triage steps

1. Query audit_logs for blocked tool calls:
   ```sql
   SELECT actor_id, details_json, created_at
   FROM audit_logs
   WHERE action = 'mitm_exec.shim_block'
   ORDER BY created_at DESC LIMIT 30;
   ```
2. Inspect `details_json.tool_slug` and `details_json.reason` fields.
3. Cross-check the tool slug against `app/safety/mitm_allowlist.py:ALLOWED_TOOLS`.
4. Check if `osa_traffic_via_mitm` flag is enabled:
   ```
   GET /api/v1/feature-flags
   ```
5. Verify flag topology is T3 or T4 per [[flag-tuple-replacement-table]].

## Mitigation

- Immediate: If legitimate tool, add to `ALLOWED_TOOLS` in `app/safety/mitm_allowlist.py` and restart.
- If false positive: review the argument pattern that triggered the block in `details_json.args`.
- If attacker probing: escalate to security team, check for scope violations.

## Rollback

- Revert allowlist changes and restart service.
- Disable `OSA_TRAFFIC_VIA_MITM=false` in `.env` to bypass shim (reduces coverage — document this).

## Related runbooks

- [[headless-shim-block]]
- [[oob-callback-received]]
- [[flag-tuple-replacement-table]]
