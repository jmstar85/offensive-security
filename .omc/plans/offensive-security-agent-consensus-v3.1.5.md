# OSA Platform v3.1.5 — Iteration 5 (Resolves §B 7 HIGH-MED ambiguities)

**Status:** Iteration 5/5 — addresses 7 HIGH-MED ambiguities from `PLAN-VERIFICATION-2026-05-10.md` §B
**Companion docs (read together):**
- v2.1 baseline (implemented): `offensive-security-agent-consensus.md`
- v3.0 base: `offensive-security-agent-consensus-v3.md`
- v3.1+v3.1.3 amendments: `offensive-security-agent-consensus-v3.1.md`
- v3.1.4-rev1 (§A fixes): `offensive-security-agent-consensus-v3.1.4.md`
- **v3.1.5 (this file):** §B canonical specs — supersedes the cited §sections in v3.1 / v3.0

**Scope:** §B HIGH-MED items only. §C MED-LOW items deferred to implementation phase. After this iteration, plan is implementation-ready.

**Locked decisions unchanged.**

---

## §W. Iteration-5 Decision Map

| # | From verification | Resolution location |
|---|---|---|
| B-1 | scope_rules schema undefined | §W.1 (canonical schema, full JSON Schema 2020-12) |
| B-2 | `_classify(step)` rules undefined | §W.2 (classification matrix) |
| B-3 | CoreDNS sidecar mechanism ambiguous | §W.3 (per-session shared CoreDNS, option c) |
| B-4 | Paused sub plan_version freezing | §W.4 (refresh-on-wake policy, option a) |
| B-5 | Concurrent ApprovalGrant 409 race | §W.5 |
| B-6 | Per-target credential M:N | §W.6 (M:N via join table, option a) |
| B-7 | (= A-1, resolved in v3.1.4 §V.1) | — |

---

## §W.1 Canonical `scope_rules` schema (resolves B-1)

**Decision:** add formal JSON Schema 2020-12 per `target_type`. Stored as JSONB in `targets.whitelist_rules` (per v3.1.4 §V.4). Validated on POST `/api/v1/targets` and on every adapter call via `app/safety/scope_validator.py`.

### §W.1.0 Canonical `target_type` ENUM (consistency fix)

**Authoritative ENUM (matches v3.1 §J.1, v3.0 §5.4 `_DOMAIN_AGENTS` keys, and v3.1 §K.1 backward-compat default):**

```sql
target_type ENUM('application', 'web', 'cloud_azure', 'source_code') NOT NULL DEFAULT 'web'
```

This **supersedes** any earlier draft text (including v3.1.4 §V.6 which incorrectly listed `'web_application'`). Schema filenames in §W.1.6 use `application.json`, `web.json`, `cloud_azure.json`, `source_code.json`.

Mapping to domain agents (per v3.0 §5.4 line 325):
- `'application'` → `ApplicationAgent` (Nmap-based app-layer scan)
- `'web'` → `WebAgent` (Nuclei + Pyrit)
- `'cloud_azure'` → `CloudAzureAgent` (ScoutSuite + Microburst + PowerZure + ROADrecon)
- `'source_code'` → `SourceCodeAgent` (gitleaks + semgrep + trivy)

CI gate: `grep -rn "web_application" backend/ docs/ .omc/plans/offensive-security-agent-consensus-v3.1.{4,5}.md` → expect zero matches outside this §W.1.0 historical note.

