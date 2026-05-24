# PentAGI ↔ OSA Reference Matrix (v4.0 port)

**Purpose:** Detailed pattern-by-pattern comparison between PentAGI (`https://github.com/vxcontrol/pentagi`, default branch `master`) and OSA v2.1+v3.2.1 baseline. Drives the v4.0 port plan at `.omc/plans/osa-pentagi-port-autopilot-v4.0.md`. Phase implementers should use this doc for 1:1 lookups (PentAGI source file → OSA target path → adoption decision).

**Source vintage:** PentAGI tree examined 2026-05-16 via WebFetch. OSA baseline at this repo's `main` branch, post-v3.2.1 consensus.

**Authoring rule:** Every row in every table cites either a PentAGI source file (`pentagi/<path>`) or an OSA source file (`backend/<path>` or `frontend/<path>`). No speculation; if a cell is empty, write "N/A — not visible from public repo".

---

## §1. UI Patterns Mapping

PentAGI uses a horizontal 2-pane resizable shell on `/flows/:id` with 6 right-pane tabs + 3 left-pane tabs (9 tabs total on desktop, folded to 6 on mobile). OSA v1 adopts the shell + 3 right + 3 left = 6 tabs total. The 3 PentAGI right-pane tabs not adopted (Searches / Vector Store / Screenshots) are explicit v3.4 backlog.

| Pattern | PentAGI source | OSA v1 target | Adoption decision | Rationale |
|---------|---------------|---------------|-------------------|-----------|
| Horizontal `ResizablePanelGroup` 2-pane shell | `pentagi/frontend/src/pages/flows/flow.tsx` | `frontend/src/pages/FlowPage.tsx` (NEW in P3-main) | **Adopt** | Single most-leverage UI pattern; locks operator mental model: left = conversation/overview, right = evidence. |
| `react-resizable-panels` lib | `pentagi/frontend/package.json` dep | `frontend/package.json` add `react-resizable-panels^2.1.0` | **Adopt** | 2.7KB gzipped, zero ecosystem risk; no React 18 issues. |
| Left pane: Automation / Assistant / Dashboard tabs (3) | `pentagi/frontend/src/features/flows/flow-central-tabs.tsx` | `frontend/src/components/flow/LeftPane.tsx` (NEW) | **Adopt 3 tabs**; Automation reuses `WorkflowChat`, Dashboard reuses `InteractionDashboard`, Assistant = placeholder ("v3.4") | Assistant sidechannel agent is v3.4 (not in Minimal 6 roles). Tab itself ships for shell coherence. |
| Right pane: Terminal / Tasks / Agents tabs | `pentagi/frontend/src/features/flows/flow-tabs.tsx` lines defining Terminal/Tasks/Agents | `frontend/src/components/flow/RightPane.tsx` + 3 tab files | **Adopt** | Spec line 119–123: "사용자 prompt: terminal, Tasks, Agents 등 UI" — explicit ask. |
| Right pane: Searches tab | `pentagi/frontend/src/features/flows/tools/` | — | **Reject for v1, defer v3.4** | No `Searcher` role in Minimal 6 (Round 6 simplifier). Backing data source (web search tools) absent in OSA. |
| Right pane: Vector Store tab | `pentagi/frontend/src/features/flows/vector-stores/` | — | **Reject for v1, defer v3.4** | Memorist Thin v1 has 1 search tool (`search_in_memory`); UI surface for vector inspection is post-v1 polish, not core feature. |
| Right pane: Screenshots tab | `pentagi/frontend/src/features/flows/screenshots/` | — | **Reject for v1, defer v3.4** | Requires browser tool + `vxcontrol/scraper` container service; both v3.4+. |
| xterm.js + 4 addons (fit, search, web-links, webgl) | `pentagi/frontend/package.json` `@xterm/xterm ^5.x` + 4 addon entries | `frontend/package.json` `@xterm/xterm^5.5.0` + 4 addons | **Adopt** | Standard terminal emulation; addons cover OSA's needs (resize, ctrl-f, autolink, GPU-accelerated render). |
| Monaco editor for artifact diff | `pentagi/frontend/package.json` `@monaco-editor/react` | — | **Reject for v1, defer v3.4** | OSA v1 has no diff-viewer use case; defer until Coder role lands. |
| Apollo Client + graphql-ws for realtime | `pentagi/frontend/package.json` `@apollo/client@3.13`, `graphql-ws@6.x` | — | **Reject; use WebSocket-evolved** (ADR-001) | Existing `backend/app/api/v1/ws.py` + `event_bus` is reused with `topic` kwarg. GraphQL = 500+ LOC + 2 new backend deps. |
| Toast notifications (`sonner`) | `pentagi/frontend/package.json` `sonner` | — | **Optional v3.4** | Radix's `Toast` primitive already available; not blocking. |
| Drawer primitive (`vaul`) | `pentagi/frontend/package.json` `vaul` | — | **Reject v1** | Not needed for shell + 3 tabs. |
| react-hook-form + zod for new-flow form | `pentagi/frontend/src/features/flows/flow-form.tsx` | Reuse existing `PentestWorkflow.tsx` form, evolved to /flow entry | **Partial adopt** | OSA's existing WorkflowChat already validates; keep current shape, add new `/flow/new` route in P3-main. |
| `recharts` for dashboard charts | `pentagi/frontend/package.json` `recharts` | Already in `frontend/package.json` (^2.13) | **N/A — already present** | OSA Dashboard already uses recharts. |
| @react-pdf/renderer + html2pdf.js for report export | `pentagi/frontend/package.json` | Existing `backend/app/reports/generator.py` + WeasyPrint | **Reject — different stack** | OSA generates PDF server-side; PentAGI does client-side. Keep OSA's server-side path. |

