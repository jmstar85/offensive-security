# Rescope Flow

This document describes how the OSA Platform handles **discovered targets** — hosts that surface mid-execution from an active recon step (e.g., a `subfinder` run yields a new subdomain that was not in the project's original scope).

> Anchored to plan v3.2.1 §5.1. Resolves the v3.2.0 Critic D-1 BLOCKER.

## Why rescope exists

An AI-drafted plan is bounded by the project whitelist at **approval time**. Once a session is `executing`, active recon tools (`subfinder`, `dnsx`, `nmap`) emit new hostnames the planner could not see. Without a re-validation gate, those hosts would be probed without any operator decision.

The rescope flow inserts a hard gate: any newly-discovered host whose tier requires a list it is not on **pauses the session** and **requires explicit operator approval** before the orchestrator may resume.

## State machine

```
executing
   ├─ discovered targets classified by tier
   │     ├─ all in scope            → continue executing
   │     ├─ ≥1 wildcard_block_regex → auto-drop (operator never sees)
   │     └─ ≥1 out-of-tier-scope    → paused_for_rescope (RescopeApproval row, status=pending)
   │
paused_for_rescope
   ├─ POST /rescope { accept: [...], reject: [...] }
   │     ├─ accept ≥ 1 host (any other rescope rows also resolved) → executing
   │     └─ accept = 0 (all rejected), no other approved rescopes  → killed
   │
   ├─ rescope_decision_timeout_seconds elapses (default 300s)
   │     └─ status=timed_out, accepted=[], rejected=all              → killed (safety-favoring)
```

Multiple rescope rows can be pending for one session (e.g., separate active steps emit different discoveries). The session leaves `paused_for_rescope` only when **all** pending rows have a terminal decision.

## Endpoints

| Method | Path | Behavior |
|--------|------|----------|
| `GET` | `/api/v1/pentest-sessions/{id}/rescope-pending` | list pending rescope rows + discovered hosts |
| `POST` | `/api/v1/pentest-sessions/{id}/rescope` | operator decides `accept` / `reject` (must partition discovered set) |

Decision payload:

```json
{
  "rescope_id": "<UUID>",
  "accept": ["api.acme.com"],
  "reject": ["evil.example.org"],
  "reason": "api.acme.com is in the engagement RoE addendum"
}
```

The `accept` ∪ `reject` set **must equal** the rescope row's `discovered_targets.rejected` set; partial decisions return `400 accept_reject_must_partition_discovered`.

## Safety guarantees

1. **Wildcard block beats every allowlist.** Hosts matching `wildcard_block_regex` are dropped before the operator sees them; they never enter a rescope row.
2. **Auto-drop on timeout favors safety.** When the operator does not decide within `rescope_decision_timeout_seconds`, the discovered set is silently dropped and the session is killed (if no other accepted hosts exist).
3. **Tier-aware validation is strict.** `active_recon` requires `active_allowed`; `active_exploit` requires `exploit_allowed`. No legacy fallback to `ip_ranges` / `domains` in this path.
4. **Idempotent decisions.** A second `POST /rescope` on the same `rescope_id` returns `409 rescope already decided`.

## Observability

Every transition emits:

- Audit log action: `paused_for_rescope`, `rescope_approved`, `rescope_rejected`, `rescope_auto_drop`.
- Prometheus counter: `osa_rescope_events_total{action}` (`paused` / `approved` / `rejected` / `auto_drop`).
- Per-host counter: `osa_active_recon_targets_total{result}` (`accepted` / `needs_rescope` / `wildcard_blocked`).

Grafana dashboard: `docs/observability/safety-chain.json`.

## Operational guidance

- Expect 5–15 rescope events per realistic external recon engagement (per Architect v3.2.1 §3 Tension D).
- Keep `wildcard_block_regex` tight: `^.*\.gov$`, `^.*\.mil$`, `^.*\.edu$`, and any operator-supplied "never touch" patterns.
- When rescope decisions become repetitive (same host appearing 3+ times), surface that as a project-level scope addition request rather than a per-session rescope.
- The 300s timeout is operator-tunable via `settings.rescope_decision_timeout_seconds`; engagements with on-call rotation may extend to 900s, but the safety-favoring auto-drop default should not change.