### §W.1.1 Common envelope (all target_types)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "osa://schemas/scope_rules/common.json",
  "type": "object",
  "required": ["version"],
  "properties": {
    "version": { "const": 1 },
    "notes": { "type": "string", "maxLength": 1024 }
  }
}
```

`version: 1` is the only supported value at MVP. Future schema bumps must be backward-readable; readers reject unknown major versions with a clear error.

### §W.1.2 `target_type = "web"`

```json
{
  "$id": "osa://schemas/scope_rules/web.json",
  "allOf": [{ "$ref": "common.json" }],
  "type": "object",
  "required": ["domains"],
  "properties": {
    "domains": {
      "type": "array",
      "minItems": 1,
      "maxItems": 50,
      "items": { "type": "string", "format": "hostname",
                 "pattern": "^(\\*\\.)?[a-z0-9]([a-z0-9-]*[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$" }
    },
    "ip_ranges": {
      "type": "array",
      "items": { "type": "string", "format": "ipv4-cidr-or-host" },
      "default": []
    },
    "ports": {
      "type": "array",
      "items": { "type": "integer", "minimum": 1, "maximum": 65535 },
      "default": [80, 443]
    },
    "exclude_paths": {
      "type": "array",
      "items": { "type": "string", "pattern": "^/" },
      "default": []
    }
  },
  "additionalProperties": false
}
```

**Wildcard semantics:** `*.example.com` matches one or more subdomain labels (`a.example.com`, `a.b.example.com`); does NOT match the apex `example.com` — apex must be listed separately if in scope.

### §W.1.3 `target_type = "cloud_azure"`

```json
{
  "$id": "osa://schemas/scope_rules/cloud_azure.json",
  "allOf": [{ "$ref": "common.json" }],
  "type": "object",
  "required": ["azure_subscriptions", "tenants"],
  "properties": {
    "azure_subscriptions": {
      "type": "array",
      "minItems": 1,
      "items": { "type": "string", "format": "uuid" }
    },
    "tenants": {
      "type": "array",
      "minItems": 1,
      "items": { "type": "string", "format": "uuid" }
    },
    "allowed_resource_groups": {
      "type": "array",
      "items": { "type": "string", "pattern": "^[A-Za-z0-9._\\-()]{1,90}$" },
      "default": []
    },
    "allowed_storage_accounts": {
      "type": "array",
      "items": { "type": "string", "pattern": "^[a-z0-9]{3,24}$" },
      "default": []
    },
    "allowed_key_vaults": {
      "type": "array",
      "items": { "type": "string", "pattern": "^[a-zA-Z][a-zA-Z0-9-]{2,23}$" },
      "default": []
    },
    "allow_ms_graph": { "type": "boolean", "default": false },
    "allow_priv_esc_simulation": { "type": "boolean", "default": false }
  },
  "additionalProperties": false
}
```

**Empty allow-lists semantics:**
- `allowed_resource_groups: []` (or absent) → **all** RGs in listed subscriptions are in scope.
- `allowed_storage_accounts: []` → all storage accounts in the in-scope subscriptions (with default `false` for storage-write priv-esc actions per §W.2).
- `allowed_key_vaults: []` → **no** Key Vault access permitted (closed by default — this is the only allow-list whose `[]` means "deny all").
- `allow_ms_graph: false` → MS Graph calls blocked at `AzureScopeValidator`.
- `allow_priv_esc_simulation: false` → ApprovalGate **always** denies priv-esc steps (no operator approval can override). Phase-2: per-target operator override toggle.

Rationale for KV exception: Key Vault contents are typically the highest-value data; opt-in is safer than opt-out.

### §W.1.4 `target_type = "source_code"`

```json
{
  "$id": "osa://schemas/scope_rules/source_code.json",
  "allOf": [{ "$ref": "common.json" }],
  "type": "object",
  "required": ["git_url"],
  "properties": {
    "git_url": {
      "type": "string",
      "pattern": "^(https://|git@)[\\w.\\-]+[:/][\\w./\\-]+(\\.git)?$"
    },
    "branch": { "type": "string", "default": "HEAD" },
    "include_paths": {
      "type": "array",
      "items": { "type": "string" },
      "default": []
    },
    "exclude_paths": {
      "type": "array",
      "items": { "type": "string" },
      "default": ["node_modules/", ".git/", "dist/", "build/"]
    },
    "deep_history_scan": { "type": "boolean", "default": false }
  },
  "additionalProperties": false
}
```

### §W.1.5 `target_type = "application"` (Nmap-based app-layer scan, MVP)

```json
{
  "$id": "osa://schemas/scope_rules/application.json",
  "allOf": [{ "$ref": "common.json" }],
  "type": "object",
  "required": ["ip_ranges"],
  "properties": {
    "ip_ranges": {
      "type": "array",
      "minItems": 1,
      "maxItems": 50,
      "items": { "type": "string",
                 "pattern": "^(\\d{1,3}\\.){3}\\d{1,3}(/(?:[0-9]|[12][0-9]|3[0-2]))?$" }
    },
    "ports": {
      "type": "array",
      "items": { "type": "integer", "minimum": 1, "maximum": 65535 },
      "default": [22, 80, 443, 3389, 5985, 5986, 8080, 8443]
    },
    "scan_intensity": {
      "type": "string",
      "enum": ["light", "standard", "aggressive"],
      "default": "standard"
    },
    "exclude_ips": {
      "type": "array",
      "items": { "type": "string", "pattern": "^(\\d{1,3}\\.){3}\\d{1,3}$" },
      "default": []
    }
  },
  "additionalProperties": false
}
```

Conflict resolution: if `ip_ranges` and `exclude_ips` overlap, `exclude_ips` wins (excluded IPs are dropped from the effective scan list at adapter level).

### §W.1.6 Implementation

```python
# app/safety/scope_schema.py  (NEW)
import ipaddress, json, re
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from importlib.resources import files

_SCHEMA_NAMES = ("common", "application", "web", "cloud_azure", "source_code")
_RAW = {n: json.loads(files("app.safety.schemas").joinpath(f"{n}.json").read_text())
        for n in _SCHEMA_NAMES}

# Build a Registry so $ref to common.json resolves
_REGISTRY = Registry().with_resources([
    (f"osa://schemas/scope_rules/{n}.json", Resource.from_contents(_RAW[n]))
    for n in _SCHEMA_NAMES
])

# Custom format checker — Draft 2020-12 has no built-in CIDR-or-host format
_format_checker = FormatChecker()

@_format_checker.checks("ipv4-cidr-or-host", raises=ValueError)
def _check_ipv4_cidr_or_host(v: str) -> bool:
    try:
        ipaddress.ip_network(v, strict=False)
        return True
    except ValueError:
        return bool(re.fullmatch(r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))+", v))

_VALIDATORS: dict[str, Draft202012Validator] = {
    n: Draft202012Validator(_RAW[n], registry=_REGISTRY, format_checker=_format_checker)
    for n in ("application", "web", "cloud_azure", "source_code")
}

def validate_scope_rules(target_type: str, rules: dict) -> None:
    """Raises ScopeRulesInvalid (400) on validation failure."""
    if target_type not in _VALIDATORS:
        raise ScopeRulesInvalid(f"unsupported target_type: {target_type}")
    errors = sorted(_VALIDATORS[target_type].iter_errors(rules), key=lambda e: list(e.path))
    if errors:
        raise ScopeRulesInvalid([
            {"path": list(e.path), "message": e.message} for e in errors
        ])
