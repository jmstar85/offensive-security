# Threat Model v2.0 — XBOW-Shaped Extensions over OSA v1.1

> **Version:** 2.0
> **Baseline:** OSA v1.1 threat model
> **Scope:** Wave 0–Wave 5 (W0–W5) XBOW extensions
> **Classification:** INTERNAL — Security Team + TEAM_ADMIN only
> **Last updated:** 2026-06-01

---

## Scope

This document covers the v2.0 XBOW-shaped extensions introduced across Waves 0–5 of the Offensive
Security Agent (OSA) project. It supersedes the v1.1 OSA baseline threat model for all surfaces
listed below, while inheriting all residual risk acceptance decisions from v1.1 that have not been
superseded by new mitigations.

Key additions over v1.1:
- MITM/headless proxy sidecar attack egress routing (W4/PR4.1)
- Coordinator iteration + wall-clock + token caps with audit (W4/PR4.2)
- Conversation scrubber 4-layer + canary HMAC + raw_conversation TEAM_ADMIN gate (W4/PR4.4)
- Interactsh OOB collaborator on isolated `osa-oob-net` (W4/PR4.1)
- Per-family token + scrubber layer metrics (W4/PR4.4)
- Coordinator-deleted-from-replay invariant (W2a/PR2a.3, MF-CRITIC-1)
- XBOW seed injection with pairwise feature-flag validation (W5/PR5.x)
- 7-surface STRIDE analysis (this document, PR5.5)

---

## Trust Boundaries

The following trust boundaries are in scope for this threat model. Traffic or data crossing any of
these boundaries is subject to the STRIDE analysis in subsequent sections.

### TB-1: Operator Browser ↔ FastAPI Backend
- **Protocol:** HTTPS (TLS 1.3 minimum) + JWT bearer tokens
- **Direction:** Bidirectional — REST requests inbound, SSE/WebSocket responses outbound
- **Enforcement:** TLS termination at load balancer; JWT validation middleware on every route
- **Scope of trust:** Operator is authenticated but NOT trusted for raw prompt injection without
  the TEAM_ADMIN role gate

### TB-2: FastAPI Backend ↔ Docker Daemon
- **Protocol:** Unix socket via `docker-socket-proxy` — never direct daemon exposure
- **Direction:** Backend → daemon only (command execution); daemon → backend (stdout/stderr)
- **Enforcement:** `IMAGE_REGEX` allowlist filter blocks non-approved images; socket proxy enforces
  read-only for all container metadata queries; no `--privileged` flag allowed
- **Scope of trust:** Daemon is fully trusted once a container passes image allowlist

### TB-3: FastAPI Backend ↔ LLM Provider APIs
- **Protocol:** HTTPS to provider endpoints (Anthropic, OpenAI, Google)
- **Direction:** Outbound requests only; responses are parsed, never exec'd
- **Enforcement:** Fernet-encrypted credentials at rest; KMS-wrapped Fernet key; credentials
  never logged; per-provider OAuth scope minimisation (see GA checklist)
- **Scope of trust:** Provider responses are treated as UNTRUSTED data and passed through the
  conversation scrubber before storage

### TB-4: FastAPI Backend ↔ MITM/Headless/Interactsh Sidecars (`osa-net`)
- **Protocol:** HTTP/HTTPS to sidecar ports on Docker network `osa-net`
- **Direction:** Backend → sidecar (proxy config, traffic routing); sidecar → backend (captured
  traffic, alerts)
- **Enforcement:** Sidecars on `osa-net` are isolated from production networks; interactsh is on
  `osa-oob-net` only and has NO `docker-socket-proxy` reach; traffic via mitmproxy when
  `OSA_TRAFFIC_VIA_MITM=1`
- **Scope of trust:** Sidecar output is UNTRUSTED until validated by the backend adapter layer

### TB-5: In-Scope Target ↔ Test Attack Agents
- **Protocol:** Varies by attack vector (HTTP, DNS, SMTP, etc.)
- **Direction:** Attack agents → target (attack traffic); target → agents (responses/callbacks)
- **Enforcement:** Target domain/IP validated against approved whitelist before any agent
  invocation; out-of-band callbacks via interactsh only (never via `osa-net`)
- **Scope of trust:** Target systems are UNTRUSTED and may return hostile payloads

---

## STRIDE Per Surface

### Surface 1: Coordinator (`CoordinatorService.run` + `run_with_iteration_cap`)

See deep-dive: [stride-coordinator.md](stride-coordinator.md)

