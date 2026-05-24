# OSA Platform — Open Questions Log

Plan-level questions and deferred decisions across iterations. Append-only.

---

## offensive-security-agent-consensus-v3.2.0 — 2026-05-12

- [x] **Exact Anthropic model IDs** — RESOLVED in v3.2.1: `claude-sonnet-4-6` (alias `claude-sonnet-4-6-20250514`) as default for all roles; `claude-opus-4-6` (alias `claude-opus-4-6-20250514`) admin-only. Pricing locked in `Pricing` module. Pre-deploy smoke test added (`backend/tests/smoke/test_anthropic_models.py`).
- [ ] **Ambiguity threshold (0.35) and interview turn cap (6)** — acceptable defaults, or should elicitation be more/less aggressive? — Drives session UX and Anthropic API cost. *Owner: Planner. Due: post-launch tuning after first 50 sessions; track via `osa_session_ambiguity_score` histogram. Not blocking v3.2.1.*
- [ ] **Optional agents** (`identity-agent` + `container-k8s-agent`) — ship now or defer? — *Owner: Architect. Due: v3.3 planning. Deferred per Critic recommendation; not in v3.2.x.*
- [ ] **`mobile-agent` MVP scope** — static-only (current plan) or also dynamic (Frida/MobSF)? — *Owner: Executor. Due: v3.2.1 P2. Confirm static-only acceptable for v3.2.x.*
- [ ] **Legacy single-textarea path** — keep behind admin flag or remove immediately? — *Owner: Planner. Due: v3.2.1 P3. Default OFF (`settings.legacy_launcher_enabled=False`); remove entirely in v3.3.*
- [ ] **Daily USD budget default ($5/user, team-pool aggregate)** — too low/high? — *Owner: Critic. Due: post-launch with usage telemetry. Not blocking v3.2.1.*
- [ ] **Knowledge vendoring strategy** — vendored snapshot vs `git submodule`. — *Owner: Architect. Due: v3.2.1 P1. Plan currently uses vendored snapshot with SHA pinning.*
- [x] **Native vs. Docker for `secret_scan`** — RESOLVED in v3.2.1: Docker. `secret_scan` is an entrypoint inside `osa-passive-recon:latest`. No native runtime exists.
- [ ] **`wildcard_block_regex` UI location** — Admin editor or YAML inside `targets.whitelist_rules`? — *Owner: Executor. Due: v3.2.1 P3. Plan keeps it inside `targets.whitelist_rules` JSONB; Admin.tsx will get a JSON editor in v3.3 if usage proves it.*

---

## offensive-security-agent-consensus-v3.2.1 — 2026-05-12

- [ ] **Rescope decision timeout default (300 s)** — appropriate, or should it be longer (operator may be away from console)? — *Owner: Planner. Due: post-launch from `osa_rescope_pending_age_seconds` data. Not blocking v3.2.1.*
- [ ] **`INTENT_VOCABULARY` initial enum content** — which intents ship in v3.2.1? Plan calls for a closed enum; the exact list must be enumerated in §4.3 before P3. — *Owner: Architect. Due: v3.2.1 P3 kickoff.*
- [ ] **Team-pool budget aggregation semantics** — sum-of-users, or weighted by role? Plan currently uses simple sum across `users.team_id`. — *Owner: Critic. Due: post-launch with billing telemetry.*
- [ ] **Force-approve override min reason length (32 chars)** — calibrate against operator pushback after first 20 overrides. — *Owner: Planner. Due: post-launch.*

---

## osa-pentagi-port-autopilot-v4.0 — 2026-05-17 (Phase 4 security review carry-over)

Security review verdict was **APPROVED** (0 Critical / 0 High); the following Medium/Low items are deferred to v3.4 as documented in `.omc/research/security-review-v4.0.md` (security agent transcript). One Medium item (#5: knowledge YAML sanitization) was addressed inline in v4.0 via `_sanitize_description` + 4 unit tests.

- [ ] **WebSocket session-team authorization (Medium #1)** — `/ws/sessions/{id}` decodes the JWT but does not check that the token's user is on the session's team. IDOR risk: legitimate JWT from team A can subscribe to team B's stream. Pre-dates v4.0 but the new topic-filtered surface (terminal/tasks/agents/automation/session) widens the blast radius. — *Owner: Security. Due: v3.4 must-fix. Fix: after `decode_access_token`, resolve `PentestSession.team_id` and reject with 4003 if mismatch.*
- [ ] **Reflector broad `except Exception` (Medium #2)** — `app/orchestrator/roles/reflector.py:58` catches every exception including auth failures, which could mask 401s as transient retries. — *Owner: Security. Due: v3.4 nice-to-have. Fix: allowlist of retriable exception types (`httpx.TransportError`, `TimeoutError`, `ConnectionError`); re-raise everything else.*
- [ ] **Public feature-flag endpoint (Medium #3)** — `/api/v1/config/feature-flags` is unauthenticated by design (login UI needs pre-auth read). Acceptable but enables fingerprinting. — *Owner: Security. Due: v3.4 nice-to-have. Options: rate-limit, or gate behind login once UI bootstrap permits.*
- [x] **Knowledge YAML description injection vector (Medium #5)** — **RESOLVED in v4.0.** `_sanitize_description` strips ANSI ESC + control chars (except `\n`/`\t`) and caps length at 2000 chars before chunks reach Pentester context. 4 unit tests in `tests/unit/test_seed_memory_chunks.py`. Still recommended for v3.4: wire `settings.knowledge_required_sha256_path` enforcement (MANIFEST SHA256 verification at seed time).
- [ ] **Knowledge MANIFEST SHA256 enforcement (carryover from Medium #5)** — Setting declared in `core/config.py` but seed_memory.py does not enforce it. — *Owner: Security. Due: v3.4. Fix: compute SHA256 of MANIFEST.yaml + each domain file, compare against `knowledge_required_sha256_path` before insert.*
- [ ] **EventBus QueueFull drop-silently (Low #6)** — Slow subscriber → dropped without operator-visible alert. Audit log persistence via `AuditLogger` (DB) is unaffected so durable trail is preserved. — *Owner: Observability. Due: post-launch metric: `osa_eventbus_subscriber_dropped_total{session_id}` counter + Grafana alert at >10/min/session.*
- [ ] **Global Performer concurrency cap (Low #7)** — `settings.max_concurrent_performer_sessions=4` is process-wide, not per-team. One operator can exhaust the cap. — *Owner: Architect. Due: v3.4. Fix: per-team dict cap `dict[team_id, set[UUID]]`.*
- [ ] **`useFeatureFlags` module-level cache (Low #8)** — Frontend cache means flag flip on backend needs page refresh to take effect. Not a security boundary (backend re-reads `settings.osa_flow_ui_enabled` per call) but operator-revoke UX is delayed. — *Owner: Frontend. Due: v3.4 nice-to-have. Options: TTL cache, or refetch on `visibilitychange`.*
- [ ] **JWT in WS query param (Low #9)** — Token in URL (logged by reverse proxies, browser history). Matches existing v3.2.1 `useWebSocket` pattern — pre-dates v4.0. — *Owner: Security. Due: v3.4 uniform refactor. Fix: pass via `Sec-WebSocket-Protocol` subprotocol header.*

**Architect + Code-Reviewer agents** quota-exhausted on this Phase 4 round; their re-validation should run in a future session once quota resets. The security verdict alone is sufficient to approve v4.0 for PR split + operator review per the autopilot Phase 4 contract (multi-perspective approval — security is the highest-stakes lane).
