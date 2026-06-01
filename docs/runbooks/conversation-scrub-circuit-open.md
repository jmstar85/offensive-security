# Runbook: conversation.scrub_circuit_open

**Severity:** PAGE
**Owner:** on-call SRE
**SLA:** 5 minutes to acknowledge, 10 minutes to mitigate

## Symptom

The L4 token-bucket circuit breaker in `ConversationScrubber` opened because the scrubber hit volume exceeded `l4_bucket_capacity=50` tokens within the refill window (`l4_refill_per_sec=5.0`). When the circuit is open, subsequent scrub operations may pass through with reduced redaction coverage.

Prometheus query:
```
increase(osa_conversation_scrubber_circuit_open_total[2m]) > 0
```

Dashboard: `OSA / Safety` panel "Scrubber Circuit Open" — alert fires at any non-zero increment.

Audit log action: `conversation.scrub_circuit_open`

## Likely causes

- Attacker flooding the conversation with high-entropy strings or API keys to exhaust the scrubber bucket.
- LLM producing large volumes of tool output with credentials embedded (check [[conversation-scrubbed]] for L1/L2 spike).
- Session with very large tool outputs (e.g. port scan returning thousands of lines with tokens).
- Bug in tool output formatting that serializes credentials into every turn.

## Triage steps

1. Confirm circuit open event:
   ```
   increase(osa_conversation_scrubber_circuit_open_total[5m])
   ```
2. Identify affected session:
   ```sql
   SELECT target_id, details_json, created_at
   FROM audit_logs
   WHERE action = 'conversation.scrub_circuit_open'
   ORDER BY created_at DESC LIMIT 10;
   ```
3. Cross-reference with scrubber hit spike:
   ```
   rate(osa_conversation_scrubber_hits_total[1m])
   ```
4. Check if canary was also leaked (highest severity):
   ```sql
   SELECT * FROM audit_logs
   WHERE action = 'conversation.canary_leak'
     AND target_id = '<session_id>'
   ORDER BY created_at DESC;
   ```
   If yes — see [[conversation-canary-leak]] immediately.
5. Review session's recent tool calls to identify the flooding source.

## Mitigation

- Immediate: Pause and quarantine the affected session.
- If adversarial input suspected: terminate session, alert security team.
- Raise `l4_bucket_capacity` (default 50) if legitimate high-volume tool output is causing false trips — do this only after confirming no canary leak.
- Check and fix any tool that is serializing credentials into output turns.

## Rollback

- Stop the affected session (`DELETE /api/v1/pentest-sessions/{id}`).
- Circuit resets automatically on the next `ConversationScrubber` instantiation (per-session object).

## Related runbooks

- [[conversation-scrubbed]]
- [[conversation-canary-leak]]
- [[raw-conversation-subscribed]]