| STRIDE | Threat | v2.0 Mitigation |
|--------|--------|-----------------|
| **Spoofing** | A malicious sub-agent forges a coordinator identity to bypass iteration cap | JWT sub-claim validated on every coordinator call; coordinator ID bound to session at creation |
| **Spoofing** | Replay of an old coordinator token to resume a capped session | Session nonce invalidated on cap exhaustion; coordinator-deleted-from-replay invariant (MF-CRITIC-1) |
| **Tampering** | Adversarial LLM output mutates coordinator state between iterations | Immutable iteration log with HMAC chain; state transitions validated before commit |
| **Tampering** | Feature flag toggled mid-session to bypass safety checks | `feature_flag_validator` locks pairwise tuple at session creation; mutations rejected (MF-CRITIC-8) |
| **Repudiation** | No audit trail for coordinator decisions / cap events | Every cap event (wall-clock, token, iteration) emits a structured audit log entry with timestamp and session ID |
| **Repudiation** | Coordinator deleted from replay buffer to hide actions | MF-CRITIC-1 opt-out lane discriminator prevents coordinator events from being purged (W2a/PR2a.3) |
| **Information Disclosure** | Coordinator exposes internal LLM reasoning in error responses | Error sanitisation strips LLM content; only status codes and safe error codes returned |
| **Information Disclosure** | Token usage leaks cost / capability information | Per-family token metrics behind `TEAM_ADMIN` gate; raw usage never in operator-visible responses |
| **Denial of Service** | Infinite loop exhausts compute/cost budget | `run_with_iteration_cap`: hard iteration limit + wall-clock cap + token budget enforced before each step |
| **Denial of Service** | Prompt injection causes runaway tool calls | Tool-call count per iteration capped; coordinator aborts on threshold breach |
| **Elevation of Privilege** | Sub-agent requests TEAM_ADMIN operation via crafted coordinator payload | Role check re-evaluated per request; coordinator cannot elevate its own role |
| **Elevation of Privilege** | Compromised coordinator gains access to raw_conversation | `raw_conversation` channel gated exclusively on `accept_raw=true` + TEAM_ADMIN role (WS close 4003 on failure) |

---

### Surface 2: MITM Proxy (mitmproxy sidecar + `MitmProxyAdapter`)

See deep-dive: [stride-mitm-headless.md](stride-mitm-headless.md)

| STRIDE | Threat | v2.0 Mitigation |
|--------|--------|-----------------|
| **Spoofing** | Rogue sidecar impersonates legitimate mitmproxy instance | Sidecar started with pinned image digest; port binding validated at startup |
| **Spoofing** | Forged MITM capture events injected into adapter | Event schema validated; unexpected fields rejected; source IP restricted to `osa-net` |
| **Tampering** | Attacker modifies intercepted traffic before backend sees it | MITM captures are read-only in adapter; no write-back path; capture signed with sidecar HMAC |
| **Tampering** | OSA_TRAFFIC_VIA_MITM=0 bypass by environment variable injection | Env var set at container launch; no runtime mutation path exposed |
| **Repudiation** | MITM captures not persisted, making forensics impossible | Capture store persisted to volume; retention policy enforced; audit event on capture start/stop |
| **Information Disclosure** | MITM captures contain credentials / PII from target responses | Scrubber pipeline applied to all captured content before storage; raw captures never returned to operators |
| **Denial of Service** | High-volume target responses flood MITM capture buffer | Capture buffer size-limited; overflow drops with alert; headless browser timeout enforced |
| **Elevation of Privilege** | Headless browser escapes sandbox via MITM proxy | Headless runs in non-privileged container; no host-network access; proxy only on `osa-net` |

---

### Surface 3: Interactsh OOB Collaborator

| STRIDE | Threat | v2.0 Mitigation |
|--------|--------|-----------------|
| **Spoofing** | Third party registers same interactsh subdomain to intercept callbacks | Subdomain generated with cryptographic random suffix; collision probability negligible |
| **Spoofing** | Fake interactsh server returns crafted DNS/HTTP callbacks | Interactsh client validates HTTPS certificate of collaborator server; token verified in callback |
| **Tampering** | Attacker injects false callbacks to trigger false-positive findings | Callback payload includes HMAC bound to session ID; backend verifies before accepting |
| **Repudiation** | Callback received but not attributed to specific attack session | Session ID embedded in subdomain label; every callback logged with originating session |
| **Information Disclosure** | OOB interaction data leaks sensitive target information | Interactsh on isolated `osa-oob-net` — no route to `osa-net` or host; data retained only for session duration |
| **Denial of Service** | Callback flood from reflective DNS amplification | Rate-limit on callback ingestion per session; circuit breaker on interactsh adapter |
| **Elevation of Privilege** | Compromised interactsh server pivots to internal network | `osa-oob-net` has no `docker-socket-proxy` or backend DB reachability; strict egress-only from backend perspective |