**Layout decision:** `flow.tsx` shell is **always-mounted** on `/flow/:id` (no conditional render). Default split = 50/50, min 30% each pane, `100dvh-3rem` height (subtract sidebar). Mobile (`< md`) collapses to single card with all 9 tabs folded into one strip (OSA: collapses to 6 tabs).

---

## §2. 14-Role Inventory

PentAGI's role catalog lives in `pentagi/backend/pkg/providers/performers.go` (role enum) + `pentagi/backend/pkg/providers/performer.go` (engine). All roles execute through one generic `Performer.run()` function, parameterized by `MsgchainType` and a `pconfig.ProviderOptionsType` binding. There are no per-role classes; roles are differentiated by their system prompts + tool palettes + iteration caps.

OSA v1 adopts the Performer pattern but ships only the 6 highest-leverage roles. The other 8 are explicit v3.4+ backlog.

| # | Role | PentAGI source | OSA target | v1 vs v3.4+ | Tool palette (OSA) | Max iter | Notes |
|---|------|---------------|------------|-------------|---------------------|----------|-------|
| 1 | **PrimaryAgent** | `MsgchainTypeAgent` in `performer.go` | — | **v3.4+** | top-level autonomous orchestrator | 100 | Folded into Generator+Pentester for v1; revisit if multi-flow concurrency needs primary controller. |
| 2 | **Assistant** | `MsgchainTypeAssistant`, `assistant.go` | — | **v3.4+** | side-channel chat (operator injects mid-flow) | 100 | Left-pane Assistant tab ships as placeholder; backend role absent in v1. |
| 3 | **Generator** | `MsgchainTypeGenerator` | `backend/app/orchestrator/roles/generator.py` (NEW P2a) | **v1** | `ask`, `done`, `memorist.search_in_memory` | 20 | Decomposes user prompt into SubTask list + ambiguity score envelope. **Reuses** `workflow_service.CHAT_SYSTEM_PROMPT`. |
| 4 | **Refiner** | `MsgchainTypeRefiner` | — | **v3.4+** | rewrites SubTask list mid-flight | 20 | Generator handles refinement inline in v1 (single role serves plan + refine, per Round 6 Minimal 6 decision). |
| 5 | **Planner** | (beta in PentAGI) | — | **v3.4+** | produces 3–7 actionable steps before specialist runs | 20 | Generator's draft_plan covers this in v1; granular per-subtask planning deferred. |
| 6 | **Enricher** | `MsgchainTypeEnricher` | — | **v3.4+** | adds RAG context to Planner's steps | 20 | Memorist auto-call (P4) directly enriches Pentester context; explicit Enricher role redundant in v1. |
| 7 | **Pentester** | `MsgchainTypePentester` | `backend/app/orchestrator/roles/pentester.py` (NEW P2a) | **v1** | `palette_for_domain(session.domain_tags)` from `registry.py`, plus `ask`, `done`, `memorist.search_in_memory` | 100 | **Core executor.** Emits structured tool calls per ADR-005. Tool palette = the 11 existing AgentAdapters filtered by domain. |
| 8 | **Coder** | `MsgchainTypeCoder` | — | **v3.4+** | `terminal` raw shell + `file` r/w + `memorist.search_code` | 100 | Needs `terminal` raw-shell tool + safety re-validation ADR (deferred). Use case: write exploit snippets, modify configs in sandbox. |
| 9 | **Installer** | `MsgchainTypeInstaller` | — | **v3.4+** | `terminal` raw shell + `file` r/w | 100 | Container setup, tool install inside sandbox. Same blocker as Coder. |
| 10 | **Searcher** | `MsgchainTypeSearcher` | — | **v3.4+** | google, duckduckgo, tavily, perplexity, searxng, sploitus, browser | 20 | OSA has no web search tools yet; adopting requires 7+ new tool integrations. |
| 11 | **Memorist** | `MsgchainTypeMemorist` | `backend/app/orchestrator/roles/memorist.py` (NEW P2a) | **v1** | `search_in_memory` only | 20 | Thin v1: 1 search tool. v3.4: `search_guide`, `search_answer`, `search_code`, `graphiti_search`. |
| 12 | **Adviser** | `MsgchainTypeAdviser` | `backend/app/orchestrator/roles/adviser.py` (NEW P2a) | **v1** | invoked by Performer (not by another role) when ExecutionMonitor trips | n/a (one-shot) | Trigger: same tool ≥ 5 calls OR total tool calls ≥ 10. Injects loop-break message. |
| 13 | **Mentor** | not in performers.go enum but referenced | — | **v3.4+** | invoked when executor needs higher-level guidance | n/a | Subsumed by Adviser in v1. |
| 14 | **Reflector** | `MsgchainTypeReflector` | `backend/app/orchestrator/roles/reflector.py` (NEW P2a) | **v1** | wraps every Role.run() try/except | n/a (wrapper) | 3 retries, exponential backoff 200ms/1s/5s — reuses `ModelClient.send()` retry policy. |
| 15 | **CallerReflector** | variant of Reflector | merged into Reflector | **v1** | same | n/a | Single class covers both PentAGI variants. |
| 16 | **Reporter** | `MsgchainTypeReporter` | `backend/app/orchestrator/roles/reporter.py` (NEW P2a) | **v1** | invokes `backend/app/reports/generator.py` ReportGenerator | 20 | Minimal v1; no markdown re-formatting. |