```

Called from `app/api/v1/targets.py` BEFORE the ORM insert, AND from each domain agent's `prepare()` step before any tool dispatch (defense in depth — DB rows could be edited externally).

### §W.1.7 Tests

| Test | Target type | Body | Expected |
|---|---|---|---|
| valid web | web | `{version:1, domains:["*.example.com","example.com"]}` | 201 |
| invalid web (no domains) | web | `{version:1}` | 400 |
| invalid hostname pattern | web | `{version:1, domains:["BAD..host"]}` | 400 |
| valid application minimal | application | `{version:1, ip_ranges:["10.0.0.0/24"]}` | 201 |
| application invalid CIDR | application | `{version:1, ip_ranges:["10.0.0.0/40"]}` | 400 (custom FormatChecker) |
| application overlap excluded | application | `{version:1, ip_ranges:["10.0.0.0/24"], exclude_ips:["10.0.0.5"]}` → effective scan list | excludes 10.0.0.5 |
| valid azure minimal | cloud_azure | `{version:1, azure_subscriptions:[uuid], tenants:[uuid]}` | 201 |
| azure KV access default-deny | cloud_azure | per above + adapter calls KV → expect violation | violation |
| azure with `allow_ms_graph:true` | cloud_azure | adapter calls graph.microsoft.com | allowed |
| source_code valid | source_code | `{version:1, git_url:"https://github.com/x/y.git"}` | 201 |
| source_code SSH URL | source_code | `{version:1, git_url:"git@github.com:x/y.git"}` | 201 |
| unknown version rejected | web | `{version:99, domains:[...]}` | 400 |
| extra property rejected | web | `{version:1, domains:[...], evil:true}` | 400 |
| `$ref` resolution works | web | (validator boots without `RefResolutionError`) | startup test passes |
| custom format checker registered | application | `Draft202012Validator.FORMAT_CHECKER` includes `ipv4-cidr-or-host` | unit assertion |

---

## §W.2 ApprovalGate `_classify(step)` matrix (resolves B-2)

**Decision:** explicit `(domain_agent, internal_tool, action)` → action_class lookup table. Default = no approval needed. Conservative: when in doubt, gate it.

### §W.2.0 Canonical `step` dict shape

The classifier, ApprovalGate, Blackboard, and DomainAgent all share this structure:

```python
# app/orchestrator/types.py  (NEW)
class Step(TypedDict, total=False):
    agent: Literal["application", "web", "cloud_azure", "source_code"]  # ENUM matches §W.1.0
    tool: str            # e.g., "nmap", "nuclei", "metasploit", "powerzure", "scoutsuite"
    action: str          # tool-specific verb (e.g., "scan", "Get-AzureUserInformation", "exploit")
    config: dict         # tool/action params; tags, flags, module_path, etc.
    dry_run: bool        # if True, classifier returns None
    plan_version: int    # set by master at distribution; mirrors blackboard control
```

`step_hash` (used by ApprovalGate per v3.1 §F.2) is computed over `(agent, action, config)` — NOT including `tool` because `tool` is derivable from `(agent, action)` and NOT including `dry_run`/`plan_version` (those are routing metadata). This matches v3.1 §F.2 line 287-289.

### §W.2.1 Classification table

| Domain agent | Internal tool | Action / module | action_class | Rationale |
|---|---|---|---|---|
| `cloud_azure` | PowerZure | **any** module | `privilege_escalation` | Entire toolkit is offensive Azure AD; default-gate all |
| `cloud_azure` | Microburst | `Invoke-EnumerateAzureBlobs` (read) | None | Read-only reconnaissance |
| `cloud_azure` | Microburst | `Invoke-AzureUploadKeyVaultCert` | `privilege_escalation` | Write to KV |
| `cloud_azure` | Microburst | `Invoke-AzureRunbookData` (executes runbook) | `privilege_escalation` | Code execution on hybrid worker |
| `cloud_azure` | Microburst | any other action with verb prefix `Set-`, `New-`, `Remove-`, `Update-`, `Add-`, `Invoke-Azure*Run*`, `Invoke-Azure*Upload*` | `privilege_escalation` | Write/exec verbs |
| `cloud_azure` | ScoutSuite | any action | None | Read-only audit |
| `cloud_azure` | ROADrecon | `gather` (full enumerate) | None | Read-only |
| `cloud_azure` | ROADrecon | `auth` with `--pass-policy-bypass` flag | `privilege_escalation` | Auth bypass |
| `cloud_azure` | ROADrecon | any action prefixed `role_grant` | `privilege_escalation` | Role grant |
| `web` | Metasploit | any module under `exploit/` | `privilege_escalation` | Active exploitation |
| `web` | Metasploit | any module under `auxiliary/scanner/` | None | Passive scanning |
| `web` | Metasploit | any module under `auxiliary/admin/`, `post/` | `privilege_escalation` | Admin actions / post-exploitation |
| `web` | Nuclei | any template tagged `cve` AND `critical` AND `rce` (intersection) | `privilege_escalation` | RCE chain — gate |
| `web` | Nuclei | other templates | None | Detection only |
| `web` | Pyrit | `harmbench-eval`, `multi-turn-attack`, any prompt-injection chain that targets a *deployed* customer LLM (not synthetic test target) | `privilege_escalation` | Active red-team against production AI |
| `web` | Pyrit | single-prompt `evaluate` against synthetic/test target | None | Eval-only |
| `application` | Nmap | any scan | None | Reconnaissance |
| `application` | Nmap | any scan with `--script intrusive` or `--script vuln` selection that includes `*-exploit` scripts | `privilege_escalation` | NSE intrusive exploit scripts |
| `source_code` | gitleaks / semgrep / trivy | any | None | Static analysis only |
| Any | any | step explicitly tagged `dry_run: true` | None | Dry-run override (master sets this) |

### §W.2.2 Implementation

```python
# app/safety/approval_classifier.py  (NEW)
import re

PRIV_ESC_RULES: list[Callable[[Step], bool]] = [
    # CloudAzure / PowerZure — default-gate everything
    lambda s: s["agent"] == "cloud_azure" and s["tool"] == "powerzure",

    # CloudAzure / Microburst — write/exec verbs
    lambda s: (s["agent"] == "cloud_azure" and s["tool"] == "microburst"
               and bool(re.match(r"^(Set-|New-|Remove-|Update-|Add-|Invoke-Azure.*?(Run|Upload))",
                                  s.get("action", "")))),

    # CloudAzure / ROADrecon — fixed precedence (parenthesized)
    lambda s: (s["agent"] == "cloud_azure" and s["tool"] == "roadrecon" and (
        (s.get("action") == "auth"
         and "pass-policy-bypass" in s.get("config", {}).get("flags", []))
        or s.get("action", "").startswith("role_grant")
    )),

    # Web / Metasploit — exploit/admin/post categories
    lambda s: (s["agent"] == "web" and s["tool"] == "metasploit"
               and s.get("config", {}).get("module_path", "").startswith(
                   ("exploit/", "auxiliary/admin/", "post/"))),

    # Web / Nuclei — cve+critical+rce intersection
    lambda s: (s["agent"] == "web" and s["tool"] == "nuclei"
               and {"cve", "critical", "rce"}.issubset(set(s.get("config", {}).get("tags", [])))),

    # Web / Pyrit — production-target chains
    lambda s: (s["agent"] == "web" and s["tool"] == "pyrit"
               and s.get("action") in {"harmbench-eval", "multi-turn-attack"}
               and s.get("config", {}).get("target_kind") == "production"),

    # Application / Nmap — intrusive NSE
    lambda s: (s["agent"] == "application" and s["tool"] == "nmap"
               and any(t in (s.get("config", {}).get("scripts") or [])
                       for t in ("intrusive", "vuln", "exploit"))),
]

