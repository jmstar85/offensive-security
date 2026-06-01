# STRIDE Deep Dive — Surface 5 + 6: Conversation Scrubber + raw_conversation Gate

> **Surface:** 4-layer conversation scrubber + canary HMAC + `raw_conversation` TEAM_ADMIN gate
> **Threat model version:** 2.0
> **Wave coverage:** W4 (PR4.4)
> **Related surfaces:** Surface 4 (credential vault, Layer 1 integration)
> **Last updated:** 2026-06-01

---

## Overview

The conversation scrubber is a 4-layer pipeline applied to all LLM conversation content before
it is stored or returned to operators:

- **Layer 1:** Regex-based pattern matching (API keys, secrets, known PII formats)
- **Layer 2:** NER-based entity recognition (names, emails, addresses, phone numbers)
- **Layer 3:** Unicode/encoding normalisation (prevents bypass via homoglyphs, encodings)
- **Layer 4:** Canary HMAC verification (detects post-scrub tampering)

The `raw_conversation` WebSocket channel bypasses the scrubber and is restricted to sessions where
`accept_raw=true` is set and the operator holds the `TEAM_ADMIN` JWT role. Unauthorised access
results in WebSocket close code 4003.

---

## Spoofing

### Threat S-1: Prompt injection disguised as scrubber passthrough
- **Scenario:** Attacker crafts an LLM prompt that contains a PII/credential pattern encoded to
  evade Layer 1 and Layer 2, causing the scrubber to treat it as safe content.
- **Likelihood:** High — encoding bypasses are well-documented for regex and NER systems.
- **Impact:** High — credential or PII leaks into operator-visible output.
- **Existing v2.0 mitigation:** Layer 3 canonicalises all input (Unicode normalisation form NFKC +
  punycode decoding + percent-decoding) before Layer 1 and Layer 2 run; canary HMAC signs
  scrubber output so any post-canonicalisation injection is detected.
  Proved by: `backend/tests/safety/test_adversarial_prompts.py` — encoding bypass adversarial corpus.
- **Residual risk:** Medium. Zero-day encoding bypasses not in current corpus. Quarterly corpus
  refresh is the control.
- **Owner:** ML team

### Threat S-2: Forged `accept_raw=true` claim to access raw_conversation
- **Scenario:** Operator crafts a JWT with a manually set `accept_raw=true` claim, bypassing the
  TEAM_ADMIN gate and accessing unredacted conversation data.
- **Likelihood:** Low — JWT is signed by server-side secret.
- **Impact:** Critical — full unredacted conversation access.
- **Existing v2.0 mitigation:** `accept_raw` flag only settable by TEAM_ADMIN JWT claim (server-side);
  flag re-verified on every WebSocket frame, not just at connection establishment; WS close 4003
  on any frame where claim is invalid or missing; JWT signing key rotated quarterly.
  Proved by: E2E test suite — `test_raw_conversation_unauthorized` (W4/PR4.4).
- **Residual risk:** Low.
- **Owner:** Security team

---

## Tampering

### Threat T-1: Adversarial payload mutates scrubbed output before storage
- **Scenario:** After the scrubber completes, a malicious component in the pipeline (or a
  compromised storage layer) modifies the scrubbed conversation before it is written to the DB.
- **Likelihood:** Low — requires compromise of an internal service.
- **Impact:** High — tampered conversation stored as authentic; forensic integrity lost.
- **Existing v2.0 mitigation:** Canary HMAC signed on scrubber output at completion; storage layer
  re-verifies HMAC before write; HMAC mismatch triggers P1 alert, session abort, and rollback.
  Any deviation from the signed content is detectable.
- **Residual risk:** Low. Requires compromise of HMAC key, which is stored in KMS.
- **Owner:** Backend team

### Threat T-2: Scrubber layer bypassed via Unicode/encoding tricks
- **Scenario:** Attacker uses homoglyph substitution, bidirectional override characters, or
  percent-encoding to smuggle PII/credentials through Layer 1 and Layer 2.
- **Likelihood:** High without Layer 3.
- **Impact:** High — PII/credential leak in stored conversation.
- **Existing v2.0 mitigation:** Layer 3 performs NFKC normalisation + bidirectional character
  stripping + percent-decode + punycode decode before Layers 1 and 2; normalised form stored
  (original not retained after normalisation).
  Proved by: `backend/tests/safety/test_adversarial_prompts.py` — encoding bypass tests.
- **Residual risk:** Low-Medium. Novel encoding techniques not yet in Layer 3 may bypass.
- **Owner:** ML team

---

## Repudiation

### Threat R-1: Scrubber decision not audited
- **Scenario:** The scrubber redacts content but emits no audit record of what was redacted,
  the rule that triggered, or the session context. Post-incident investigation is impossible.
- **Likelihood:** N/A (design requirement).
- **Impact:** High — no forensic capability for PII incidents.
- **Existing v2.0 mitigation:** Per-layer redaction events logged with rule ID, span offsets,
  session reference, layer number, and UTC timestamp. Logs written to immutable sink.
  Per-family scrubber layer metrics exposed in FlowConsole (TEAM_ADMIN).
  Proved by: `backend/tests/observability/` — scrubber metrics tests (PR4.4).