**v1 inventory (6 roles):** Generator, Pentester, Memorist, Adviser, Reflector, Reporter.
**v3.4+ backlog (8 roles):** PrimaryAgent, Assistant, Refiner, Planner, Enricher, Coder, Installer, Searcher (Mentor merged into Adviser).

**Iteration caps (hard-coded in OSA per ADR-003):**
```python
# backend/app/orchestrator/performer.py (NEW P1 skeleton, populated P2a)
PERFORMER_MAX_ITER = 64            # global per-session
MAX_TOOL_CALLS_GENERAL = 100       # Pentester
MAX_TOOL_CALLS_LIMITED = 20        # Generator, Memorist, Reporter
MAX_RETRIES_REFLECTOR = 3
MAX_RETRIES_TOOL_CALL = 3
DELAY_BETWEEN_RETRIES = [0.2, 1.0, 5.0]  # seconds, exponential
ADVISER_TRIGGER_SAME_TOOL = 5
ADVISER_TRIGGER_TOTAL_TOOL = 10
```

---

## §3. Tool Catalog Comparison

PentAGI's tool registry (`pentagi/backend/pkg/tools/registry.go`) exposes ~34 tools. OSA's adapter registry (`backend/app/agents/registry.py`) exposes 11 tools (the existing AgentAdapters). Under ADR-005's OSA-strong hybrid contract, the Pentester role emits structured tool calls that map 1:1 to the existing AgentAdapter slugs — preserving tier-gating, allowlist, egress-monitor, and kill-switch.