def classify(step: Step) -> str | None:
    if step.get("dry_run"):
        return None
    for rule in PRIV_ESC_RULES:
        try:
            if rule(step):
                return "privilege_escalation"
        except (KeyError, TypeError):
            continue  # malformed step → fall through to next rule (and ultimately None);
                      # ApprovalGate is defense-in-depth, not the only validator
    return None
```

`ApprovalGate._classify` (v3.1 §F.2 line 290) becomes a thin call to `classify(step)`.

### §W.2.3 Tests

| Step | Expected action_class |
|---|---|
| `{agent:cloud_azure, tool:powerzure, action:Get-AzureUserInformation}` | `privilege_escalation` |
| `{agent:cloud_azure, tool:scoutsuite, action:scan}` | None |
| `{agent:cloud_azure, tool:microburst, action:Invoke-EnumerateAzureBlobs}` | None |
| `{agent:cloud_azure, tool:microburst, action:Invoke-AzureUploadKeyVaultCert}` | `privilege_escalation` |
| `{agent:cloud_azure, tool:microburst, action:Set-AzureSomething}` | `privilege_escalation` |
| `{agent:cloud_azure, tool:roadrecon, action:gather}` | None |
| `{agent:cloud_azure, tool:roadrecon, action:auth, config:{flags:[pass-policy-bypass]}}` | `privilege_escalation` |
| `{agent:cloud_azure, tool:roadrecon, action:role_grant_user_admin}` | `privilege_escalation` |
| `{agent:web, tool:metasploit, config:{module_path:auxiliary/scanner/http/dir_scanner}}` | None |
| `{agent:web, tool:metasploit, config:{module_path:exploit/multi/http/struts}}` | `privilege_escalation` |
| `{agent:web, tool:nuclei, config:{tags:[cve,critical,rce]}}` | `privilege_escalation` |
| `{agent:web, tool:nuclei, config:{tags:[cve,info]}}` | None |
| `{agent:web, tool:pyrit, action:multi-turn-attack, config:{target_kind:production}}` | `privilege_escalation` |
| `{agent:web, tool:pyrit, action:evaluate, config:{target_kind:synthetic}}` | None |
| `{agent:application, tool:nmap, config:{scripts:[default,safe]}}` | None |
| `{agent:application, tool:nmap, config:{scripts:[intrusive]}}` | `privilege_escalation` |
| any step with `{dry_run: true}` | None |
| malformed `{agent:cloud_azure}` (no tool) | None (no rule raises) |

Plus: integration test where `cloud_azure` target's `allow_priv_esc_simulation=false` → ApprovalGate denies even if grant exists (per §W.1.3 hard-deny rule).

---

## §W.3 CoreDNS — per-session shared container, same Docker network (resolves B-3)

**Decision:** **option (c)** — one CoreDNS container per pentest session, shared across all sub-orchestrators in that session, joined to a session-scoped Docker network. Agent containers join the same network and use `--dns <coredns-ip>` (NOT `127.0.0.1`).

**Rationale vs alternatives:**
- (a) Multi-process container: violates 1-process-per-container Docker norm; supervisord adds complexity; agent images would all need CoreDNS bundled.
- (b) Sidecar in `network_mode: container:<peer>`: forces 1:1 sidecar:agent ratio (CoreDNS instance per agent container); high resource overhead with concurrent subs × tools.
- (c) Per-session shared CoreDNS: 1 CoreDNS per session, regardless of sub/tool count; resolver scope = session = scope_rules union; correct isolation boundary.

**Network model:** session-scoped Docker bridge network with **default external connectivity** (NOT `internal=True`). Scope enforcement layers, in order:
1. **CoreDNS allowlist** (this section): only allowlisted hostnames resolve; everything else returns NXDOMAIN. Agents that hardcode IPs bypass this layer.
2. **EgressMonitor** (v3.1 §B.2 / v2.1 baseline): parses every container log for IP/hostname connections; kills the container on out-of-scope match. Catches IP-based bypass.
3. **AzureScopeValidator** (v3.0 §5.2): adapter-level ARM ID gating for Azure SDK calls.

`internal=True` would defeat the platform: agents need real connectivity to in-scope external hosts (e.g., `*.example.com`, `management.azure.com`). The combined CoreDNS-allowlist + EgressMonitor design is the scope guarantee.

### §W.3.0 `scope_rules_union` (consumed by §W.3.1)

A session may aggregate multiple targets of mixed type. The master computes `scope_rules_union` once per session before `SessionNetworkBackend.setup`:

```python
# app/orchestrator/scope_union.py  (NEW)
def compute_scope_union(targets: list[Target]) -> dict:
    """Aggregate scope_rules across heterogeneous targets for DNS allowlist generation.

    Returns a flat dict consumed only by SessionNetworkBackend; NOT a scope_rules
    schema instance — semantically a "DNS allowlist input".
    """
    domains: set[str] = set()
    ips: set[str] = set()           # informational; CoreDNS only resolves names
    includes_azure: bool = False
    azure_extras: dict = {"key_vaults": set(), "storage_accounts": set()}

    for t in targets:
        rules = t.whitelist_rules     # ORM attribute (per v3.1.4 §V.4)
        if t.target_type == "web":
            domains.update(rules.get("domains", []))
        elif t.target_type == "application":
            ips.update(rules.get("ip_ranges", []))
        elif t.target_type == "cloud_azure":
            includes_azure = True
            for sa in rules.get("allowed_storage_accounts", []):
                azure_extras["storage_accounts"].add(sa)
            for kv in rules.get("allowed_key_vaults", []):
                azure_extras["key_vaults"].add(kv)
        elif t.target_type == "source_code":
            # git host derived from git_url
            host = urlparse(rules["git_url"]).hostname
            if host:
                domains.add(host)
    return {
        "domains": sorted(domains),
        "ips": sorted(ips),
        "includes_azure": includes_azure,
        "azure_storage_accounts": sorted(azure_extras["storage_accounts"]),
        "azure_key_vaults": sorted(azure_extras["key_vaults"]),
    }
