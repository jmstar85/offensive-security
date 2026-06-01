# STRIDE Deep Dive — Surface 7: osa-oob-net Bidirectional Isolation

> **Surface:** `osa-oob-net` Docker network + interactsh container + MF6 runtime assertion
> **Threat model version:** 2.0
> **Wave coverage:** W4 (PR4.1) — interactsh sidecar + network isolation
> **Invariant:** Interactsh ONLY on `osa-oob-net`; no `docker-socket-proxy` reach; no route to `osa-net`
> **Last updated:** 2026-06-01

---

## Overview

The `osa-oob-net` Docker network is a dedicated isolated network used exclusively by the interactsh
OOB collaborator container. It has no route to `osa-net` (the primary sidecar network), no access
to the `docker-socket-proxy`, and no path to the backend database or cache. This bidirectional
isolation ensures that:

1. A compromised interactsh container cannot pivot to internal services.
2. Callbacks received on `osa-oob-net` cannot be injected into `osa-net` traffic.
3. The `docker-socket-proxy` cannot be reached from `osa-oob-net` containers.

The MF6 runtime assertion verifies network membership at container startup and fails fast if
the invariant is violated.

---

## Spoofing

### Threat S-1: Container on `osa-net` claims to be interactsh to receive OOB callbacks
- **Scenario:** A compromised container on `osa-net` registers itself as the interactsh callback
  receiver, intercepting OOB callbacks intended for the legitimate interactsh instance.
- **Likelihood:** Low — network segmentation prevents `osa-net` containers from accessing `osa-oob-net`.
- **Impact:** High — false negative on OOB callbacks; real callbacks suppressed.
- **Existing v2.0 mitigation:** Docker network segmentation enforced at compose level; `osa-net`
  and `osa-oob-net` have no common bridge; interactsh only container attached to `osa-oob-net`;
  callback HMAC verified by backend before acceptance.
  Proved by: `backend/tests/e2e/test_attack_matrix.py` — SSRF/OOB network isolation tests (PR4.5).
- **Residual risk:** Low. Requires Docker network bypass (host-level kernel vulnerability).
- **Owner:** Infra team

### Threat S-2: Fake interactsh subdomain registered to intercept callbacks
- **Scenario:** Attacker registers a subdomain that collides with the interactsh subdomain used
  by the attack session, intercepting DNS/HTTP callbacks from the target.
- **Likelihood:** Very Low — cryptographic random suffix makes collision probability ~2^-64.
- **Impact:** Medium — false positive callbacks; attacker learns about attack target behaviour.
- **Existing v2.0 mitigation:** Subdomain generated with 64-bit cryptographic random suffix;
  interactsh client validates HTTPS certificate of collaborator server; session token embedded in
  subdomain label and verified in callback payload.
- **Residual risk:** Very Low (accepted, documented in risk register as RR-3).
- **Owner:** Security team

---

## Tampering

### Threat T-1: `osa-oob-net` bridged to `osa-net` by misconfigured compose file
- **Scenario:** An accidental or malicious change to `docker-compose.yml` adds `osa-oob-net` as a
  second network attachment for an `osa-net` container, creating a bridge between the two networks.
- **Likelihood:** Medium — compose file changes are a common source of misconfiguration.
- **Impact:** Critical — interactsh can now reach `osa-net` services; isolation invariant broken.
- **Existing v2.0 mitigation:** MF6 runtime assertion checks network membership at container startup;
  fails fast if any `osa-oob-net` container also appears on `osa-net` (or vice versa); CI pipeline
  runs compose diff review to detect network attachment changes; CODEOWNERS gate on `docker-compose*.yml`.
  Proved by: `backend/tests/e2e/test_attack_matrix.py` — MF6 assertion tests.
- **Residual risk:** Low. MF6 catches runtime misconfiguration; CI catches compose changes.
- **Owner:** Infra team

### Threat T-2: `docker-socket-proxy` attached to `osa-oob-net` by configuration drift
- **Scenario:** Infrastructure drift or automated tooling adds the `docker-socket-proxy` container
  to `osa-oob-net`, giving the interactsh container access to the Docker daemon.
- **Likelihood:** Low.
- **Impact:** Critical — interactsh can enumerate and control containers via Docker API.
- **Existing v2.0 mitigation:** `docker-socket-proxy` network attachments explicitly enumerated in
  compose; MF6 assertion verifies `docker-socket-proxy` is NOT on `osa-oob-net`; compose change
  triggers mandatory security review.
- **Residual risk:** Low.
- **Owner:** Infra team

---

## Repudiation

### Threat R-1: Network topology changes not audited
- **Scenario:** A network bridge is created between `osa-oob-net` and `osa-net` but no audit record
  exists, making it impossible to determine when the isolation was broken or by whom.
- **Likelihood:** Low — Docker network events are captured by daemon.
- **Impact:** High — forensic gap for isolation breaches.
- **Existing v2.0 mitigation:** Docker network events (`network connect`, `network disconnect`)
  forwarded to structured audit log; MF6 assertion failure emits `network.oob_net.membership_assert_failure`
  audit event with container ID, network name, and timestamp; compose change audit trail in git.
- **Residual risk:** Low.
- **Owner:** Platform team

### Threat R-2: OOB callback received but not attributed to session
- **Scenario:** An interactsh callback arrives but is not associated with the originating attack
  session, making it impossible to attribute the OOB interaction.
- **Likelihood:** Low — session ID embedded in subdomain label.
- **Impact:** Medium — finding cannot be attributed; false positive risk.
- **Existing v2.0 mitigation:** Session ID embedded in interactsh subdomain label at generation
  time; every callback logged with originating session ID extracted from subdomain; unattributed
  callbacks rejected with warning audit event.
