# Deep Interview Spec: Pentagi-style New-Flow Page for OSA (multi-provider model selection, auth popups, presets, Automation/Assistant modes)

## Metadata
- Interview ID: osa-newflow-pentagi-ui
- Rounds: 3 (Round 0 topology + 3 scoring rounds)
- Final Ambiguity Score: ~19%
- Type: brownfield
- Generated: 2026-07-02
- Threshold: 0.20
- Threshold Source: default
- Initial Context Summarized: no
- Status: PASSED (ambiguity ≤ threshold)
- Branch: feat/kali-coexistence-v1

## Clarity Breakdown
| Dimension | Score | Weight | Weighted |
|-----------|-------|--------|----------|
| Goal Clarity | 0.85 | 0.35 | 0.2975 |
| Constraint Clarity | 0.78 | 0.25 | 0.1950 |
| Success Criteria | 0.75 | 0.25 | 0.1875 |
| Context Clarity | 0.88 | 0.15 | 0.1320 |
| **Total Clarity** | | | **0.812** |
| **Ambiguity** | | | **0.188 (~19%)** |

## Topology
All 5 components confirmed **active** (no deferrals). User explicitly chose to build Assistant fully.

| Component | Status | Description | Coverage / Deferral Note |
|-----------|--------|-------------|--------------------------|
| 1. Page layout/UX redesign | active | Restyle `/pentest-sessions/new` (PentestWorkflow.tsx) to Pentagi's new-flow composition | Adopt Pentagi layout in OSA's shadcn/Tailwind design system; standalone at existing route (NOT the deferred `/flow` consolidation) |
| 2. Provider + model selector | active | Anthropic/Ollama/OpenAI; per-session **per-role** model assignment; real routing | Session default + optional per-role overrides; default = Anthropic claude-opus-4-8; Ollama→qwen; wire per-session/per-role provider routing into backend |
| 3. First-time auth popup + secure reuse | active | Popup on first provider selection (API key now; OAuth when configured); reuse Fernet-encrypted creds | Reuse existing credential subsystem + AddCredentialModal; flip `osa_multi_provider_llm` ON |
| 4. Preset templates | active | Prompt presets + workflow templates next to model selector | Prompt presets prefill objective → autonomous lane; workflow templates seed plan_json → deterministic lane |
| 5. Automation / Assistant modes | active | Mode toggle; Automation (exists) + fully-built interactive Assistant | Assistant = chat-driven, reuses Automation's tier gates (recon-auto / exploit-gated); chosen at creation, fixed for session |

## Goal
Redesign the OSA new pentest-session page at `/pentest-sessions/new` (`PentestWorkflow.tsx`) so its UI/UX mirrors Pentagi's new-flow page, and wire the supporting behavior end-to-end:

