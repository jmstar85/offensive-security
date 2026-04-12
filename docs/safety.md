# Safety Architecture — OSA Platform

## Overview

The OSA platform executes real penetration testing tools against real targets. Incorrect scope enforcement or insufficient safety controls can result in **legal liability and criminal charges**. This document describes the layered safety architecture that ensures all testing remains authorized and within scope.

---

## Safety Guard Chain

Every pentest session passes through the following guards in order. **Any rejection stops execution immediately.**

```
User Prompt
    │
    ▼
[1. Rate Limiter]          ← max 5 prompts/min per user
    │ pass
    ▼
[2. Whitelist Validator]   ← all IPs/domains must be in project whitelist
    │ pass
    ▼
[3. Claude API: Plan]      ← generates structured attack plan
    │
    ▼
[4. Exploit Allowlist]     ← only pre-approved MSF modules / Nuclei templates
    │ pass
    ▼
[5. Risk Filter]           ← blocks CRITICAL risk steps (DoS, ransomware, etc.)
    │ pass
    ▼
[6. Agent Execution]       ← Docker containers with resource limits
    │
    ├── [Kill Switch]      ← operator can stop all containers within 5s
    └── [Egress Monitor]   ← real-time outbound connection monitoring
            │ violation
            └──> Auto-kill + audit alert
    │
    ▼
[7. Audit Log]             ← every decision logged with actor, timestamp, details
```

---

## Layer 1: Rate Limiter

**Purpose:** Prevent cost runaway and rapid re-prompting that bypasses human review cadence.

**Implementation:** Token bucket per user ID — max 5 Claude API calls per minute.

**On trigger:** Returns error immediately; session is not created.

```python
# Configuration
MAX_PROMPTS_PER_MINUTE = 5  # configurable via env
```

---

## Layer 2: Whitelist Validator

**Purpose:** Ensure the AI never plans or executes actions against targets outside the authorized scope.

**Implementation:** `app/safety/whitelist.py` — validates every IP and domain against the project's `targets` table before any Claude API call.

**Validation rules:**
- IP addresses validated against CIDR ranges using Python `ipaddress` module
- Domain validation: exact match OR subdomain of an allowed domain (e.g., `api.example.com` passes if `example.com` is whitelisted)
- Empty whitelist blocks ALL targets (safe by default)

**On violation:**
1. Logs to `audit_logs` with action `whitelist_violation`
2. Session marked `failed`
3. No Claude API call is made

```bash
# Test whitelist enforcement
curl -X POST http://localhost:8000/api/v1/sessions \
  -H "Authorization: Bearer <token>" \
  -d '{"project_id": "<id>", "prompt": "Attack 8.8.8.8"}'
# → 403 Whitelist violation: IP out of scope: 8.8.8.8
```

---

## Layer 3: Exploit Allowlist

**Purpose:** Use an ALLOWLIST approach (not blocklist) — only explicitly pre-approved exploit categories are executable. Anything not listed is blocked by default.

**Approved Metasploit module prefixes:**
```
auxiliary/scanner/   ← port/service scanning only
auxiliary/gather/    ← information gathering
auxiliary/admin/     ← administrative utilities
post/multi/recon/    ← post-exploitation reconnaissance
post/multi/gather/   ← post-exploitation data gathering
exploit/multi/handler  ← listener only, no active exploit
```

**Blocked Nuclei template tags:**
```
dos         ← denial of service
fuzz        ← fuzzing (unpredictable behavior)
bruteforce  ← credential brute forcing
intrusive   ← intrusive probing
```

**On block:** Step is removed from the execution plan and logged.

---

## Layer 4: Risk Filter

**Purpose:** Block dynamically identified high-risk actions that may not be covered by the allowlist.

**Risk levels:**
| Agent | Base Risk | Level |
|-------|-----------|-------|
| nmap | 0.1 | LOW |
| pyrit | 0.3 | LOW |
| nuclei | 0.4 | MEDIUM |
| metasploit | 0.8 | HIGH |

**Blocked keywords in action field (→ CRITICAL):**
```
dos, ddos, ransomware, wiper, data_destruction,
rm -rf, format, drop table, truncate
```

**CRITICAL steps are always blocked.** HIGH and MEDIUM are logged and allowed.

---

## Layer 5: Kill Switch

**Purpose:** Allow the operator to immediately stop all running agent containers for a session, within 5 seconds.

**Trigger paths:**
1. **UI:** "Kill Session" button on the Monitor page
2. **REST API:** `POST /api/v1/sessions/{id}/kill`
3. **Automatic:** Egress Monitor violation (see below)

**What happens:**
1. All `running`/`pending` `AgentExecution` records fetched
2. Docker `stop` called on each container ID in parallel
3. All executions marked `killed`
4. Session marked `killed`
5. Audit log entry created

**Target:** < 5 second stop time for all containers.

```bash
# Manual kill switch via REST
curl -X POST http://localhost:8000/api/v1/sessions/<session-id>/kill \
  -H "Authorization: Bearer <token>"
```

---

## Layer 6: Egress Monitor

**Purpose:** Detect and block unauthorized outbound connections **during** execution (not just at plan time). This closes the gap between plan-time validation and execution-time behavior (critical for Metasploit post-exploitation lateral movement).

**Implementation:** `app/safety/egress_monitor.py` — tails Docker container log output during execution and checks any discovered IP/domain against the project whitelist.

**On violation:**
1. Auto-triggers the kill switch for the entire session
2. Logs `egress_violation` to audit log with the offending connection
3. Returns early from the executor loop

---

## Audit Logging

Every safety-relevant decision is logged to the `audit_logs` table with:

| Field | Example |
|-------|---------|
| `actor_id` | UUID of the operator |
| `action` | `whitelist_violation`, `steps_blocked`, `kill_switch_triggered`, `session_completed` |
| `target_entity` | `pentest_session` |
| `target_id` | Session UUID |
| `details_json` | `{"violations": ["IP out of scope: 10.0.0.1"]}` |
| `timestamp` | UTC timestamp |

```bash
# Retrieve audit log for a session
curl -H "Authorization: Bearer <token>" \
  "http://localhost:8000/api/v1/audit-logs?session_id=<id>"
```

---

## Container Isolation

All agent containers run with strict resource limits:

| Limit | Default | Metasploit |
|-------|---------|-----------|
| Memory | 512 MB | 2 GB |
| CPU | 1.0 cores | 2.0 cores |
| PIDs | 100 | 100 |
| Network | Isolated Docker network | Same |

Containers are destroyed after each execution (no persistent state between sessions).

---

## Legal Compliance Checklist

Before running any pentest session, verify:

- [ ] Written authorization obtained from target system owner
- [ ] Target IP ranges/domains entered in project whitelist (only authorized targets)
- [ ] Scope defined in project description
- [ ] Kill switch tested and accessible
- [ ] Audit logging confirmed active
- [ ] All test results handled per data retention policy

**The platform enforces scope technically via the whitelist, but legal authorization is the operator's responsibility.**

---

## Incident Response

If the egress monitor triggers or a whitelist violation is detected:

1. **Immediate:** Kill switch is auto-triggered — all containers stop
2. **Review:** Check `audit_logs` for the violation details
3. **Report:** Notify the client and document the incident
4. **Root cause:** Determine if the Claude-generated plan attempted to exceed scope
5. **Update whitelist:** Tighten the whitelist rules if needed

```bash
# Get all violations for review
curl -H "Authorization: Bearer <token>" \
  "http://localhost:8000/api/v1/audit-logs?action=whitelist_violation"
```