- **Residual risk:** Low.
- **Owner:** Backend team

---

## Information Disclosure

### Threat I-1: `osa-oob-net` traffic routed through `docker-socket-proxy`
- **Scenario:** Traffic from `osa-oob-net` is somehow routed through the `docker-socket-proxy`,
  exposing Docker API responses to the interactsh container.
- **Likelihood:** Very Low — no network path exists by design.
- **Impact:** High — interactsh gains Docker API access.
- **Existing v2.0 mitigation:** `docker-socket-proxy` not attached to `osa-oob-net`; no iptables
  FORWARD rules between the two networks; verified in integration tests that cross-network HTTP
  requests from `osa-oob-net` to `docker-socket-proxy` port fail with connection refused.
  Proved by: `backend/tests/e2e/test_attack_matrix.py` — network isolation integration tests.
- **Residual risk:** Low.
- **Owner:** Infra team

### Threat I-2: OOB interaction data retained longer than session
- **Scenario:** Interactsh callback data (which may include sensitive target information) is
  retained after the attack session ends, creating a data retention risk.
- **Likelihood:** Medium — default retention policies may be too long.
- **Impact:** Medium — stale OOB data accessible beyond session lifecycle.
- **Existing v2.0 mitigation:** OOB interaction data retained only for session duration + 1 h grace;
  session termination triggers callback data purge job; purge job runs within 10 min of session end.
- **Residual risk:** Low-Medium. Purge job failure would retain data beyond intended window.
  Monitoring alert on purge job failure required.
- **Owner:** Platform team

---

## Denial of Service

### Threat D-1: OOB network flooding from reflective DNS amplification
- **Scenario:** Target performs a DNS amplification attack via the interactsh subdomain, flooding
  the `osa-oob-net` interface with high-volume DNS responses.
- **Likelihood:** Low-Medium — DNS amplification is a known attack technique.
- **Impact:** Medium — OOB network saturation; interactsh container unavailable.
- **Existing v2.0 mitigation:** `osa-oob-net` is ingress-limited via iptables rate-limit rule
  (default 1000 packets/s); rate-limit rule applied in compose at network creation; circuit breaker
  on interactsh adapter disables OOB callbacks when rate threshold exceeded.
- **Residual risk:** Low-Medium. Extremely high amplification factor could exceed rate limit before
  circuit breaker engages.
- **Owner:** Infra team

### Threat D-2: Interactsh container crash causes missed OOB callbacks
- **Scenario:** Interactsh container crashes or is OOM-killed during a session, causing OOB
  callbacks from the target to be missed.
- **Likelihood:** Low-Medium — containers can crash under load.
- **Impact:** Medium — false negative on OOB-dependent findings.
- **Existing v2.0 mitigation:** Interactsh container configured with `restart: always` in compose;
  health check polls container status every 10 s; container restart emits audit event; session
  coordinator notified of sidecar restart so it can re-register the subdomain.
- **Residual risk:** Low. A restart during active callback window (< 10 s) may miss one callback.
- **Owner:** Infra team

---

## Elevation of Privilege

### Threat E-1: Compromised interactsh container pivots to internal services
- **Scenario:** An exploited vulnerability in the interactsh binary allows RCE; attacker attempts
  to pivot from `osa-oob-net` to reach the backend DB, cache, or other internal services.
- **Likelihood:** Low — requires a zero-day in interactsh.
- **Impact:** Critical — full internal network access.
- **Existing v2.0 mitigation:** No route from `osa-oob-net` to DB, cache, backend, or any other
  internal service; `osa-oob-net` has egress only to the interactsh external endpoint (DNS + HTTPS);
  container runs as non-root user; no capabilities granted beyond NET_BIND_SERVICE.
- **Residual risk:** Medium. Zero-day in interactsh + Docker network isolation bypass (kernel vuln)
  would break this. gVisor as an additional sandbox is in the backlog.
- **Owner:** Infra team

### Threat E-2: `osa-oob-net` used as a pivot to reach `osa-net` services
- **Scenario:** Attacker on `osa-oob-net` exploits a Docker network misconfiguration to reach
  containers on `osa-net` (mitmproxy, headless browser).
- **Likelihood:** Low — requires Docker network bypass.
- **Impact:** High — MITM captures and headless browser accessible from compromised interactsh.
- **Existing v2.0 mitigation:** Bidirectional network isolation: no bridge, no iptables FORWARD
  rules, no shared container attachments between `osa-oob-net` and `osa-net`; MF6 runtime assertion
  verifies isolation at startup and on any Docker network event.
  Proved by: integration tests verifying cross-network connection failures.
- **Residual risk:** Low. Kernel-level namespace escape is the residual risk class.
- **Owner:** Infra team

---

## Residual Risk Summary

| ID | Category | Residual Risk | Owner | Monitoring |
|----|----------|---------------|-------|------------|
| RR-N1 | Elevation | interactsh zero-day + Docker network isolation bypass | Infra team | Weekly image CVE scan; gVisor backlog |
| RR-N2 | DoS | High-amplification DNS flood exceeds iptables rate limit | Infra team | `osa.network.oob_net.packet_rate` alert |
| RR-N3 | Info Disclosure | Purge job failure retains OOB data beyond session | Platform team | Purge job success/failure alert |
| RR-N4 | Spoofing | Subdomain collision (accepted, ~2^-64 probability) | Security team | Documented in risk register; no automated monitoring |