---

### Surface 4: Credential Vault (`UserLLMCredential` + Fernet + KMS-wrapped key)

See deep-dive: [stride-credential-vault.md](stride-credential-vault.md)

| STRIDE | Threat | v2.0 Mitigation |
|--------|--------|-----------------|
| **Spoofing** | Attacker creates a `UserLLMCredential` record for another user | Credential row is scoped to `user_id` FK; all queries filtered by authenticated user claim |
| **Spoofing** | KMS impersonation to obtain unwrapped Fernet key | KMS access via IAM role bound to service account; MFA enforced on KMS key policy |
| **Tampering** | DB row modified to substitute a different Fernet-encrypted credential | Row integrity checked via HMAC on write; mismatch triggers credential invalidation + alert |
| **Tampering** | Fernet key rotated mid-session to invalidate live credentials | Key rotation follows runbook: dual-key window allows in-flight decryption; rollback path tested |
| **Repudiation** | Credential access not audited | Every credential read/write emits structured audit event with user_id, provider, timestamp |
| **Information Disclosure** | Plaintext API key logged in application logs | Scrubber layer 1 (regex) strips `sk-*` and equivalent patterns from all log sinks |
| **Information Disclosure** | Fernet key exposed via environment variable leak | KMS-wrapped key only; plaintext Fernet key never in env vars or config files |
| **Denial of Service** | KMS unavailability prevents all LLM operations | KMS response cached (TTL = 5 min) per-instance; degraded mode returns 503 with retry-after |
| **Elevation of Privilege** | Low-privilege user reads another user's credential | Row-level security enforced in ORM layer + DB policy; cross-user query returns 403 |
| **Elevation of Privilege** | Credential vault bypass via direct DB connection string leak | DB connection string in Secrets Manager; never in app config or logs |

---

### Surface 5: Conversation Scrubber (4 layers + canary HMAC + `raw_conversation` TEAM_ADMIN gate)

See deep-dive: [stride-scrubber.md](stride-scrubber.md)

| STRIDE | Threat | v2.0 Mitigation |
|--------|--------|-----------------|
| **Spoofing** | Prompt injection disguised as scrubber passthrough | Layer 2 (NER-based) strips entity patterns regardless of encoding; canary HMAC detects tampering |
| **Spoofing** | Forged `accept_raw=true` claim to access raw_conversation | Flag only settable by TEAM_ADMIN JWT claim; re-verified on every WebSocket frame |
| **Tampering** | Adversarial payload mutates scrubbed output before storage | Canary HMAC signed on scrubber output; storage layer re-verifies before write |
| **Tampering** | Scrubber layer bypassed by Unicode/encoding tricks | Layer 3 (normalisation) canonicalises input before layers 1 + 2 run; encoding bypasses prevented |
| **Repudiation** | Scrubber decision not audited (what was redacted and why) | Per-layer redaction events logged with rule ID, span, and session reference |
| **Information Disclosure** | PII/credential leaks in scrubbed conversation output | 4-layer pipeline (regex → NER → normalisation → canary); FPR < 1% per GA checklist |
| **Information Disclosure** | `raw_conversation` accessible to non-TEAM_ADMIN operators | WebSocket close 4003 on missing/invalid TEAM_ADMIN role; verified in E2E test suite |
| **Denial of Service** | NER model inference overwhelms scrubber under high concurrency | Scrubber runs in bounded thread pool; request queue size-limited; timeout aborts with safe fallback |
| **Elevation of Privilege** | Operator promotes self to TEAM_ADMIN via crafted JWT | JWT signed by server-side secret; TEAM_ADMIN claim cannot be self-issued |

---

### Surface 6: `raw_conversation` Channel (TEAM_ADMIN only, `accept_raw=true`, close 4003)

| STRIDE | Threat | v2.0 Mitigation |
|--------|--------|-----------------|
| **Spoofing** | Session token stolen to access raw conversation of another user | Session token bound to IP + User-Agent fingerprint; rotation on privilege escalation |
| **Tampering** | Raw conversation frames manipulated in transit | TLS 1.3 required for all WebSocket connections; no plaintext fallback |
| **Repudiation** | TEAM_ADMIN access to raw_conversation not audited | Channel open/close + every frame access emits audit event with admin user_id |
| **Information Disclosure** | Raw conversation exposes unredacted LLM reasoning | Access strictly gated; scrubbed version served to non-TEAM_ADMIN; explicit operator consent required |
| **Denial of Service** | Admin floods raw_conversation channel with high-frequency polling | Server-side rate limit per TEAM_ADMIN session; backpressure applied at WebSocket layer |
| **Elevation of Privilege** | Lateral movement from raw_conversation to coordinator control plane | raw_conversation is read-only; no write path back into coordinator from this channel |

