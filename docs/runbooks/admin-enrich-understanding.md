# Runbook: coordinator.understanding_enriched

**Severity:** INFO
**Owner:** on-call SRE
**SLA:** 30 minutes to acknowledge (audit review only)

## Symptom

An admin or team_admin used the `POST /api/v1/coordinator/{session_id}/enrich-understanding` endpoint to manually inject additional context into the coordinator's understanding for a session. This is audited via `coordinator.understanding_enriched`.

Audit log action: `coordinator.understanding_enriched`

Prometheus query:
```
increase(osa_domain_agent_dispatch_total{domain="coordinator",result="understanding_enriched"}[60m]) > 0
```

Dashboard: `OSA / Coordinator` panel "Admin Enrichments".

## Likely causes

- Expected: operator enriching scope during an active pentest session (adding targets, clarifying objectives).
- Unexpected high frequency: could indicate automated or scripted enrichment bypassing normal workflow.
- Enrichment by non-admin user: access control violation (only `ADMIN`/`TEAM_ADMIN` may call this endpoint).

## Triage steps

1. Review recent enrichment events:
   ```sql
   SELECT actor_id, target_id, details_json, created_at
   FROM audit_logs
   WHERE action = 'coordinator.understanding_enriched'
   ORDER BY created_at DESC LIMIT 20;
   ```
2. Verify the actor's role:
   ```sql
   SELECT email, role FROM users WHERE id = '<actor_id>';
   ```
3. Inspect `details_json` for the enrichment content — check for prompt injection patterns.
4. If the enrichment came from an unexpected actor or contains suspicious content, pause the session.
5. For high-frequency enrichment: check if a bot/script is calling this endpoint in a loop.

## Mitigation

- If legitimate enrichment: no action required.
- If prompt injection in enrichment payload: pause session, rotate session canary, see [[conversation-canary-leak]].
- If unauthorized caller: revoke user session, patch access control if role check failed.
- Rate-limit the endpoint if automated abuse detected.

## Rollback

- Enrichment cannot be un-applied to an in-progress coordinator run.
- Terminate and re-create the session to start fresh without the enrichment.

## Related runbooks

- [[conversation-canary-leak]]
- [[raw-conversation-subscribed]]
- [[coordinator-skipped-for-replay-lane]]
- [[credential-revoked]]
