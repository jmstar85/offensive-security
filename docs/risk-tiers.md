# Risk Tier Taxonomy

OSA Platform classifies every pentest step into one of four risk tiers. Tiers determine:

1. **Egress policy** — what destinations the container may reach.
2. **Approval requirement** — what session-level flag must be true before execution.
3. **Whitelist field** — which `whitelist_rules` field a target must match.
4. **Base risk weight** — input to the overall plan risk score.

> Plan v3.2.1 §0.1 Principle 4, §2.4, §5.2.

## The four tiers

| Tier | Base risk | Whitelist field | Required session flag | Examples |
|------|-----------|-----------------|------------------------|----------|
| `passive_no_target_contact` | 0.05 | `passive_allowed` | — | DNS lookups via public resolvers, CT logs (crt.sh), HIBP API, WHOIS / RDAP |
| `passive_low_touch` | 0.30 | `passive_allowed` | — | `httpx` GET (single request per host), `robots.txt` / `.well-known/`, `wappalyzer`, `securitytxt` |
| `active_recon` | 0.55 | `active_allowed` | `approved_active_recon=true` | `nmap -sV`, `nuclei` template scan, `subfinder` (bruteforce), `dnsx` (record-type enumeration), `cloudenum` |
| `active_exploit` | 0.85 | `exploit_allowed` | `approved_active_exploit=true` + admin role | `metasploit` allowlisted auxiliary/post modules, `pyrit` AI red-team probes, credential validators (write-capable APIs) |

## Why four tiers (not two)

The 4-tier model exists to make **wire activity** distinct from **decision activity**:

- `passive_no_target_contact` carries zero attribution risk to the operator — purely public-records work.
- `passive_low_touch` is "wire active but indistinguishable from background traffic" — a single GET / DNS resolve that has no operator-attributable footprint at typical timescales.
- `active_recon` is "wire activity the target can attribute" — IDS will see it, log it, and could flag it.
- `active_exploit` is "modification of target state possible" — even if the specific module is read-only.

This separation lets operators authorize a Tier 1–2 engagement without exposing Tier 3–4 by default. It also lets the planner choose less invasive intents first when the operator's `approved_active_recon` flag is not set.

## How a tool gets its tier

Tools are registered in `backend/app/agents/registry.py` with a `tier` field on the `ToolEntry` dataclass. Adding a new tool means:

1. Drop a `Dockerfile` under `docker/agents/Dockerfile.<slug>`.
2. Add a `ToolEntry` to `_REGISTRY` with the appropriate `tier` and `applicable_domain_tags`.

Tier classification rules:

- The tool **only reads public records** (no traffic to the target): `passive_no_target_contact`.
- The tool **sends one or a few HTTP/DNS requests** per host with no fuzzing flags: `passive_low_touch`.
- The tool **sends many requests** or **enumerates** the target (brute force, fuzzing, template scanning): `active_recon`.
- The tool **modifies target state** or **exercises credentials**: `active_exploit`.

When unsure, classify upward (more restrictive). The risk filter and safety chain assume conservative classification; mis-classifying low surfaces no problem at the gate.

## Strict tier-allowlist requirement

Per plan §5.2, each tier requires its own explicit allowlist:

- `active_recon` against a host that is only in `passive_allowed` → rejected at approval and at rescope.
- `active_exploit` against a host that is only in `active_allowed` → rejected.
- `exploit_allowed` is admin-only at the API layer.

There is **no fallback** from the tier-aware path to the legacy `ip_ranges` / `domains` fields. The legacy `validate_target` API still reads those fields for v3.1.x project-creation flows (no regression in existing behavior), but the rescope / approval-preview / tier-flag enforcement paths are strict.

## Wildcard blocks

Project-level `wildcard_block_regex` patterns beat every allowlist:

```jsonc
{
  "wildcard_block_regex": [
    "^.*\\.gov$",
    "^.*\\.mil$",
    "^internal\\.acme\\.com$"
  ]
}
```

Any host matching any pattern is rejected regardless of which tier list it appears in.

## Risk score derivation

The overall plan risk score is the max base-risk weight across all steps, multiplied by 10:

```python
score = max(TIER_RISK[step.tier] for step in plan.steps) * 10
```

A plan with only `passive_no_target_contact` steps scores 0.5; a plan with even one `active_exploit` step scores 8.5. The risk filter blocks any plan whose **action** matches a destructive keyword (`dos`, `ransomware`, …) regardless of tier classification.

## Observability

- `osa_session_ambiguity_score{bucket=...}` distribution by quintile bucket.
- `osa_active_recon_targets_total{result=accepted|needs_rescope|wildcard_blocked}`.
- Audit log `paused_for_rescope` entries reveal which tier triggered the pause.