---

### Surface 7: `osa-oob-net` Bidirectional Isolation (interactsh ONLY, no docker-socket-proxy reach)

See deep-dive: [stride-network-isolation.md](stride-network-isolation.md)

| STRIDE | Threat | v2.0 Mitigation |
|--------|--------|-----------------|
| **Spoofing** | Container on `osa-net` claims to be interactsh to receive OOB callbacks | Network segmentation enforced by Docker network policy; interactsh only container on `osa-oob-net` |
| **Tampering** | `osa-oob-net` bridged to `osa-net` by misconfigured compose | MF6 runtime assertion checks network membership at startup; compose diff reviewed in CI |
| **Repudiation** | Network topology changes not audited | Docker network events forwarded to audit log; drift detected by MF6 assertion |
| **Information Disclosure** | `osa-oob-net` traffic routed through `docker-socket-proxy` | `docker-socket-proxy` not attached to `osa-oob-net`; verified in integration tests |
| **Denial of Service** | OOB network flooding from target DNS amplification | `osa-oob-net` is ingress-limited; iptables rate-limit rule applied at compose level |
| **Elevation of Privilege** | Compromised interactsh container pivots to internal services | No route from `osa-oob-net` to DB, cache, or backend; egress only to interactsh external endpoint |

---

## Residual Risks

The following risks are NOT mitigated to zero. Each has an explicit owner and monitoring metric.

| ID | Surface | Residual Risk | Owner | Monitoring Metric |
|----|---------|---------------|-------|-------------------|
| RR-1 | Coordinator | LLM jailbreak produces harmful output despite caps — caps bound resource cost, not content | Security team | `osa.scrubber.layer2.redaction_rate` spike alert |
| RR-2 | MITM Proxy | Zero-day in mitmproxy sidecar image allows RCE | Infra team | `sidecar_image_digest` drift alert; weekly image scan |
| RR-3 | Interactsh | Subdomain collision (probability ~2^-64) enables callback interception | Security team | No monitoring (acceptable risk); documented in risk register |
| RR-4 | Credential Vault | KMS outage > 5 min degrades all LLM operations | Platform team | `osa.kms.cache_miss_rate` + KMS availability alarm |
| RR-5 | Scrubber | Novel PII pattern not covered by regex/NER leaks in raw scrubbed output | ML team | Quarterly FPR audit; canary token injection test |
| RR-6 | raw_conversation | TEAM_ADMIN credentials compromised, giving attacker read access to all conversations | Security team | Anomalous TEAM_ADMIN login alert; UEBA rule |
| RR-7 | Network Isolation | Docker network isolation bypass via kernel namespace vulnerability (privilege required) | Infra team | Container security scan; gVisor evaluation in backlog |

---

## Coordinator-Deleted-From-Replay Invariant

**Reference:** MF-CRITIC-1, resolved in W2a/PR2a.3

The coordinator event opt-out lane discriminator ensures that coordinator lifecycle events
(session start, iteration, cap-hit, session end) are NEVER purged from the replay buffer by
LLM-generated content or by the conversation scrubber.

**Mechanism:**
- Coordinator events are tagged with `_lane: "coordinator"` discriminator field
- Replay buffer purge logic filters on `_lane != "coordinator"` before any deletion
- Scrubber pipeline skips coordinator-lane events entirely (they do not contain user PII)
- Integration test `test_coordinator_events_survive_purge` asserts invariant on every merge

**Cross-references:**
- `backend/tests/safety/test_adversarial_prompts.py` — adversarial corpus proving bypass attempts fail
- `backend/tests/e2e/test_attack_matrix.py` — per-vector verification including CSRF/SSRF flows
- `stride-coordinator.md` — full STRIDE analysis for this surface

---

## Sign-Off Table

| Surface | Reviewer | Date | Status |
|---------|----------|------|--------|
| Surface 1 — Coordinator | _ | _ | _ |
| Surface 2 — MITM Proxy | _ | _ | _ |
| Surface 3 — Interactsh OOB | _ | _ | _ |
| Surface 4 — Credential Vault | _ | _ | _ |
| Surface 5 — Conversation Scrubber | _ | _ | _ |
| Surface 6 — raw_conversation | _ | _ | _ |
| Surface 7 — osa-oob-net Isolation | _ | _ | _ |

> **Instructions for reviewers:** Set Status to PASS, FAIL, or CONDITIONAL. For CONDITIONAL, attach
> a linked issue with the condition that must be met before GA. All 7 surfaces must be PASS before
> the GA readiness checklist can be completed.