| Tool category | PentAGI tools (sample) | OSA v1 equivalent | Adoption | Notes |
|---------------|------------------------|--------------------|----------|-------|
| **Barrier (workflow control)** | `done`, `ask` | `done`, `ask` (NEW in P2a/P4) | **Adopt** | `ask` is core to ambiguity loop (P4); `done` finalizes session → triggers Reporter. |
| **Delegation (agent-as-tool)** | `pentester`, `coder`, `installer`, `memorist`, `search`, `advice`, `maintenance` | `pentester`, `memorist`, `advice` (NEW in P2a) | **Partial** | Coder/Installer/Searcher = v3.4. Maintenance subsumed by Reflector (wrapper, not callable). |
| **Execution primitive: terminal raw shell** | `terminal` (LLM emits raw shell → `docker exec` via `ContainerExecCreate`) | — | **REJECT for v1** | OSA-strong hybrid: LLM emits **structured** tool calls (`{agent: 'nuclei', action: 'scan', config: {…}}`), NOT raw shell. Tier-gating + allowlist enforcement requires structured input. Raw `terminal` tool surfaces only when Coder/Installer ship (v3.4) with separate safety ADR. |
| **Execution primitive: file r/w** | `file` (TAR copy in/out of container) | — | **REJECT for v1** | No v1 role needs filesystem access inside sandbox. AgentAdapters already mount results via stdout JSON. |
| **OSA-specific: AgentAdapter slugs (11)** | N/A (PentAGI has no per-tool adapter) | `nmap`, `nuclei`, `metasploit`, `pyrit`, `passive_recon`, `subfinder`, `dnsx`, `httpx`, `cloudenum`, `wappalyzer`, `knowledge_loader` | **OSA preserves all 11** | Tier-gated (`passive_no_target_contact` / `passive_low_touch` / `active_recon` / `active_exploit`). Pentester palette = `palette_for_domain(domain_tags)`. |
| **Web intel** | `browser` (via vxcontrol/scraper), `google`, `duckduckgo`, `tavily`, `traversaal`, `perplexity`, `searxng`, `sploitus` | — | **REJECT for v1** | All require new tool integrations + Searcher role + new sandbox container. Defer to v3.4. |
| **Memory: vector queries** | `search_in_memory`, `search_guide`, `search_answer`, `search_code` | `search_in_memory` only | **1 of 4 adopt** | Thin v1 RAG (Round 2). Other 3 deferred. |
| **Memory: graph queries** | `graphiti_search` (Neo4j+Graphiti) | — | **REJECT** | Optional stack in PentAGI; OSA doesn't need it for Thin v1. |
| **Result storage** | per-agent `*_result` tools | existing `AgentExecution` rows in DB (write by `PlanExecutor`) | **OSA preserves** | No new tool needed; results persisted as v2.1. |

**ADR-005 envelope (Pentester structured tool call shape):**

```jsonc
{
  "name": "<tool_slug>",        // e.g. "nuclei", must be in list_agent_types()
  "input": {
    "intent": "<intent_slug>",  // e.g. "web_scan", must be in INTENT_VOCABULARY
    "config": {                  // tool-specific; passed to AgentAdapter.execute(target, config)
      "targets": ["…"],
      "templates": ["cves/2024/"],
      "rate": 100
    }
  }
}
```

Dispatch path (Performer._dispatch_tool):
```
1. validate tool_slug ∈ list_agent_types()    [registry.py]
2. validate intent_slug ∈ INTENT_VOCABULARY   [intent_vocabulary.py:25 specs]
3. resolve adapter ← get_adapter(tool_slug)
4. resolve target ← session.target
5. WhitelistValidator.validate(target, config)  [whitelist.py]
6. filter_plan_steps(step, adapter.tier)        [risk_filter.py]
7. exploit_allowlist.check(adapter, config)     [exploit_allowlist.py]
8. EgressMonitor.scope_egress(adapter)          [egress_monitor.py]
9. result ← adapter.execute(target, config)      [agents/<name>.py]
10. persist AgentExecution row                   [models/session.py]
11. event_bus.publish(session_id, result, topic="session")  [events.py]
12. KillSwitch.check_active(session)             [kill_switch.py]
```

Every step survives v3.2.1. The 6 roles add a layer **above** this dispatch, not parallel to it.

---

## §4. GraphQL Subscription → OSA WebSocket Topic Mapping

PentAGI uses GraphQL subscriptions over `graphql-ws` (`pentagi/backend/pkg/graph/schema.graphqls`). OSA evolves the existing WebSocket `event_bus` with a `topic` kwarg (ADR-001). The 1:1 publisher → topic → UI panel mapping is preserved.

