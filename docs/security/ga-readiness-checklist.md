# GA Readiness Checklist (PR5.5 Gate)

> **Version:** 2.0
> **Scope:** OSA + XBOW W0–W5 releases
> **Classification:** INTERNAL — Security Team + TEAM_ADMIN
> **Last updated:** 2026-06-01

All hard-gate items must be checked before any GA deployment approval is granted.
Operational gates must be completed within 2 weeks of hard-gate sign-off.
Continuous monitoring must be wired before production traffic is enabled.

---

## Hard Gates (CRITICAL — block GA if FAIL)

These items represent mandatory security controls. A single FAIL or unchecked item blocks GA.

- [ ] Security review sign-off on credential_vault Fernet KMS-backed key + rotation runbook
      Assignee: Security team | Evidence: signed LGTM in PR + runbook link in wiki
- [ ] OAuth scope minimization per LLM provider (anthropic, openai, google)
      Assignee: Security team | Evidence: per-provider scope table reviewed and minimized to least-privilege
- [ ] MITM/headless threat model + STRIDE pass (Surface 2 + Surface 5)
      Assignee: Security team | Evidence: stride-mitm-headless.md + stride-scrubber.md sign-off rows filled
- [ ] osa-interactsh bidirectional network-isolation invariant (Surface 7)
      Assignee: Infra team | Evidence: MF6 assertion green in CI + stride-network-isolation.md sign-off
- [ ] Conversation scrubber 4-layer adversarial coverage (L2 FPR < 1% measured)
      Assignee: ML team | Evidence: adversarial corpus test results with FPR metric attached
- [ ] raw_conversation TEAM_ADMIN access control (close 4003 verified)
      Assignee: Security team | Evidence: E2E test `test_raw_conversation_unauthorized` passing
- [ ] Coordinator-deleted-from-replay invariant (MF1 / MF-CRITIC-1)
      Assignee: Backend team | Evidence: `test_coordinator_events_survive_purge` passing on main
- [ ] feature_flag_validator production-gated tuple set (MF3 / MF-CRITIC-8 pairwise matrix)
      Assignee: Backend team | Evidence: pairwise test matrix passing; no invalid tuple transitions in staging

---

## Operational Gates

These items must be completed before production traffic is enabled but do not block the security
sign-off process itself.

- [ ] Staging-prod telemetry parity >= 95% across all observability metrics
      Metric: compare Grafana staging vs prod dashboards; diff < 5% on all time-series panels
- [ ] Rollback drill executed for each adjacent-tuple transition (T4→T3, T3→T2, T2→T1)
      Requirements:
        - ZERO session-state corruption on rollback
        - < 10 min flip-time SLA from decision to traffic restored
        - Drill results logged in ops runbook
- [ ] CODEOWNERS coverage = 100% on new safety modules including seed_xbow.py
      Check: `git diff origin/main --name-only | xargs -I{} grep -l "{}" CODEOWNERS` returns no uncovered files
- [ ] Runbooks published for every new audit event introduced in PR5.3 set
      Audit events introduced in W4/W5:
        - `coordinator.cap_hit.iteration`
        - `coordinator.cap_hit.wall_clock`
        - `coordinator.cap_hit.token_budget`
        - `scrubber.redaction.layer1`
        - `scrubber.redaction.layer2`
        - `scrubber.canary.mismatch`
        - `raw_conversation.access.granted`
        - `raw_conversation.access.denied`
        - `credential_vault.read`
        - `credential_vault.write`
        - `network.oob_net.membership_assert`

---

## Continuous Monitoring Wired (PagerDuty)

All alerts below must be configured with PagerDuty escalation policies before production traffic is
enabled. Severity P1 = page on-call immediately; P2 = notify within 30 min; P3 = daily digest.

- [ ] **(a)** `osa.coordinator.iteration_cap_hit_rate` > 5% in 5 min → P2
      Rationale: Spike indicates adversarial loop injection or runaway agent