```

### §W.3.1 SessionNetworkBackend (corrected)

```python
# app/agents/backends/docker_session.py  (NEW)
class SessionNetworkBackend:
    """Per-session Docker network + CoreDNS instance.

    Lifecycle: created when MasterOrchestrator spawns; destroyed on session terminal.
    Network is NOT internal-only: agents need external connectivity to in-scope hosts.
    Scope enforcement = CoreDNS allowlist (this layer) + EgressMonitor (log parser) +
    AzureScopeValidator (adapter-level).
    """
    def __init__(self, session_id: uuid.UUID, scope_union: dict):
        self._session_id = session_id
        self._network_name = f"osa-sess-{session_id}"
        self._coredns_name = f"osa-dns-{session_id}"
        self._scope = scope_union   # produced by compute_scope_union()

    async def setup(self) -> None:
        # 1. Create network — bridge, NOT internal (agents need allowlisted external access)
        await docker.networks.create(name=self._network_name, driver="bridge")
        # 2. Generate Corefile from scope_union
        corefile = self._render_corefile(self._scope)
        # 3. Launch CoreDNS in network
        self._coredns_container = await docker.containers.run(
            image="coredns/coredns:1.11.1",
            name=self._coredns_name,
            command=["-conf", "/etc/coredns/Corefile"],
            volumes={tempfile_with(corefile): {"bind": "/etc/coredns/Corefile", "mode": "ro"}},
            network=self._network_name,
            detach=True, remove=True,
        )
        info = await self._coredns_container.show()
        self._coredns_ip = info["NetworkSettings"]["Networks"][self._network_name]["IPAddress"]

    def attach_kwargs(self) -> dict:
        return {
            "network": self._network_name,
            "dns": [self._coredns_ip],
            "dns_search": [],
        }

    def _render_corefile(self, scope: dict) -> str:
        """Allowlist Corefile: explicit per-host stanzas forward to upstream;
        catch-all root zone returns NXDOMAIN.

        Wildcard handling: `*.example.com` is expanded into a wildcard zone using
        the `template` plugin matched by regex; underlying upstream resolution
        still proxies the actual query.
        """
        allowed_exact: set[str] = set()
        allowed_wildcards: list[str] = []  # base domain (e.g., "example.com" from "*.example.com")

        for host in scope["domains"]:
            if host.startswith("*."):
                allowed_wildcards.append(host[2:])
            else:
                allowed_exact.add(host)

        if scope["includes_azure"]:
            # Always-allowed Azure control-plane endpoints
            allowed_exact.update({
                "management.azure.com",
                "login.microsoftonline.com",
                "graph.microsoft.com",
            })
            # Per-resource Azure endpoints (still wildcard form because instance is variable)
            for sa in scope["azure_storage_accounts"]:
                allowed_exact.add(f"{sa}.blob.core.windows.net")
                allowed_exact.add(f"{sa}.file.core.windows.net")
            for kv in scope["azure_key_vaults"]:
                allowed_exact.add(f"{kv}.vault.azure.net")

        # Build per-zone stanzas — each forwards to public resolver
        exact_zones = "\n".join(
            f"{host}:53 {{ forward . 1.1.1.1 8.8.8.8 }}"
            for host in sorted(allowed_exact)
        )
        # CoreDNS suffix-zone matching: registering `example.com:53` covers all
        # subdomains AND the apex. Wildcard semantics in §W.1.2 mean `*.example.com`
        # nominally excludes apex, but DNS-layer over-permissiveness here is acceptable
        # since EgressMonitor (per-connection scope check) is the authoritative gate.
        wildcard_zones = "\n".join(
            f"{base}:53 {{ forward . 1.1.1.1 8.8.8.8 }}"
            for base in sorted(allowed_wildcards)
        )
        # Root catch-all → NXDOMAIN for everything else
        catchall = """.:53 {
  log
  errors
  template IN ANY . {
    rcode NXDOMAIN
  }
}"""
        return f"{exact_zones}\n{wildcard_zones}\n{catchall}\n"

    async def teardown(self) -> None:
        try:
            await self._coredns_container.kill()
        except DockerError:
            pass  # already dead
        await docker.networks.get(self._network_name).delete()
```

**Corefile semantics summary:**
- Per-host zones (e.g., `example.com:53 { forward . 1.1.1.1 }`) → real resolution.
- Wildcard zones (e.g., `example.com:53` with `template` so any subdomain matches) → real upstream resolution.
- Root zone `.:53` is the catch-all → returns NXDOMAIN. Because per-host zones have higher specificity, in-scope queries hit those zones first; only out-of-scope queries fall through to `.:53`.

### §W.3.2 Integration with MasterOrchestrator

```python
# In MasterOrchestrator.run()
from app.orchestrator.scope_union import compute_scope_union
self._scope_union = compute_scope_union(self._targets)
self._network = SessionNetworkBackend(self._session_id, self._scope_union)
await self._network.setup()
try:
    await asyncio.gather(*[sub.run() for sub in self._subs])
finally:
    await self._network.teardown()
```

Each `sub_orchestrator` passes `self._network.attach_kwargs()` into `DockerBackend.start(...)` for every adapter container it spawns.

### §W.3.3 Tests (corrected)

- `compute_scope_union` over 3 targets (web + cloud_azure + source_code) → returns expected merged dict.
- `SessionNetworkBackend.setup` creates bridge network + CoreDNS container; tear-down removes both; no orphan after 5 successive sessions.
- **Integration:** spin up SessionNetworkBackend with `{domains: ["example.com", "*.target.test"], includes_azure: false}`. From a busybox container in the same network with `--dns <coredns-ip>`:
  - `dig example.com` → real A record (NOERROR)
  - `dig sub.target.test` → real A record (NOERROR; matched by wildcard zone)
  - `dig evil.example.org` → NXDOMAIN (root catch-all)
  - `curl https://example.com/` → connects (TCP open, allowlisted IP)
  - `curl https://evil.example.org/` → DNS resolution fails (curl error code 6)