| PentAGI subscription | OSA topic string (in `event_bus.publish(session_id, event, topic="…")`) | UI panel that subscribes |
|----------------------|--------------------------------------------------------------------------|--------------------------|
| `terminalLogAdded` | `"terminal"` | Right-pane Terminal tab |
| `agentLogAdded` | `"agents"` | Right-pane Agents tab |
| `taskCreated` | `"tasks"` (sub-event: `event.type="task_created"`) | Right-pane Tasks tab |
| `taskUpdated` | `"tasks"` (sub-event: `event.type="task_updated"`) | Right-pane Tasks tab |
| `messageLogAdded` | `"automation"` (sub-event: `event.type="message_added"`) | Left-pane Automation tab |
| `messageLogUpdated` | `"automation"` (sub-event: `event.type="message_updated"`) | Left-pane Automation tab |
| `assistantLogAdded` | — (v3.4) | Left-pane Assistant tab (placeholder in v1) |
| `assistantLogUpdated` | — (v3.4) | Left-pane Assistant tab |
| `searchLogAdded` | — (v3.4) | Right-pane Searches tab (not in v1) |
| `vectorStoreLogAdded` | — (v3.4) | Right-pane Vector Store tab (not in v1) |
| `screenshotAdded` | — (v3.4) | Right-pane Screenshots tab (not in v1) |
| `flowCreated` / `flowUpdated` / `flowDeleted` | `"session"` (default, sub-event `event.type="session_updated"`) | Sidebar list (existing v2.1 behavior unchanged) |
| `assistantCreated` / `assistantUpdated` / `assistantDeleted` | — (v3.4) | — |
| `providerCreated` / `providerUpdated` / `providerDeleted` | — (v3.4) | — (OSA single Anthropic provider) |
| `apiTokenCreated` / `apiTokenUpdated` / `apiTokenDeleted` | — | Settings page (legacy `/admin` route, not in /flow shell) |
| `settingsUserUpdated` | — | Legacy Admin page |
| `flowTemplateCreated` / `flowTemplateUpdated` / `flowTemplateDeleted` | — | Legacy Workflows page (preserved in sidebar) |

**Per-panel subscription contract:** each UI panel opens one WS connection with one topic:
- Terminal tab → `GET /api/v1/ws/sessions/{id}?topics=terminal`
- Tasks tab → `GET /api/v1/ws/sessions/{id}?topics=tasks`
- Agents tab → `GET /api/v1/ws/sessions/{id}?topics=agents`
- Automation tab → `GET /api/v1/ws/sessions/{id}?topics=automation`
- Sidebar (legacy) → `GET /api/v1/ws/sessions/{id}` (no topic kwarg → defaults to `"session"`)

The frontend `useTopicWebSocket(sessionId, topic)` hook (≤60 LOC) replaces the monolithic `useWebSocket` in P3-spike.

**ADR-001 quantitative thresholds for substrate lock (measured by P3-spike `test_eventbus_topics.py`):**
1. p99 event-to-client latency ≤ 100ms @ 60 events/sec × 3 topics × 10 sessions
2. `asyncio.QueueFull` drop rate < 0.1% under same load
3. No subscriber-list memory leak after disconnect

If any miss → fall back to GraphQL subscriptions (Strawberry + graphql-ws + Apollo Client), documented in `.omc/research/adr-001-fallback-graphql.md`. Fall-back path is **~3 PRs of incremental scope** on top of P3-main.

---

## §5. DB Schema Comparison

PentAGI uses PostgreSQL + pgvector single store with ~25 migrations in `pentagi/backend/migrations/sql/` (2024-10 through 2026-03). OSA uses PostgreSQL with 4 migrations (001 initial → 004 workflows) + adds 2 new (005 pgvector, 006 msgchains) in P1.