- **Residual risk:** Low.
- **Owner:** Platform team

### Threat R-2: TEAM_ADMIN raw_conversation access not audited
- **Scenario:** A TEAM_ADMIN operator accesses unredacted conversations without any record, enabling
  insider threat or covert data collection.
- **Likelihood:** Medium — insider threat is a realistic risk for privileged users.
- **Impact:** High — undetectable data exfiltration.
- **Existing v2.0 mitigation:** Channel open and close + every frame access emits audit event with
  TEAM_ADMIN `user_id`, session reference, frame count, and UTC timestamp. Anomalous access
  patterns trigger UEBA alert.
- **Residual risk:** Medium. UEBA rule tuning required to avoid alert fatigue.
- **Owner:** Security team

---

## Information Disclosure

### Threat I-1: PII or credentials leak in scrubbed conversation output
- **Scenario:** A PII or credential pattern not covered by the scrubber's current regex/NER model
  passes through all 4 layers and is stored and returned to operators.
- **Likelihood:** Medium — no scrubber achieves 100% coverage.
- **Impact:** High — PII exposure; GDPR/compliance breach.
- **Existing v2.0 mitigation:** 4-layer pipeline (regex → NER → normalisation → canary);
  FPR < 1% target per GA checklist; adversarial corpus tested on every merge; quarterly corpus
  refresh scheduled.
  Proved by: `backend/tests/safety/test_adversarial_prompts.py` — 100% catch assertion on corpus.
- **Residual risk:** Medium. True zero FPR is not achievable; novel PII formats will exist.
- **Owner:** ML team

### Threat I-2: raw_conversation accessible to non-TEAM_ADMIN operators
- **Scenario:** A bug in the WebSocket middleware allows a non-TEAM_ADMIN operator to receive
  raw (unredacted) conversation frames.
- **Likelihood:** Low — WebSocket middleware is well-tested.
- **Impact:** Critical — full unredacted conversation access for all operators.
- **Existing v2.0 mitigation:** WebSocket close 4003 on missing or invalid TEAM_ADMIN role;
  role check performed in middleware before session handshake; frame-level check re-validates
  on each message; regression test in E2E suite.
  Proved by: `backend/tests/e2e/test_attack_matrix.py` — raw_conversation access control tests.
- **Residual risk:** Low.
- **Owner:** Security team

---

## Denial of Service

### Threat D-1: NER model inference overwhelms scrubber under high concurrency
- **Scenario:** High request volume causes the NER model (Layer 2) to queue up, increasing
  latency and eventually timing out or crashing under load.
- **Likelihood:** Medium — NER inference is CPU-intensive.
- **Impact:** Medium — operator sessions see increased latency or scrubber timeouts.
- **Existing v2.0 mitigation:** Scrubber runs in bounded thread pool (size = 2 × CPU cores);
  request queue size-limited (default 100); timeout (5 s) aborts with safe fallback (full redaction
  of pending content); load shedding returns 503 before queue is exhausted.
- **Residual risk:** Low-Medium. NER model upgrade may change inference latency characteristics;
  load testing required after each model update.
- **Owner:** ML team

### Threat D-2: Canary HMAC computation adds unacceptable latency
- **Scenario:** HMAC computation over large conversation payloads becomes a bottleneck,
  increasing scrubber latency to unacceptable levels.
- **Likelihood:** Low — HMAC-SHA256 is fast.
- **Impact:** Low — operational only.
- **Existing v2.0 mitigation:** HMAC computed over scrubbed output only (not raw input); streaming
  HMAC implementation avoids loading entire payload into memory; p99 latency target < 50 ms.
- **Residual risk:** Low.
- **Owner:** Backend team

---

## Elevation of Privilege

### Threat E-1: Operator promotes self to TEAM_ADMIN via crafted JWT
- **Scenario:** Operator modifies their JWT payload to include `"role": "TEAM_ADMIN"` and
  `"accept_raw": true`, attempting to gain access to raw_conversation.
- **Likelihood:** Low — JWT is signed; modification would break signature.
- **Impact:** Critical — access to all raw conversations.
- **Existing v2.0 mitigation:** JWT signed by server-side HMAC-SHA256 secret; TEAM_ADMIN claim
  cannot be self-issued; signature verification on every request; JWT secret rotated quarterly
  and stored in KMS.
- **Residual risk:** Low. Requires compromise of JWT signing key.
- **Owner:** Security team

---

## Residual Risk Summary

| ID | Category | Residual Risk | Owner | Monitoring |
|----|----------|---------------|-------|------------|
| RR-S1 | Info Disclosure | Novel PII format bypasses all 4 scrubber layers | ML team | Quarterly adversarial corpus refresh; FPR metric |
| RR-S2 | Spoofing | Zero-day encoding bypass not in Layer 3 normaliser | ML team | Quarterly corpus refresh; `scrubber.layer3.bypass_attempt` alert |
| RR-S3 | Repudiation | UEBA alert fatigue causes TEAM_ADMIN access alerts to be ignored | Security team | Quarterly UEBA rule review; alert suppression audit |
| RR-S4 | DoS | NER latency regression after model upgrade | ML team | Load test required after each NER model update |
