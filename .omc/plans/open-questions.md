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