| Concern | PentAGI table(s) | OSA table(s) | Disposition | Note |
|---------|-------------------|--------------|-------------|------|
| Flow/session entity | `flows`, `flow_templates` | `pentest_sessions`, `workflows` | **OSA preserves**; PentAGI's `flow_templates` ≈ OSA's `workflows` (DAG editor) | No schema change. |
| Tasks/SubTasks | `tasks`, `subtasks` | `pentest_sessions.draft_plan_json` (JSONB list) + `pentest_sessions.plan_json` (post-approval) | **OSA absorbs into JSONB; no separate tables in v1** | Round 6 simplifier: flat SubTask list lives inside session row; v3.4 may externalize if SubTask graph editor needed. |
| Message chain (per-role transcript) | `msgchains` (typed by `MsgchainType` enum) | `msgchains` (NEW in P1, table from `006_msgchains.py`) | **OSA adopts** | Schema: `id UUID PK, pentest_session_id UUID FK, role_name VARCHAR(32), messages_json JSONB, started_at TIMESTAMPTZ, ended_at TIMESTAMPTZ, status VARCHAR(16), retries INT DEFAULT 0`. Index `(pentest_session_id, started_at)`. |
| Per-stream logs (terminal/agent/search/vector/screenshot/assistant) | `termlogs`, `agentlogs`, `searchlogs`, `vectorstorelogs`, `screenshots`, `assistant_logs`, plus `alogs/aslogs/slogs` controllers | — (NOT adopted) | **REJECT** | OSA uses `AgentExecution` (existing) + `WorkflowMessage` (existing) + new `msgchains` to cover all streams. Per-stream tables add 8 new tables; OSA's 3 cover the v1 scope. |
| Vector embeddings | `pgvector` columns inside `msglogs.embedding`, `subtasks.embedding` | `memory_entries.embedding vector(384)` (NEW in P1, table from `006_msgchains.py`) | **OSA adopts pgvector + separate table** | Schema: `id UUID PK, domain_tag VARCHAR(32), source_yaml_path TEXT, name TEXT, description TEXT, embedding vector(384), metadata_json JSONB, created_at TIMESTAMPTZ`. hnsw index per ADR-002. |
| User/Auth | `users`, `api_tokens` | `users`, plus JWT-based auth (no API token table) | **OSA preserves** | PentAGI multi-tenant per-user-token; OSA single-team JWT (locked v3.2.1). |
| Providers (multi-LLM) | `providers` table | — | **REJECT** | OSA Anthropic-only (locked v3.2.1). |
| Settings/preferences | `settings`, `user_preferences` | (config in `.env` + DB-less settings) | **OSA preserves** | OSA settings via pydantic-settings + env file. |
| Tracking/supervision | `agent_supervision` columns (added 2026-03 migration) | (audit_log table existing) | **OSA preserves audit_log** | No new schema; audit columns added to `audit_logs` if Performer needs richer events. |

**OSA migrations added by v4.0:**
- `005_pgvector.py`: `CREATE EXTENSION IF NOT EXISTS vector;` (no tables)
- `006_msgchains.py`: `msgchains` + `memory_entries` tables + hnsw index

No schema changes to v3.2.1 tables (`pentest_sessions`, `workflow_messages`, `rescope_approvals`, `agent_executions`, `users`, `teams`, `projects`, `targets`, `workflows`, `audit_logs`, `reports`).

---

## §6. Safety Model Comparison

**PentAGI brakes (per `pentagi/backend/pkg/providers/performer.go` and `.env.example`):**

| Brake | Mechanism | Source |
|-------|-----------|--------|
| Iteration cap (general) | `maxGeneralAgentChainIterations = 100` | performer.go |
| Iteration cap (limited) | `maxLimitedAgentChainIterations = 20` | performer.go |
| Retry count | `maxRetriesToCallAgentChain = 3`, `maxRetriesToCallFunction = 3`, `maxRetriesToCallSimpleChain = 3` | performer.go |
| Reflector wrap | `maxReflectorCallsPerChain = 3` | performer.go |
| Execution Monitor (Adviser injection) | `EXECUTION_MONITOR_SAME_TOOL_LIMIT=5`, `EXECUTION_MONITOR_TOTAL_TOOL_LIMIT=10` | .env.example |
| Tool-call quotas | Per-role: Searcher ≤20, others ≤100 | performer.go |
| Soft-detection abort | `maxSoftDetectionsBeforeAbort = 4` | performer.go |
| Sandbox | Per-flow Docker container; LLM via `terminal` tool calls `docker exec` | tools/terminal.go |
| Iteration cap (shutdown) | `maxAgentShutdownIterations = 3` | performer.go |
| Inter-retry delay | `delayBetweenRetries = 5 * time.Second` | performer.go |
| Operator control | `stopFlow` mutation, `finishFlow` mutation, `ASK_USER=true` opt-in | controller/flow.go |