1. **Model selection** across three providers — **Anthropic, Ollama, OpenAI** — with a session **default model plus optional per-role overrides** (the ~6 agent roles: Coordinator/Generator, Pentester, Memorist, Adviser, Reflector, Assistant). The selection **actually routes** each session's agents to the chosen provider/model (new per-session/per-role provider fields threaded through the backend, not just the global `osa_llm_provider` switch).
2. **First-time auth popup**: the first time a user selects a vendor that needs credentials (Anthropic or OpenAI) with none configured, a popup connects them via that vendor's **API key** (OAuth path kept available but only functional when real client IDs are configured in env). Credentials are stored **securely** (existing Fernet at-rest, per-user) and reused silently afterward. **Ollama requires no auth** (local qwen).
3. **Preset templates** next to model selection: **prompt/objective presets** (chips that prefill the objective box and run the autonomous lane) **and workflow templates** (the 3 existing DAG templates — recon-only/web-pentest/full-scope — that seed `plan_json` and run the deterministic saved-workflow lane).
4. **Automation and Assistant modes**: a mode toggle. Automation is the existing autonomous Coordinator→Pentester flow. **Assistant is fully built**: an interactive chat where the operator converses turn-by-turn with an AI that invokes the **same safety-gated tools** under the **same tier gates** as Automation (recon runs automatically; exploit/active-tier steps require the session's approval flags). Mode is chosen on the new-flow page and fixed for the session.
5. **Default behavior**: a new session defaults to **Anthropic claude-opus-4-8** (requires an Anthropic key/env to run); **Ollama and OpenAI are explicit opt-ins**. Choosing Ollama uses the locally-installed **qwen3-14b** by default. The multi-provider surface (`osa_multi_provider_llm`) is **flipped ON by default** so the selector, popups, and Credentials page are visible.

Visual fidelity: **adopt Pentagi's layout/composition** (provider-model selector + preset chips + Automation/Assistant toggle + prompt box) rendered with OSA's **existing design system** (shadcn/Tailwind tokens, dark mode) — faithful to structure, consistent with OSA styling (not a pixel clone).

## Constraints
- **Additive, not rip-and-replace** (project byword D5 / ralplan Principle 1): the deterministic Coordinator, legacy PlanExecutor, and no-LLM demo path must keep working as fallback; byte-identical replay regression (W0 comparator) must stay green.
- **Safety chain is immutable** (D4 / C7): every autonomous- and Assistant-agent tool call must traverse `filter_plan_steps → filter_by_tier_flags(session.approval_flags) → RiskFilter → shims → backend hardening → IMAGE_REGEX`. The AST guard `tests/ast/test_no_direct_backend_calls.py` must stay green. Assistant's tool execution uses the **same** dispatch path as Automation — no new bypass.
- **Credential security** (existing, must preserve): Fernet at-rest encryption, per-user scoping (ADR-004, no per-team), never log/return plaintext, audit every credential touch, decrypted secret in process memory only, `contextvars.copy_context()` at spawn sites for per-user isolation.
- **Standalone page**: keep the redesign at `/pentest-sessions/new`; do NOT block on the Pentagi-port Phase 3 `/flow/:id` consolidation (its Phase 1–2 foundation is not yet merged).
- **Provider set is exactly Anthropic / Ollama / OpenAI** for the selector. Google/Gemini stays hidden even though backend supports it.
- **Per-role assignment** structured as: one session default + an "Advanced" expander for per-role overrides (common case = a single choice).
- **OAuth reality**: OAuth client IDs are placeholders in code; ship API-key popups now, keep OAuth available but gracefully degrade to API-key when client IDs are unset.
- **Ollama** is model-agnostic and local-only; list installed models live via `GET {ollama_base_url}/api/tags`, default `qwen3-14b-96k:latest`; if unreachable, present the qwen default and surface a clear "Ollama server not reachable" state.
- Must run on the existing stack: React 18 + React Router 6 + Tailwind + shadcn/Radix (frontend); FastAPI + SQLAlchemy + Alembic (backend); existing `LLMRouter`, `OllamaClient`, `user_llm_credentials`, credential_resolver.

## Non-Goals
- Google/Gemini provider in the selector (hidden this round).
- The full Pentagi-port `/flow/:id` page consolidation (separate Phase 3 effort).
- Pixel-perfect cloning of Pentagi's exact CSS.
- Per-team / shared credentials (ADR-004 keeps per-user).
- Building real OAuth app registrations for Anthropic/OpenAI (API-key-first; OAuth functional only when operator supplies real client IDs).
- Editable/DAG-authoring UI for workflow templates (the 3 existing templates are wired as-is; no template editor).
- Scheduled/recurring "automation" (Automation here = the existing autonomous execution lane, not cron).

## Acceptance Criteria
- [ ] `/pentest-sessions/new` renders a Pentagi-style form (provider/model selector + preset area + Automation/Assistant toggle + objective box) using OSA's design system, with `osa_multi_provider_llm` ON by default.
- [ ] Provider selector offers exactly Anthropic, Ollama, OpenAI. Selecting Ollama lists locally-installed models (live `/api/tags`), defaulting to qwen3-14b; Anthropic/OpenAI show curated model lists.
- [ ] Session default is **claude-opus-4-8** (Anthropic); the existing admin-only gate on opus is reconciled so the default is usable (see Assumptions).
- [ ] A session-default model applies to all roles; an "Advanced" expander allows per-role model overrides for the ~6 roles; overrides are persisted and actually route each role's LLM calls at runtime (verified via a test asserting a role uses its assigned provider/model).
- [ ] Selecting Anthropic or OpenAI with **no active credential** opens an auth popup; entering an API key stores it (Fernet, per-user) and closes the popup; subsequent selections reuse it silently (no popup). Ollama never prompts.
- [ ] The backend `POST /pentest-sessions/` accepts new provider/model routing fields (e.g., `provider`, per-role model map) and the session's agents run on the selected provider/model — an integration test proves a non-Anthropic selection reaches the correct client.
- [ ] Prompt presets render as chips; clicking one prefills the objective box (and sensible defaults) and the session runs the autonomous lane. Workflow-template presets seed `plan_json` and run the deterministic saved-workflow lane.
- [ ] Automation vs Assistant toggle is present; the choice is persisted on the session and fixed for its lifetime.
- [ ] Assistant mode: operator can chat; the AI can invoke safety-gated tools through the **same** dispatch/tier-gate path as Automation (recon-auto, exploit-gated); recon executes without per-step approval, exploit/active-tier steps require approval flags; all calls are audited. An integration test proves an Assistant tool call traverses the full safety chain.
- [ ] Credential plaintext is never returned by any API or logged; audit entries are written on create/use/revoke. (Existing invariants remain green.)
- [ ] Additive guarantee: deterministic lane + no-LLM demo path + byte-identical replay regression remain green; AST safety guard remains green.
- [ ] `npx tsc --noEmit` passes (frontend) and the backend test suite passes (target: existing 1028 baseline + new tests for provider routing, Assistant safety traversal, preset lane selection, auth-popup flow).

## Assumptions Exposed & Resolved
| Assumption | Challenge | Resolution |
|------------|-----------|------------|
| "Change the new-flow page" = the deferred `/flow` consolidation | Phase 3 `/flow` needs unmerged Phase 1–2 foundation | Standalone redesign of existing `/pentest-sessions/new`; `/flow` consolidation is out of scope |
| Assistant could be a stub | User could accept the deferred v3.4 placeholder | User chose to **build Assistant fully** (interactive chat + tools) |
| OAuth works for all vendors | Client IDs are placeholders; Anthropic/OpenAI are API-key in practice | API-key-first popups now; OAuth available only when real client IDs configured |
| Ollama is the session default | Original prompt said "Ollama defaults to qwen" | Clarified: **Anthropic claude-opus-4-8 is the session default**; "Ollama→qwen" applies only when Ollama is chosen; Ollama/OpenAI are opt-ins |
| Presets = one concept | OSA has both prompt-style and DAG workflow templates | **Both**: prompt presets → autonomous lane; workflow templates → deterministic lane |
| Model selection is single-model | Pentagi supports per-agent models | **Per-role** assignment: session default + optional per-role overrides |
| Flag stays OFF | Feature must be visible | Flip `osa_multi_provider_llm` **ON** by default |
| opus is admin-only | Default opus-4-8 must be usable by non-admins | **To confirm at approval:** relax `workflow_opus_requires_admin` for the opus-4-8 default (or non-admins fall back to sonnet-4-6). Also: `claude-opus-4-8` must be **added to the Anthropic catalog** (today it has opus-4-6/sonnet-4-6). |

## Technical Context (brownfield findings)
**Frontend (React 18 + Router 6 + Tailwind + shadcn/Radix):**
- Target page: `frontend/src/pages/PentestWorkflow.tsx` (route `/pentest-sessions/new` via `App.tsx`). Current form: hardcoded model dropdown (claude-sonnet-4-6 default, claude-opus-4-6 admin-only), dynamic domain-agent dropdown, prompt textarea → `createPentestDraft()` POST `/pentest-sessions/` `{project_id, initial_prompt, model_id, domain_agent_slug}`.
- Credentials UI exists: `pages/CredentialsPage.tsx` (`/credentials`, gated by `osa_multi_provider_llm`), `pages/OAuthCallback.tsx` (`/auth/oauth/callback`), `api/credentials.ts` (`listCredentials`/`createCredential`/`revokeCredential`/`startOAuth`), modal pattern `AddCredentialModal` + `RevokeDialog` (fixed inset backdrop, no external dialog lib).
- `api/agents.ts` `getTemplates()` exists but is **unwired**. `components/flow/tabs/AssistantTab.tsx` is a v3.4 placeholder. `components/flow/LeftPane.tsx` has Automation/Assistant/Dashboard tabs. `hooks/useFeatureFlags.ts` + `api/featureFlags.ts` define flags.
- Design tokens: `tailwind.config.js` HSL CSS vars (`--primary`, `--card`, etc.), dark mode.

**Backend (FastAPI + SQLAlchemy + Alembic):**
- LLM: `app/orchestrator/llm/base.py` (`LLMClient` ABC), `router.py` (`LLMRouter` → anthropic/openai/google), `anthropic_provider.py`/`openai_provider.py`/`google_provider.py`, `credential_resolver.py` (per-user lookup + Fernet decrypt + env fallback), `context.py` (`CURRENT_USER_ID` contextvar). **Ollama is separate**: `app/orchestrator/ollama_client.py` (local HTTP, default `qwen3-14b-96k:latest`, base `http://host.docker.internal:11434`), selected via global `osa_llm_provider` in `planner.py` / `roles/llm_provider.py`.
- Credentials: `app/models/credential.py` (`UserLLMCredential`), `app/core/security.py` (`encrypt_credential`/`decrypt_credential`, `CREDENTIAL_FERNET_KEY`), `app/api/v1/credentials.py` (CRUD + OAuth start/callback PKCE + scope-drift + audit; in-memory OAuth state; providers anthropic/openai/google, api_key + oauth_token). Migrations `009_user_llm_credentials`, `011_oob_callbacks`.
- Session create: `app/api/v1/pentest_sessions.py` (`CreateDraftBody` = `{project_id, initial_prompt(1-4000), model_id?, domain_agent_slug?}`), `app/models/session.py` (`PentestSession`; `model_id` default claude-sonnet-4-6, `approval_flags` JSONB tier gates, `plan_json` saved-workflow marker, `interview_state`).
- Execution: `app/orchestrator/service.py` (`run()`: fresh-plan vs saved-workflow lane by `plan_json`; autonomous lane flag-gated `osa_xbow_autonomous_enabled` default True; `_run_autonomous_lane()` threads prompt→`context['objective']`). `roles/pentester.py` reads objective + tool-loop. `coordinator.py` deterministic objective parse (+ optional Ollama LLM understanding).
- Presets/modes reference: `app/api/v1/agents.py` defines 3 templates (recon-only/web-pentest/full-scope, `GET /agents/templates`). `.omc/research/pentagi-reference.md` and `.omc/specs/deep-interview-osa-pentagi-port.md` document the Automation/Assistant/2-pane pattern.
- Config/flags: `app/core/config.py` — `osa_multi_provider_llm` (False), `osa_llm_provider` (anthropic|ollama), `osa_xbow_autonomous_enabled` (True), `ollama_*`, `anthropic_*`, `workflow_opus_requires_admin` (True).

## Ontology (Key Entities)
| Entity | Type | Fields | Relationships |
|--------|------|--------|---------------|
| Provider | core domain | id (anthropic\|ollama\|openai), auth_required, auth_methods | has many Models; may need a Credential |
| Model | core domain | id, provider, display_name, admin_only | belongs to Provider; assigned to Roles |
| Credential | core domain | id, user_id, provider, credential_type (api_key\|oauth_token), encrypted_value, label, expires_at, revoked_at | belongs to User; resolves Provider at spawn |
| AuthMethod | supporting | api_key \| oauth (PKCE) | used by Credential |
| PromptPreset | core domain | id, label, objective_text, defaults | prefills Session objective → autonomous lane |
| WorkflowTemplate | core domain | id, label, steps(DAG), executable | seeds Session.plan_json → deterministic lane |
| Role | core domain | id (coordinator/generator/pentester/memorist/adviser/reflector/assistant), assigned_model | uses a Model; runs in a Mode |
| Mode | core domain | automation \| assistant | fixed per Session; governs execution style |
| PentestSession | core domain | id, project_id, objective/prompt, provider, model_map(role→model), mode, approval_flags, plan_json | has Roles, a Mode; gated by SafetyChain |
| SafetyChain | external/invariant | whitelist, tier_gate, exploit_allowlist, egress, kill_switch, audit | wraps every tool call (both Modes) |

## Ontology Convergence
| Round | Entity Count | New | Changed | Stable | Stability Ratio |
|-------|-------------|-----|---------|--------|----------------|
| 1 | 8 | 8 | - | - | N/A |
| 2 | 10 | 2 (PromptPreset/WorkflowTemplate split; Mode) | 1 (Preset→split) | 7 | ~80% |
| 3 | 10 | 0 | 0 | 10 | 100% (converged) |

## Interview Transcript
<details>
<summary>Full Q&A (Round 0 + 3 rounds)</summary>

### Round 0 — Topology
**Q:** Is the 5-component topology right (layout / selector / auth popup / presets / modes), and should Assistant be stubbed or fully built?
**A:** All 5 in scope; **build Assistant fully** too.

### Round 1
**Q1 Providers:** **Anthropic, Ollama, OpenAI only** (Google hidden; curated lists; Ollama live `/api/tags`, default qwen).
**Q2 Auth:** **API-key per vendor now, OAuth when configured** (placeholder client IDs acknowledged).
**Q3 Presets:** **Both** — prompt presets + workflow templates.
**Q4 Assistant:** **Interactive chat that runs safety-gated tools.**
**Ambiguity:** ~33%

### Round 2
**Q1 Assistant approvals:** **Same tier gates as Automation, chat-driven** (recon-auto, exploit-gated).
**Q2 Preset→lane:** **Prompt presets prefill (autonomous); workflow templates run the deterministic lane.**
**Q3 Routing+flag:** **Per-role model assignment.**
**Q4 Mode selection:** **Chosen at creation, fixed for the session.**
**Ambiguity:** ~26%

### Round 3
**Q1 Per-role UI:** **One session default + optional per-role overrides (Advanced expander).**
**Q2 Default model:** **Anthropic claude-opus-4-8** as session default; Ollama/OpenAI opt-in (user edit); requires Anthropic key/env.
**Q3 Flag:** **Flip `osa_multi_provider_llm` ON by default.**
**Q4 Fidelity:** **Adopt Pentagi's layout/composition in OSA's design system.**
**Ambiguity:** ~19% ✅

</details>
