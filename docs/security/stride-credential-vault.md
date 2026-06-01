# STRIDE Deep Dive — Surface 4: Credential Vault

> **Surface:** `UserLLMCredential` model + Fernet encryption + KMS-wrapped key + OAuth scope
> **Threat model version:** 2.0
> **Wave coverage:** W0 (baseline), W4 (PR4.4 scrubber integration)
> **Last updated:** 2026-06-01

---

## Overview

The credential vault stores per-user LLM provider API keys encrypted with Fernet symmetric
encryption. The Fernet key itself is wrapped by AWS KMS (or equivalent), ensuring that plaintext
credentials are never stored on disk or in environment variables. Each credential record is scoped
to a `user_id` foreign key, and all access is audited. The vault integrates with the conversation
scrubber to ensure API keys never appear in logs.

---

## Spoofing

### Threat S-1: Attacker creates a `UserLLMCredential` record for another user
- **Scenario:** A low-privilege user manipulates API parameters to create or overwrite a credential
  record belonging to a different `user_id`, injecting a known-bad API key.
- **Likelihood:** Medium — IDOR is a common API vulnerability class.
- **Impact:** High — could cause attack sessions to use attacker-controlled LLM endpoint.
- **Existing v2.0 mitigation:** All `UserLLMCredential` queries filtered by authenticated JWT
  `user_id` claim at ORM layer; `user_id` field not user-writable (set server-side from JWT);
  row-level security policy in DB enforces `user_id = current_user_id()`.
  Proved by: `backend/tests/e2e/test_attack_matrix.py` — IDOR test cases (PR4.5).
- **Residual risk:** Low.
- **Owner:** Backend team

### Threat S-2: KMS impersonation to obtain unwrapped Fernet key
- **Scenario:** Attacker deploys a rogue service that responds to KMS API calls and returns a
  known Fernet key, allowing decryption of all stored credentials.
- **Likelihood:** Very Low — KMS endpoint is pinned; IAM role binding is enforced.
- **Impact:** Critical — full credential exposure for all users.
- **Existing v2.0 mitigation:** KMS access via IAM role bound to backend service account;
  KMS endpoint pinned in config (no env var override without restart); MFA enforced on KMS key
  policy for all administrative operations; KMS endpoint certificate validated.
- **Residual risk:** Low. Requires compromise of the IAM role or KMS service itself.
- **Owner:** Security team

---

## Tampering

### Threat T-1: DB row modified to substitute a different Fernet-encrypted credential
- **Scenario:** Attacker with DB write access (e.g., via SQL injection) overwrites the ciphertext
  field of a `UserLLMCredential` row with a ciphertext encrypted under a known Fernet key.
- **Likelihood:** Low-Medium — SQL injection is a common attack vector.
- **Impact:** High — attacker's API key used for attack sessions.
- **Existing v2.0 mitigation:** Row integrity protected by HMAC computed over `(user_id, provider,
  ciphertext, created_at)`; HMAC mismatch on read triggers credential invalidation + P1 alert;
  all SQL queries use parameterised statements (ORM-enforced); WAF blocks common SQLi patterns.
  Proved by: `backend/tests/e2e/test_attack_matrix.py` — SQLi test cases (PR4.5).
- **Residual risk:** Low-Medium. Second-order SQLi in less-tested paths may not be covered.
  Security code review of all new ORM queries required.
- **Owner:** Backend team

### Threat T-2: Fernet key rotated mid-session to invalidate live credentials
- **Scenario:** A key rotation is initiated while active sessions are using the current key,
  causing decryption failures and session disruption.
- **Likelihood:** Low — rotation is a manual process.
- **Impact:** Medium — operational disruption for active sessions.
- **Existing v2.0 mitigation:** Key rotation follows documented runbook: dual-key window allows
  both old and new keys to be valid during transition (TTL = 1 h); all in-flight decryptions
  attempted with new key first, then old key on failure; rollback procedure tested quarterly.
- **Residual risk:** Low.
- **Owner:** Security team

---

## Repudiation

### Threat R-1: Credential access not audited
- **Scenario:** API keys are read/written without any audit trail, making it impossible to
  determine which sessions used which credentials or detect unauthorised access.
- **Likelihood:** N/A (design requirement).
- **Impact:** High — no forensic capability.
- **Existing v2.0 mitigation:** Every `UserLLMCredential` read and write emits a structured audit
  event: `credential_vault.read` / `credential_vault.write` with `user_id`, `provider`, `session_id`,
  `timestamp`, `source_ip`. Audit events written to immutable log sink.
- **Residual risk:** Low. Immutable sink relies on infrastructure-level tamper resistance.
- **Owner:** Platform team

### Threat R-2: Key rotation not audited
- **Scenario:** A Fernet key rotation occurs without an audit record, making it impossible to
  correlate decryption errors with a rotation event.
