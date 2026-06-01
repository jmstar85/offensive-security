# Runbook: raw_conversation.subscribed

**Severity:** WARN
**Owner:** on-call SRE
**SLA:** 15 minutes to acknowledge, 20 minutes to review

## Symptom

A user subscribed to the `raw_conversation` WebSocket topic, which streams unscrubbed role turns including any tool output before the `ConversationScrubber` runs. This topic is gated by `verify_raw_conversation_access` in `app/api/v1/coordinator.py` (SF-CRITIC-9).

Prometheus query:
```
increase(osa_domain_agent_dispatch_total{domain="ws",result="raw_conversation_subscribed"}[10m]) > 0
```

Dashboard: `OSA / WebSocket` panel "Raw Conversation Subscribers".

Audit log action: `raw_conversation.subscribed`

## Likely causes

- Authorized team_admin or admin user subscribed for legitimate debugging.
- Unauthorized access attempt by a regular member user (should be blocked by access control gate).
- Automated tool (CI, integration test) subscribing without proper role headers.
- Bug in access control gate allowing non-admin subscription.

## Triage steps

1. Query audit_logs for all recent raw_conversation subscriptions:
   ```sql
   SELECT actor_id, ip_address, details_json, created_at
   FROM audit_logs
   WHERE action = 'raw_conversation.subscribed'
   ORDER BY created_at DESC LIMIT 20;
   ```
2. Verify the subscriber's role:
   ```sql
   SELECT email, role FROM users WHERE id = '<actor_id>';
   ```
   Only `ADMIN` and `TEAM_ADMIN` roles are permitted.
3. If the subscriber has `MEMBER` role and subscription succeeded — this is a P0 access control bug; page security team immediately.
4. Verify `verify_raw_conversation_access` is enforced at `app/api/v1/coordinator.py:74`.
5. Check if `accept_raw=True` was passed in the WebSocket handshake headers.

## Mitigation

- If unauthorized subscriber: revoke the user's session tokens, audit their activity.
- If access control bug confirmed: emergency patch to `verify_raw_conversation_access`, restart service.
- If legitimate: no action required; log for compliance.

## Rollback

- No rollback for legitimate subscriptions.
- If bug: revert the commit that broke the gate and hot-patch.

## Related runbooks

- [[conversation-canary-leak]]
- [[conversation-scrubbed]]
- [[admin-enrich-understanding]]
