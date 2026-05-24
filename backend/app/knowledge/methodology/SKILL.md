# Offensive Security Methodology — OSA Platform

Methodology pack used as planning context for every domain agent. Tactical
modules live in the per-domain SKILL.md files; this pack covers the *process*.

## Engagement phases

1. **Scoping** — Confirm authorization in writing. Capture target IPs, domains,
   cloud account IDs, and out-of-scope assets. Document the rules of engagement
   (RoE), allowed test windows, and escalation contacts.
2. **Passive recon** — Public-records-only data. No traffic that the target
   can attribute to the operator. Tier `passive_no_target_contact`.
3. **Low-touch recon** — HTTP GET, DNS lookups, public banner grabs. Wire
   activity exists but is indistinguishable from background traffic. Tier
   `passive_low_touch`.
4. **Active recon** — Subdomain enumeration, port/service discovery, template
   vulnerability scanning. Requires explicit `approved_active_recon` flag on
   the session and that targets fall inside `active_allowed`.
5. **Active exploitation** — Validated credentials, Metasploit auxiliary/post
   modules, dynamic mobile analysis. Requires `approved_active_exploit`,
   admin role, and targets inside `exploit_allowed`.
6. **Post-engagement** — Cleanup, evidence handover, retest checklist, written
   report with severity rubric (see §Severity).

## Asset-graph discipline

Maintain a target asset graph throughout the engagement. Every new asset
discovered during recon must be classified as (in_scope | out_of_scope |
needs_rescope). When classification is `needs_rescope`, the workflow service
emits `paused_for_rescope` and requires explicit operator approval before any
further probe of the asset.

## Severity rubric (engagement-level)

- **Critical** — Direct, unauthenticated path to data exfiltration or RCE.
- **High** — Authenticated path to elevated privilege, or unauthenticated path
  requiring user interaction.
- **Medium** — Information disclosure (versions, internal hostnames), MFA
  bypass requiring chained conditions.
- **Low** — Best-practice deviations with no direct exploitation path.
- **Informational** — Hygiene observations that do not constitute a finding.

## Reporting cadence

- Real-time: `paused_for_rescope` modal during execution.
- End-of-day: per-engagement findings digest (sent via configured notifier).
- End-of-engagement: PDF report + raw findings export (JSON).

## Time-budget profiles

Default budgets for each engagement profile (configurable per-project):

| Profile      | Passive | Low-touch | Active recon | Active exploit |
| ---          | ---     | ---       | ---          | ---            |
| 1-hour spot  | 15 min  | 15 min    | 25 min       | 5 min          |
| 4-hour QA    | 30 min  | 45 min    | 2 h 15 m     | 30 min         |
| 1-day audit  | 1 h     | 1 h 30 m  | 4 h          | 1 h 30 m       |
| 1-week engmt | 4 h     | 1 day     | 3 days       | 2 days         |

The orchestrator does not enforce these — they are guidance for the AI
planner during interview-loop drafting.

## Out-of-scope handling

Any AI-drafted step targeting an asset outside `passive_allowed ∪
active_allowed ∪ exploit_allowed` is rejected at approval time. The operator
must either edit the step, add the asset to the appropriate allowlist, or
remove the step before the session can proceed.

## Decision rights

- AI proposes; operator approves. No step executes without an explicit
  `approved_at` transition.
- Discovered targets surfaced mid-execution pause the session via
  `paused_for_rescope` (state machine in service.py).
- `claude-opus-4-6` is reserved for high-risk drafts and requires admin role.