- [ ] **(b)** `osa.coordinator.token_budget_exceeded_rate` > 1% in 5 min → P2
      Rationale: Unexpected token spend; possible prompt injection
- [ ] **(c)** `osa.scrubber.layer2.redaction_rate` spike > 3 sigma → P1
      Rationale: Sudden increase in PII in LLM responses; possible data exfiltration path
- [ ] **(d)** `osa.scrubber.canary.mismatch_count` > 0 in 1 min → P1
      Rationale: Canary HMAC failure = active tampering with scrubber output
- [ ] **(e)** `osa.raw_conversation.unauthorized_access_count` > 0 → P1
      Rationale: Any attempt to access raw_conversation without TEAM_ADMIN is an active attack signal
- [ ] **(f)** `osa.kms.cache_miss_rate` > 20% sustained for 2 min → P2
      Rationale: KMS availability degradation; credential operations at risk
- [ ] **(g)** `osa.kms.error_rate` > 0.1% in 1 min → P1
      Rationale: KMS errors block all LLM operations; immediate triage required
- [ ] **(h)** `sidecar_image_digest.drift_detected` = true → P1
      Rationale: Unexpected sidecar image change = potential supply chain compromise
- [ ] **(i)** `osa.network.oob_net.membership_assert_failure` > 0 → P1
      Rationale: MF6 assertion failure = network isolation invariant broken
- [ ] **(j)** `osa.credential_vault.cross_user_access_attempt` > 0 → P1
      Rationale: Row-level security bypass attempt
- [ ] **(k)** `osa.coordinator.replay_purge_violation` > 0 → P1
      Rationale: MF-CRITIC-1 invariant breach = coordinator events being deleted from replay
- [ ] **(l)** `osa.feature_flag.invalid_tuple_transition` > 0 → P1
      Rationale: MF-CRITIC-8 pairwise matrix violation; safety feature bypass attempt
- [ ] **(m)** `osa.mitm.capture_buffer_overflow_count` > 0 in 5 min → P2
      Rationale: MITM buffer overflow drops traffic; potential DoS or data loss
- [ ] **(n)** `osa.interactsh.callback_rate` > 1000/min per session → P2
      Rationale: DNS amplification or callback flood from target; circuit breaker should engage

---

## Post-GA Quarterly Cadence

These recurring tasks must be scheduled in the ops runbook and assigned to named owners.

- [ ] **Fernet key rotation**
      Frequency: Quarterly (every 90 days)
      Owner: Security team
      Procedure: dual-key window rotation per runbook; verify all in-flight sessions survive

- [ ] **Sidecar image digest refresh**
      Frequency: Quarterly (or within 48 h of CVE affecting pinned image)
      Owner: Infra team
      Procedure: update pinned digest in compose file; run full integration test suite; tag new release

- [ ] **SBOM regeneration + diff review**
      Frequency: Quarterly
      Owner: Security team + Infra team
      Procedure: `syft` generates new SBOM; diff against previous; review any new transitive dependencies
      for license compliance and known vulnerabilities

- [ ] **Adversarial scrubber corpus refresh**
      Frequency: Quarterly
      Owner: ML team
      Procedure: add 20 new adversarial examples from red-team sessions; re-run FPR measurement;
      update L2 model if FPR > 1% threshold

- [ ] **Penetration test of new attack surfaces**
      Frequency: Annually (or after any major new surface added)
      Owner: External security firm + Security team
      Scope: all 7 surfaces in threat-model-v2.0.md

---

## Checklist Completion Sign-Off

| Gate | Signed Off By | Date | Notes |
|------|--------------|------|-------|
| Hard gates (all 8) | _ | _ | _ |
| Operational gates | _ | _ | _ |
| Monitoring wired | _ | _ | _ |
| Post-GA cadence scheduled | _ | _ | _ |

> **GA DECISION:** All rows above must be signed before the GA deployment approval issue is closed.
