# Runbook: headless_exec.shim_block

**Severity:** WARN
**Owner:** on-call SRE
**SLA:** 15 minutes to acknowledge, 30 minutes to mitigate

## Symptom

The headless browser shim blocked an agent tool call because the slug or arguments did not pass the headless allowlist check.

Prometheus query:
```
increase(osa_kali_shim_block_total{reason=~"headless.*"}[5m]) > 0
```

Dashboard: `OSA / Safety` panel "Shim Block Events", filtered to `headless` reason.

Audit log action: `headless_exec.shim_block`

## Likely causes

- `osa_headless_browser_enabled=True` but `osa_multi_provider_llm=False` (prerequisite not met — see [[flag-tuple-replacement-table]]).
- Tool slug not in headless allowlist.
- Target URL not in scope per session's `passive_egress_allowlist`.
- Headless agent called with disallowed browser flag (e.g. `--no-sandbox` outside test env).

## Triage steps

1. Query audit_logs:
   ```sql
   SELECT actor_id, details_json, created_at
   FROM audit_logs
   WHERE action = 'headless_exec.shim_block'
   ORDER BY created_at DESC LIMIT 20;
   ```
2. Inspect `details_json.tool_slug`, `details_json.reason`, and `details_json.args`.
3. Verify flag prerequisites:
   ```
   GET /api/v1/feature-flags
   ```
   Confirm `osa_headless_browser_enabled=true` AND `osa_multi_provider_llm=true`.
4. Check if the target URL appears in `passive_egress_allowlist` in `app/core/config.py`.
5. If the block reason is `unsupported_flag_topology`, see [[unsupported-flag-topology]].

## Mitigation

- Immediate: If legitimate tool call, verify flag prerequisites are met (T3 or T4 tuple required).
- Add target to `PASSIVE_EGRESS_ALLOWLIST` if scope is valid.
- If headless not needed: set `OSA_HEADLESS_BROWSER_ENABLED=false` in `.env` and restart.

## Rollback

- Set `OSA_HEADLESS_BROWSER_ENABLED=false` in `.env` and restart service.
- No DB migration required.

## Related runbooks

- [[mitm-shim-block]]
- [[unsupported-flag-topology]]
- [[flag-tuple-replacement-table]]