**What PentAGI does NOT have (OSA-strong hybrid preserves):**

| OSA-only brake | OSA source | Why critical for OSA |
|----------------|------------|---------------------|
| **Per-target whitelist (CIDR/domain enforcement)** | `backend/app/safety/whitelist.py` (`WhitelistValidator`) | Legal/compliance: OSA pentests are scoped to specific client environments. Whitelist enforces "no scan outside the contracted IP/domain set." |
| **Tier gating** (passive_no_target_contact / passive_low_touch / active_recon / active_exploit) | `backend/app/agents/registry.py` (`Tier` field on `ToolEntry`) + `backend/app/orchestrator/service.py:80-178` | Operator must explicitly approve crossing into active recon or exploit tier. Session-level flags `active_recon_requires_explicit_approval` + `active_exploit_requires_explicit_approval` in `core/config.py`. |
| **Exploit allowlist (MSF prefixes + Nuclei tag block-list)** | `backend/app/safety/exploit_allowlist.py` | Hard-coded acceptable Metasploit module prefixes (auxiliary/scanner, auxiliary/gather, post/multi/*, exploit/multi/handler only); blocked Nuclei tags (dos, fuzz, bruteforce, intrusive). Prevents destructive exploits from running even when active_exploit tier is approved. |
| **Egress monitor (runtime log inspection)** | `backend/app/safety/egress_monitor.py` | Real-time inspection of container stdout/stderr. Detects unsafe egress patterns (data exfil, C2 callbacks) and triggers kill switch. |
| **Kill switch (Docker API container kill)** | `backend/app/safety/kill_switch.py` | Emergency halt: kills all running session containers via Docker API in ≤5s (configurable `kill_switch_timeout_seconds`). |
| **Audit log (all actions)** | `backend/app/safety/audit.py` (`AuditLogger`) + `backend/app/models/audit.py` (`AuditLog` table) | Compliance: every operator action, every tool dispatch, every approval, every rescope decision logged with actor + target + timestamp. Legal evidence preservation. |
| **Whitelist on rescope discoveries** | `backend/app/orchestrator/rescope_service.py` | Mid-execution discovery of new targets pauses session; operator must approve before they enter scope. |

**OSA-strong hybrid contract (revised v4.0):**
- v1 adopts PentAGI brakes: iteration caps (64 general, 20 limited per ADR-003), retry counts, Reflector wrap (3 retries with 200ms/1s/5s backoff), Adviser injection (5 same-tool / 10 total-tool), per-role tool-call quotas.
- v1 preserves OSA brakes: whitelist, tier gating, exploit allowlist, egress monitor, kill switch, audit log, rescope approval.
- v1 does NOT adopt: raw `terminal` tool (LLM emits structured tool calls, not shell); single per-flow Docker container model (OSA's per-tool ExecutionBackend pattern stays).

**Critical invariant (Principle 1 of v4.0):** safety chain order — `WhitelistValidator → filter_plan_steps → RiskFilter.filter_steps → EgressMonitor → KillSwitch.check_active` — is invariant across all Performer dispatches. Pentester emits structured tool calls; Performer's `_dispatch_tool` runs the chain in this exact order before invoking `AgentAdapter.execute()`. Any v3.4+ role (Coder, Installer) that ships raw-shell access requires a separate safety re-validation ADR.

---

## Adoption Summary

**5 patterns adopted in v4.0:**
1. 2-pane resizable shell + 3+3 tabs (`/flow/:id` route).
2. Role-based Performer pattern + 6 roles (Generator/Pentester/Memorist/Adviser/Reflector/Reporter).
3. Agent-as-tool delegation (structured tool calls under ADR-005).
4. pgvector + Memorist RAG (Thin v1, local sentence-transformers, k=3 auto-call).
5. Topic-per-panel streaming (WebSocket-evolved with `topic` kwarg, ADR-001).

**Explicit rejections (v1):**
- Raw `terminal` tool (LLM shell access) — deferred to v3.4 with separate safety ADR
- 3 right-pane tabs (Searches / Vector Store / Screenshots) — v3.4
- 8 of 14 PentAGI roles — v3.4
- GraphQL substrate as default — fall-back only if ADR-001 thresholds miss
- Multi-LLM provider expansion — Anthropic-only locked v3.2.1
- Graphiti+Neo4j optional stack — v3.4
- Per-flow Docker container model — OSA per-tool ExecutionBackend preserved

**3 substantive gaps documented:**
1. **PentAGI safety < OSA safety.** PentAGI relies on sandbox + iteration caps + `ASK_USER`. OSA layers 6 explicit brakes (whitelist, tier-gating, exploit-allowlist, egress, kill-switch, audit) on top. Adopt PentAGI's brakes additively; never remove OSA's. Pentester's structured-tool-call envelope (ADR-005) is the mechanism that preserves all OSA brakes while letting role-level autonomy live above them.
2. **PentAGI flat SubTask list vs OSA DAG-style plan_json.** PentAGI: `Flow → Task → SubTask → Action → Artifact/Memory`, flat. OSA: `pentest_sessions.plan_json` is a list with topological-sortable steps (workflow_plan.py), so DAG-capable but currently rendered as a list. P4 bridges: Generator's SubTask list lands in `draft_plan_json`; topological order applied via `workflow_plan.normalize()` on approval; runtime delegation follows topological order.
3. **PentAGI per-flow Docker container vs OSA per-tool container.** PentAGI: one container per flow, LLM emits shell into it. OSA: each AgentAdapter spawns its own container per `agent_executions` row via `DockerBackend`. OSA's model is preserved — Pentester emits structured tool call, Performer dispatches via `get_adapter()`, adapter spawns its own container, results stream via `event_bus`. PentAGI's per-flow model is incompatible with OSA's per-tool tier gating and would require collapsing tier semantics into a runtime classifier (rejected per Round 1).

---

## Implementer Lookup Index

For Phase implementers (P1–P5), this section maps PentAGI source paths to OSA target paths in one place:

| PentAGI source | OSA target | Phase |
|----------------|------------|-------|
| `pentagi/frontend/src/pages/flows/flow.tsx` | `frontend/src/pages/FlowPage.tsx` | P3-main |
| `pentagi/frontend/src/features/flows/flow-central-tabs.tsx` | `frontend/src/components/flow/LeftPane.tsx` | P3-main |
| `pentagi/frontend/src/features/flows/flow-tabs.tsx` | `frontend/src/components/flow/RightPane.tsx` | P3-main |
| `pentagi/frontend/src/features/flows/terminal/flow-terminal.tsx` | `frontend/src/components/flow/tabs/TerminalTab.tsx` | P3-main |
| `pentagi/frontend/src/features/flows/tasks/` | `frontend/src/components/flow/tabs/TasksTab.tsx` | P3-main |
| `pentagi/frontend/src/features/flows/agents/` | `frontend/src/components/flow/tabs/AgentsTab.tsx` | P3-main |
| `pentagi/backend/pkg/providers/performer.go` | `backend/app/orchestrator/performer.py` | P1 skeleton + P2a wired |
| `pentagi/backend/pkg/providers/performers.go` (role enum) | `backend/app/orchestrator/roles/registry.py` | P1 + P2a |
| `pentagi/backend/pkg/tools/registry.go` | `backend/app/orchestrator/roles/pentester.py` (palette derived from existing `backend/app/agents/registry.py`) | P2a |
| `pentagi/backend/pkg/tools/terminal.go` | NOT adopted v1; deferred ADR for v3.4 Coder/Installer | v3.4 |
| `pentagi/backend/pkg/graph/schema.graphqls` (subscriptions) | `backend/app/core/events.py` (extended with `topic` kwarg) + `backend/app/api/v1/ws.py` | P3-spike |
| `pentagi/backend/pkg/graph/subscriptions/{publisher,subscriber,controller}.go` | `backend/app/core/events.py` `EventBus` class | P3-spike |
| `pentagi/backend/migrations/sql/*msgchains*.sql` | `backend/alembic/versions/006_msgchains.py` | P1 |
| `pentagi/backend/migrations/sql/*memory*.sql` (pgvector) | `backend/alembic/versions/005_pgvector.py` + `006_msgchains.py` (memory_entries table) | P1 |
| `pentagi/backend/pkg/providers/assistant.go` | NOT adopted v1; left-pane Assistant tab is a placeholder | v3.4 |
| `pentagi/.env.example` (EXECUTION_MONITOR_*, AGENT_PLANNING_STEP_ENABLED, ASK_USER) | `backend/app/core/config.py` settings additions in P1 (`adviser_trigger_same_tool=5`, etc.) | P1 |