- Two concurrent sessions: each gets its own network; resolver in session A cannot be reached from session B (different bridge networks; default Docker isolation).
- Azure target: `dig vault123.vault.azure.net` resolves only when `vault123` is in `allowed_key_vaults`.

### §W.3.4 Spec amendment

**Replaces v3.1 §B.3 entirely.**

> §B.3 DNS-level interception (defense in depth) — see §W.3 (per-session shared CoreDNS in non-internal session network; allowlist-by-zone Corefile; root zone catch-all NXDOMAIN).

---

## §W.4 Paused-sub `plan_version` refresh on wake (resolves B-4)

**Decision:** **option (a)** — on wake, sub-orchestrator refreshes `self._plan_version` from current Blackboard control state before retrying `ApprovalGate.require()`. The approval grant the operator created carries `plan_version` matching the plan **at-time-of-approval**; if a replan happened during the operator's deliberation, the wake-up triggers fresh approval rather than infinite re-pause.

### §W.4.0 DomainAgent ABC addition

**Extends v3.0 §5.4 `DomainAgent(ABC)` with one new method:**

```python
class DomainAgent(ABC):
    # ... existing members ...

    def plan_steps_after_replan(self, snapshot: BlackboardSnapshot) -> list[Step]:
        """Re-derive this agent's step list after a master replan.

        Default implementation calls plan_steps with the original target/context
        plus the latest blackboard snapshot. Agents that derive steps from
        observations (CloudAzureAgent's gather→exploit chain) override this.
        """
        return self.plan_steps(self._target, {**self._context, "snapshot": snapshot})
```

`step` membership compared via `step_hash` (see §W.2.0), NOT raw dict equality, to tolerate key-ordering / whitespace.

### §W.4.1 Replaces v3.1 §H.2 lines 386-394

```python
try:
    await asyncio.wait_for(
        self._approval_event.wait(),
        timeout=settings.approval_wait_timeout_seconds,
    )
    self._approval_event.clear()
    self._approval_pending = None

    # Refresh plan_version: master may have replanned during pause
    snapshot = self._blackboard.snapshot()
    fresh_plan_version = snapshot.control.get("plan_version", self._plan_version)
    if fresh_plan_version != self._plan_version:
        self._plan_version = fresh_plan_version
        new_steps = self._domain_agent.plan_steps_after_replan(snapshot)
        new_step_hashes = {_hash_step(s) for s in new_steps}
        if _hash_step(step) not in new_step_hashes:
            await self._blackboard.sub_append(self._sub_id,
                Event("step_dropped_after_replan", {"original_step_hash": _hash_step(step)}))
            continue  # to next step in for-loop
    # Retry the gate; if plan_version changed, this likely raises ApprovalRequired again
    await self._approval_gate.require(self._session_id, step, self._plan_version)
```

`_hash_step(s)` is the same SHA-256 over `(agent, action, config)` used by `ApprovalGate` (v3.1 §F.2 lines 287-289 + §W.2.0).

**Race window note:** `snapshot.control.get("plan_version")` is read via `Blackboard.snapshot()` — per v3.1.4 §V.1, snapshot is lock-free but writes complete-then-publish. Worst case the sub reads `plan_version_n` while master is mid-write to `plan_version_{n+1}`; the next supervisor tick will produce another `awaiting_approval` event if the new plan again requires approval — converging within at most 2 wake-cycles per replan.

### §W.4.2 Re-pause budget

To prevent worst-case oscillation (master replans every approval), add a per-step re-pause counter:

```python
self._step_pause_count: dict[str, int] = defaultdict(int)
MAX_REPAUSES_PER_STEP = 3

# inside the except ApprovalRequired branch:
sh = _hash_step(step)
self._step_pause_count[sh] += 1
if self._step_pause_count[sh] > MAX_REPAUSES_PER_STEP:
    await self._blackboard.sub_append(self._sub_id,
        Event("step_abandoned_too_many_replans", {"step_hash": sh, "count": self._step_pause_count[sh]}))
    continue
```

### §W.4.3 Tests

- Approval arrives, no replan happened → step executes (regression test, existing §H.6 row).
- Approval arrives, master replanned during pause but `_hash_step(step)` still in `plan_steps_after_replan` set → re-pause once → operator re-approves under new plan_version → step executes.
- Approval arrives, master replanned and `_hash_step(step)` NOT in new set → `step_dropped_after_replan` event; sub continues.
- Pathological: master replans 4× in a row → step abandoned at re-pause #4; `step_abandoned_too_many_replans` event; sub continues.
- ABC contract: every concrete DomainAgent (Application/Web/CloudAzure/SourceCode) implements or inherits `plan_steps_after_replan` and returns a `list[Step]` (TypedDict).

---

## §W.5 ApprovalGrant 409 race (resolves B-5)

**Replaces v3.1 §H.5 first bullet:**

> POST `/api/v1/sessions/{id}/approvals` body: `{"step_hash": ..., "plan_version": ...}`. Inserts `approval_grants` row, then calls `OrchestratorRegistry.notify_approval(...)`. **On `IntegrityError` from the UNIQUE `(session_id, step_hash, plan_version)` constraint, the handler MUST catch and return `409 Conflict` with body `{"reason": "already_approved", "session_id": "...", "step_hash": "...", "plan_version": ...}`.** The first POST to land wins; the second receives 409. Both operators see the latest grant via the project WS feed.

### §W.5.1 Handler

