# Runbook: conversation.canary_leak

**Severity:** CRITICAL PAGE
**Owner:** on-call SRE + Security Lead
**SLA:** 2 minutes to acknowledge, 5 minutes to quarantine session

## Symptom

The L3 canary check in `ConversationScrubber` detected that the session-specific canary token (derived via `SHA-256(session_id.bytes + b"canary-v1")[:16]`) appeared in a conversation turn. This is a strong signal of prompt injection or memory exfiltration.

Prometheus query:
```
increase(osa_conversation_scrubber_hits_total{layer="l3"}[1m]) > 0
```

Dashboard: `OSA / Safety` panel "Scrubber L3 Canary Hits" — zero-tolerance alert.

Audit log action: `conversation.canary_leak`

## Likely causes

- Prompt injection: attacker-controlled content in tool output embedded the canary and caused it to be echoed back in a subsequent LLM turn.
- Memory exfiltration: a malicious payload caused the model to recall and repeat a system-context string containing the canary.
- Internal bug: canary accidentally included in a tool's output template (rare, check recent deployments).

## Triage steps

1. Immediately identify the session:
   ```sql
   SELECT target_id, details_json, created_at
   FROM audit_logs
   WHERE action = 'conversation.canary_leak'
   ORDER BY created_at DESC LIMIT 5;
   ```
2. Pause the session: `PATCH /api/v1/pentest-sessions/{id}` with `{"status": "paused"}`.
3. Examine the full conversation turn that triggered L3:
   - Pull `raw_conversation` topic events for the session (requires admin or team_admin role — see [[raw-conversation-subscribed]]).
   - Identify the tool call that introduced canary-containing content.
4. Check for circuit breaker correlation:
   ```
   increase(osa_conversation_scrubber_circuit_open_total{session_id="<id>"}[5m])
   ```
5. Check whether the `[REDACTED:canary_leak]` substitution appeared in the `conversation` (scrubbed) topic output — if yes, scrubber worked correctly. If no, escalate severity.
6. Review recent tool invocations for the session in `audit_logs` ordered by time.

## Mitigation

- Immediate: Terminate the session (`DELETE /api/v1/pentest-sessions/{id}`).
- Notify security lead — this is a potential data exfiltration event.
- Rotate the `CREDENTIAL_FERNET_KEY` if any production credentials were in context.
- Review all tool outputs from the session for injected payloads.
- File incident report.

## Rollback

- No rollback for the canary detection mechanism itself.
- If false positive (rare): verify canary derivation `SHA-256(session_id.bytes + b"canary-v1")[:16]` matches the token in the turn.

## Related runbooks

- [[conversation-scrubbed]]
- [[conversation-scrub-circuit-open]]
- [[raw-conversation-subscribed]]
- [[infra-network-membership-violation]]