- **Likelihood:** Low.
- **Impact:** Medium.
- **Existing v2.0 mitigation:** Key rotation runbook mandates audit event emission before and after
  rotation; rotation event includes old key ID (hash), new key ID (hash), operator user_id, and
  timestamp.
- **Residual risk:** Low.
- **Owner:** Security team

---

## Information Disclosure

### Threat I-1: Plaintext API key logged in application logs
- **Scenario:** An API key appears in a log line (e.g., in a URL parameter, request body dump,
  or exception traceback) and is captured by the logging pipeline.
- **Likelihood:** High without mitigation — a well-documented risk for API-key-based systems.
- **Impact:** Critical — full credential exposure.
- **Existing v2.0 mitigation:** Scrubber Layer 1 (regex) strips `sk-*`, `Bearer `, and equivalent
  patterns from all log sinks before write; structured logging framework (no raw string
  interpolation); API key never logged at DEBUG level; HTTP client configured to mask
  `Authorization` header.
  Proved by: `backend/tests/safety/test_adversarial_prompts.py` — credential redaction corpus.
- **Residual risk:** Medium. Novel API key formats (new providers) may not be covered by regex.
  Adding new providers requires updating scrubber Layer 1 patterns.
- **Owner:** ML team + Security team

### Threat I-2: Fernet key exposed via environment variable leak
- **Scenario:** The Fernet key is stored as an environment variable and leaks via `/proc/self/environ`
  access, debug endpoint, or container inspection.
- **Likelihood:** Medium without mitigation — env var credential storage is a common anti-pattern.
- **Impact:** Critical — full credential vault decryption.
- **Existing v2.0 mitigation:** KMS-wrapped key only; plaintext Fernet key NEVER stored in env vars
  or config files; backend fetches key from KMS at startup and holds it only in process memory;
  memory dump protection via mlock where supported.
- **Residual risk:** Low-Medium. In-memory key is vulnerable to memory dump on a compromised host.
  Mitigated by host-level security (gVisor, SELinux) in production.
- **Owner:** Infra team

---

## Denial of Service

### Threat D-1: KMS unavailability prevents all LLM operations
- **Scenario:** KMS service becomes unavailable (outage or throttling), preventing Fernet key
  retrieval and blocking all credential decryption operations.
- **Likelihood:** Low-Medium — KMS outages are rare but possible.
- **Impact:** High — all LLM-dependent features unavailable.
- **Existing v2.0 mitigation:** KMS response cached per-instance with TTL = 5 min; cache serves
  requests during short outages; on cache miss + KMS error, service returns 503 with `Retry-After`
  header; PagerDuty alert triggered at `kms.error_rate > 0.1%`.
- **Residual risk:** Medium. Outages longer than 5 min degrade all LLM operations. Multi-region
  KMS replication is the recommended long-term mitigation.
- **Owner:** Platform team

---

## Elevation of Privilege

### Threat E-1: Low-privilege user reads another user's credential
- **Scenario:** Attacker with valid authentication but for a different user_id reads credential
  rows belonging to another user via a horizontal privilege escalation.
- **Likelihood:** Low-Medium — IDOR is common in API services.
- **Impact:** High — full API key exposure for another user.
- **Existing v2.0 mitigation:** Row-level security enforced at both ORM layer and DB policy;
  cross-user query returns 403 before DB query is executed; DB policy enforces `user_id = current_user_id()`
  as a second-layer control.
  Proved by: `backend/tests/e2e/test_attack_matrix.py` — IDOR test cases (PR4.5).
- **Residual risk:** Low.
- **Owner:** Backend team

### Threat E-2: Credential vault bypass via DB connection string leak
- **Scenario:** Direct database connection string (bypassing ORM + row-level security) leaks via
  config file, env var, or error message, allowing raw DB access.
- **Likelihood:** Low.
- **Impact:** Critical — full DB access bypasses all application-layer controls.
- **Existing v2.0 mitigation:** DB connection string stored in AWS Secrets Manager; never in app
  config files or environment variables; rotated quarterly; Secrets Manager access restricted to
  backend service IAM role.
- **Residual risk:** Low.
- **Owner:** Security team

---

## Residual Risk Summary

| ID | Category | Residual Risk | Owner | Monitoring |
|----|----------|---------------|-------|------------|
| RR-V1 | Info Disclosure | Novel API key format bypasses Layer 1 scrubber | ML team + Security | New provider onboarding checklist includes scrubber update |
| RR-V2 | Info Disclosure | In-memory Fernet key exposed on compromised host | Infra team | Host-level security review; gVisor evaluation |
| RR-V3 | DoS | KMS outage > 5 min degrades all LLM operations | Platform team | `osa.kms.error_rate` P1 alert; multi-region KMS backlog |
| RR-V4 | Tampering | Second-order SQLi in new ORM queries | Backend team | Security code review required for all new ORM queries |
