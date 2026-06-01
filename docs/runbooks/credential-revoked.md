# Runbook: credential.revoked

**Severity:** WARN
**Owner:** on-call SRE
**SLA:** 10 minutes to acknowledge, 20 minutes to mitigate

## Symptom

An LLM provider credential was explicitly revoked via the API or admin UI, making the associated user's sessions unable to call LLM APIs until a new credential is provisioned.

Prometheus query:
```
increase(osa_domain_agent_dispatch_total{result="credential_missing"}[5m]) > 0
```

Dashboard: `OSA / Credentials` panel "Revocation Events".

Audit log action: `credential.revoked`

## Likely causes

- Admin manually revoked a credential (security rotation, suspected compromise).
- OAuth token expired and revocation was triggered by the provider (scope drift — see `credential.scope_drift`).
- User deleted their account, triggering cascade revocation.
- Automated credential rotation script ran and issued a new credential without updating the session.

## Triage steps

1. Confirm revocation in audit_logs:
   ```sql
   SELECT actor_id, target_id, details_json, created_at
   FROM audit_logs
   WHERE action = 'credential.revoked'
   ORDER BY created_at DESC LIMIT 20;
   ```
2. Check if there is a subsequent `credential.created` entry for the same user:
   ```sql
   SELECT * FROM audit_logs
   WHERE action IN ('credential.revoked', 'credential.created')
     AND actor_id = '<user_id>'
   ORDER BY created_at DESC LIMIT 10;
   ```
3. Verify `osa_multi_provider_llm=True` — if False, credential revocation has no effect on routing.
4. Check for `credential.scope_drift` events preceding the revocation.
5. Identify any active sessions belonging to the affected user:
   ```sql
   SELECT id, status FROM pentest_sessions WHERE owner_id = '<user_id>' AND status = 'active';
   ```

## Mitigation

- Immediate: Provision a new credential via `POST /api/v1/credentials` with a valid API key.
- Pause active sessions until the new credential is confirmed working.
- If rotation-triggered: verify `CREDENTIAL_FERNET_KEY` is set correctly in `.env`.

## Rollback

- Credentials cannot be un-revoked; issue a new credential.
- If erroneous revocation: re-create the credential and re-activate affected sessions.

## Related runbooks

- [[cost-budget-exceeded]]
- [[admin-enrich-understanding]]