```python
# app/api/v1/approvals.py
@router.post("/sessions/{session_id}/approvals", status_code=201)
async def create_approval(session_id: uuid.UUID, body: ApprovalCreate, user: User = Depends(...)):
    grant = ApprovalGrant(
        session_id=session_id,
        step_hash=body.step_hash,
        plan_version=body.plan_version,
        action_class=body.action_class,
        granted_by=user.id,
    )
    try:
        db.add(grant)
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "reason": "already_approved",
                "session_id": str(session_id),
                "step_hash": body.step_hash,
                "plan_version": body.plan_version,
            },
        )
    OrchestratorRegistry.notify_approval(session_id, _resolve_sub_id(session_id, body.step_hash), body.step_hash)
    return ApprovalRead.from_orm(grant)
```

`_resolve_sub_id(session_id, step_hash)` looks up the `awaiting_approval:*` blackboard control key whose value's `step_hash` matches; returns the matching `sub_id`. If none found (operator approved a step no sub is waiting on, or sub already timed out), `notify_approval` is a no-op. Signature `(session_id, sub_id, step_hash)` matches v3.1 §H.5 line 418.

### §W.5.2 Tests

- Two parallel POSTs with same body → first 201, second 409 with `reason: already_approved`.
- After 409, `OrchestratorRegistry.notify_approval` is **not** called for the duplicate (otherwise paused sub wakes twice → benign but spec says: only the winning POST notifies).
- 409 response body conforms to documented schema (asserted via OpenAPI conformance test).

---

## §W.6 Per-target credential M:N binding (resolves B-6)

**Decision:** **option (a)** — introduce `target_credentials` join table. Migration 004 adds it alongside `credentials`. A target may have 0..N credentials; a credential may bind to 0..N targets within its project (cross-project binding forbidden).

### §W.6.1 Schema (replaces v3.0 §5.1 Migration 004 `credentials` block)

> **Note on `approval_grants`:** v3.0 §5.1 Migration 004 originally co-located `credentials` and `approval_grants` table creation. The `approval_grants` schema is now owned by **v3.1 §F.1** (revised columns + index). v3.1.5 §W.6.1 below redefines ONLY the credentials portion; `approval_grants` creation moves into Migration 004 alongside `credentials` and `target_credentials` per v3.1 §F.1 SQL.

```python
# 004_credentials.py
op.create_table(
    "credentials",
    sa.Column("id", postgresql.UUID, primary_key=True),
    sa.Column("project_id", postgresql.UUID, sa.ForeignKey("projects.id"), nullable=False),
    sa.Column("name", sa.String(128), nullable=False),
    sa.Column("kind", sa.String(32), nullable=False),  # azure_sp | github_pat
    sa.Column("encrypted_blob", sa.LargeBinary, nullable=False),
    sa.Column("nonce", sa.LargeBinary, nullable=False),
    sa.Column("created_by", postgresql.UUID, sa.ForeignKey("users.id"), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    sa.UniqueConstraint("project_id", "name", name="uq_credentials_project_name"),
)
op.create_table(
    "target_credentials",
    sa.Column("target_id", postgresql.UUID, sa.ForeignKey("targets.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("credential_id", postgresql.UUID, sa.ForeignKey("credentials.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("bound_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    sa.Column("bound_by", postgresql.UUID, sa.ForeignKey("users.id"), nullable=False),
)
op.create_index("idx_tc_credential", "target_credentials", ["credential_id"])
```

**Removed from `credentials`:** the prior `target_id` column (was 1:N). Project-wide credentials simply have no `target_credentials` rows; adapter code must check both project-wide pool and target-bound pool.

### §W.6.2 Cross-project binding constraint

Enforced at API layer (FK alone allows cross-project binding because both `targets.project_id` and `credentials.project_id` are independent):

```python
# app/api/v1/credentials.py
@router.post("/{credential_id}/bindings/{target_id}")
async def bind(credential_id: uuid.UUID, target_id: uuid.UUID, user: User = Depends(require_admin)):
    cred = await db.get(Credential, credential_id)
    target = await db.get(Target, target_id)
    if cred.project_id != target.project_id:
        raise HTTPException(400, "credential and target must belong to same project")
    # ... insert target_credentials row
```

Plus a CHECK trigger in migration as belt-and-suspenders:

```sql
CREATE OR REPLACE FUNCTION check_cred_target_same_project() RETURNS TRIGGER AS $$
BEGIN
    IF (SELECT project_id FROM credentials WHERE id = NEW.credential_id) !=
       (SELECT project_id FROM targets WHERE id = NEW.target_id) THEN
        RAISE EXCEPTION 'credential and target must belong to same project';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER trg_check_cred_target_same_project
    BEFORE INSERT OR UPDATE ON target_credentials
    FOR EACH ROW EXECUTE FUNCTION check_cred_target_same_project();
```

### §W.6.3 Adapter resolution order

```python
# app/services/credentials.py — resolve_credentials_for(target_id, kind) -> list[Credential]
async def resolve_credentials_for(target_id: uuid.UUID, kind: str | None = None) -> list[Credential]:
    target = await db.get(Target, target_id)
    # 1. Target-bound credentials
    bound = await db.execute(
        select(Credential).join(TargetCredential).where(
            TargetCredential.target_id == target_id,
            Credential.revoked_at.is_(None),
            *( [Credential.kind == kind] if kind else [] ),
        )
    )
    bound_list = list(bound.scalars())
    # 2. Project-wide (no target_credentials row at all)
    project_wide = await db.execute(
        select(Credential).where(
            Credential.project_id == target.project_id,
            Credential.revoked_at.is_(None),
            ~Credential.id.in_(select(TargetCredential.credential_id)),
            *( [Credential.kind == kind] if kind else [] ),
        )
    )
    return bound_list + list(project_wide.scalars())
```

Adapters request specific `kind` (`"azure_sp"` for CloudAzure, `"github_pat"` for SourceCode); resolver returns target-bound first, project-wide as fallback.

### §W.6.4 UI implication (cross-ref §5.7)

