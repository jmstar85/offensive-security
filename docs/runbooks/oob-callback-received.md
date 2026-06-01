# Runbook: oob_callback.received

**Severity:** INFO
**Owner:** on-call SRE
**SLA:** 30 minutes to acknowledge, 60 minutes to review

## Symptom

An out-of-band (OOB) callback was received by the interactsh sidecar and correlated to an active pentest session. This is typically expected during SSRF/blind injection testing, but unmatched callbacks may indicate scope drift.

Prometheus query:
```
increase(osa_domain_agent_dispatch_total{domain="interactsh",result="oob_callback"}[15m]) > 0
```

Dashboard: `OSA / Recon` panel "OOB Callbacks".

Finding type: `oob_callback` (emitted by `app/agents/parsers/interactsh.py`).

## Likely causes

- Expected: AttackAgent triggered an SSRF/XXE/blind-injection payload and the target phoned home.
- Unexpected/scope violation: callback from a host not in the session's authorised target list.
- Stale callback: DNS TTL-delayed callback arriving after session closed.
- Misconfigured interactsh server receiving callbacks from unrelated infrastructure.

## Triage steps

1. Query findings for the session:
   ```sql
   SELECT session_id, details_json, created_at
   FROM findings
   WHERE details_json->>'type' = 'oob_callback'
   ORDER BY created_at DESC LIMIT 20;
   ```
2. Extract `correlation_id` from `details_json` and match to the sending request in session logs.
3. Verify the originating IP/domain is within authorised scope:
   ```sql
   SELECT scope_json FROM pentest_sessions WHERE id = '<session_id>';
   ```
4. Check if the callback arrived after the session was closed (stale callback pattern).
5. If scope violation: immediately escalate to security team.

## Mitigation

- If in-scope: no action required; callback is expected evidence.
- If out-of-scope callback: pause session, notify team, review what payload triggered it.
- Stale callback: log and dismiss; verify interactsh cleanup ran post-session.

## Rollback

- N/A for legitimate callbacks.
- If interactsh misconfiguration: redeploy with correct `INTERACTSH_SERVER` env var.

## Related runbooks

- [[mitm-shim-block]]
- [[infra-network-membership-violation]]
