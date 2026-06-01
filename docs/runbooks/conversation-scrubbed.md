# Runbook: conversation.scrubbed

**Severity:** WARN
**Owner:** on-call SRE
**SLA:** 15 minutes to acknowledge, 30 minutes to mitigate

## Symptom

The `ConversationScrubber` in `app/safety/conversation_scrubber.py` matched one or more scrub patterns (L1 regex, L2 Shannon entropy, or L3 canary) against a conversation turn. Sensitive material was redacted before the turn was published to the `conversation` topic.

Prometheus query:
```
increase(osa_conversation_scrubber_hits_total[5m]) > 0
```

Dashboard: `OSA / Safety` panel "Scrubber Hits by Layer".

Audit log action: `conversation.scrubbed`

## Likely causes

- L1 hit: API key, JWT, Bearer token, private key block, or password appeared in LLM response or tool output.
- L2 hit: High-entropy string (>= 4.5 bits/char, >= 20 chars) present in conversation turn — often base64-encoded credentials or session tokens.
- L3 hit: Session canary token appeared in conversation output (indicates possible prompt injection — see [[conversation-canary-leak]]).
- Normal operation: scrubber working as designed. High rate may indicate a systematic credential leak.

## Triage steps

1. Check scrubber hit rate by layer:
   ```
   rate(osa_conversation_scrubber_hits_total{layer="l1"}[5m])
   rate(osa_conversation_scrubber_hits_total{layer="l2"}[5m])
   rate(osa_conversation_scrubber_hits_total{layer="l3"}[5m])
   ```
2. If L3 hits > 0, immediately escalate — see [[conversation-canary-leak]].
3. Check if circuit breaker opened:
   ```
   increase(osa_conversation_scrubber_circuit_open_total[5m]) > 0
   ```
   If so, see [[conversation-scrub-circuit-open]].
4. Identify affected session via audit_logs:
   ```sql
   SELECT target_id, details_json, created_at
   FROM audit_logs
   WHERE action = 'conversation.scrubbed'
   ORDER BY created_at DESC LIMIT 30;
   ```
5. Review which tool output or role turn triggered the L1/L2 match (check `details_json.layer` and `details_json.pattern`).

## Mitigation

- L1/L2 scrubbed: review tool output pipeline to prevent credentials entering conversation turns.
- Ensure tools strip credentials from their stdout before returning to the orchestrator.
- If L1 rate high: check that `CREDENTIAL_FERNET_KEY` is set and credentials are not logged in plaintext.

## Rollback

- Scrubber cannot be disabled in production; it is a safety invariant.
- Adjust `l2_entropy_threshold` (default 4.5) via ConversationScrubber constructor if legitimate tokens are being redacted.

## Related runbooks

- [[conversation-canary-leak]]
- [[conversation-scrub-circuit-open]]
- [[raw-conversation-subscribed]]