Update v3.0 §5.7 component list — `pages/CredentialManager.tsx` row gets a behavior addendum:
> **CredentialManager** (admin) — credentials CRUD **+ M:N target binding**: each credential row exposes a "Bound targets" multi-select listing all targets in the same project. Empty selection = project-wide (fallback for any target). Cross-project binding is impossible (target list filtered to credential's project).

**"Project-wide" semantics:** a credential is project-wide if and only if it has **zero** rows in `target_credentials`. As soon as the operator binds it to even one target, it loses fallback role for *other* targets in the same project. Document this in `docs/credentials.md` and surface a UI tooltip on the bind multi-select.

Schema migration: project re-parenting of targets/credentials is **not supported in MVP** — the BEFORE-INSERT/UPDATE trigger in §W.6.2 protects against same-row mutations but cannot detect a target moving projects via direct SQL. Documented assumption: project_id is immutable after row creation.

### §W.6.5 Tests

- Bind 2 credentials to one target → `resolve_credentials_for(target_id)` returns both.
- Bind 1 credential to 2 targets → both `resolve` calls return it.
- Cross-project bind attempt → 400 from API; trigger raises if FK directly attempted.
- Project-wide credential (no bindings) → returned for any target in same project.
- Revoked credential → excluded from resolver.

---

## §W.7 Updated Acceptance Criteria

After §W applied, ACs from v3.0 §7 + v3.1 §N + v3.1.4 §V remain. Add:

- **AC 23 (scope schema):** POST `/api/v1/targets` with malformed scope_rules returns 400 with field-level error list. (§W.1.7)
- **AC 24 (priv-esc gating):** Plan step `(cloud_azure, powerzure, *)` always requires approval; plan step `(cloud_azure, scoutsuite, scan)` never requires approval. Classifier rejects malformed steps gracefully. (§W.2.3)
- **AC 25 (DNS scope round-trip):** Agent container in session network: (a) `dig` allowlisted host returns real A record, (b) `curl` allowlisted host succeeds (TCP open), (c) `dig` non-allowlisted host returns NXDOMAIN. (§W.3.3)
- **AC 26 (replan-during-pause):** Master replan during pause that drops the awaited step → sub records `step_dropped_after_replan` and proceeds. Every concrete DomainAgent implements `plan_steps_after_replan`. (§W.4.3)
- **AC 27 (concurrent approval):** Two parallel POST `/approvals` with identical body → 1× 201, 1× 409 with `reason: already_approved`. Notify_approval invoked exactly once with `(session_id, sub_id, step_hash)`. (§W.5.2)
- **AC 28 (M:N credentials):** One credential bound to 2 targets resolves for both; cross-project binding rejected with 400 by API and by SQL trigger. CredentialManager UI exposes bind multi-select scoped to same project. (§W.6.5)
- **AC 29 (target_type ENUM consistency):** `target_type` column accepts only `('application','web','cloud_azure','source_code')`; `web_application` is rejected by ENUM. CI grep confirms zero residual `web_application` references in code or migrations. (§W.1.0)

---

## §W.8 Documentation updates required

- `docs/scope-rules.md` — new file. Per-target_type schema reference + worked examples + wildcard semantics. Generated from §W.1 schemas.
- `docs/approval-classification.md` — new file. The §W.2.1 matrix as canonical reference for security reviewers.
- `docs/dns-isolation.md` — new file. §W.3 architecture + troubleshooting (CoreDNS Corefile inspection commands).
- `docs/credentials.md` (existing per v3.0 §6) — extend with M:N binding model + UI screenshot reference.
- `docs/api-migration.md` (created in v3.1.4 §V.10) — append §W.5 409 contract + §W.6 endpoint additions.
- `CHANGELOG.md` — single v3.1.5 entry summarizing all of §W.

---

## §W.9 What this patch does NOT cover

- §C MED-LOW items (11) — to be resolved during implementation; tracked as todos in session SQL.
- §D LOW (4) — opportunistic.
- §E pre-mortem additions (3) — to be folded into implementation phase pre-mortems.

After v3.1.5 is approved, implementation may begin at Phase 5.1 (Migration 003 with consolidated column list per v3.1.4 §V.6).

---

## §W.10 Recommended next step

1. Run **Critic** agent on v3.1.5 (regression-free check on §W resolutions).
2. If APPROVE → begin implementation Phase 5.1.
3. If defects → patch in v3.1.5-rev2.

---

## Iteration Changelog
- **v3.1.5-rev3** (2026-05-10): Critic minor edit — §W.3.1 wildcard zone simplified to `forward .` only (removed `template` clause that would have shadowed forward via NOERROR-empty). DNS-layer apex over-permissiveness documented; EgressMonitor remains authoritative scope gate.
- **v3.1.5-rev2** (2026-05-10): Critic edits applied — §W.1.0 ENUM canonicalization (`web` not `web_application`); §W.1.5 added `application` schema (was reserved); §W.1.6 explicit `referencing.Registry` + custom `FormatChecker` for `ipv4-cidr-or-host`; §W.2.0 canonical `Step` TypedDict; §W.2 split `application_web` into `application` + `web`; §W.2.2 ROADrecon precedence fix + Pyrit production/synthetic distinction + Nmap intrusive NSE rule + try/except hardening; §W.3 corrected Corefile (no `internal=True`, allowlist-by-zone with NXDOMAIN catch-all, real upstream forward); §W.3.0 added `compute_scope_union`; §W.4.0 declared `plan_steps_after_replan` ABC method; §W.4.1 step membership via `_hash_step`; §W.5.1 3-arg `notify_approval` signature with `_resolve_sub_id`; §W.6.1 noted `approval_grants` ownership now in §F.1; §W.6.4 explicit project-wide semantics + immutability assumption; §W.7 added AC 29 for ENUM consistency; v3.1.4 §V.6 default corrected from `'web_application'` → `'web'`.
- **v3.1.5** (2026-05-10): Iteration 5 ambiguity-resolution patch. §W.1–§W.9.
- v3.1.4-rev1 (2026-05-10): Iteration 4 + critic edits. §V.1–§V.11.
- v3.1.3 (2026-05-10): Iteration 3 — §Q–§T.
- v3.1 (2026-05-10): Iteration 2 — §A–§P.
- v3.0 (2026-05-10): Planner draft.
