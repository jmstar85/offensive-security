# Deep Interview Spec: OSA Main-Page Redesign + Pentest Rebrand + "Sign in with Claude" OAuth

## Metadata
- Interview ID: osa-mainpage-oauth-v1
- Rounds: 5 (+ Round 0 topology gate)
- Final Ambiguity Score: ~15%
- Type: brownfield
- Generated: 2026-07-05
- Threshold: 0.2
- Threshold Source: default
- Initial Context Summarized: no
- Status: PASSED

## Clarity Breakdown
| Dimension | Score | Weight | Weighted |
|-----------|-------|--------|----------|
| Goal Clarity | 0.88 | 0.35 | 0.308 |
| Constraint Clarity | 0.80 | 0.25 | 0.200 |
| Success Criteria | 0.82 | 0.25 | 0.205 |
| Context Clarity | 0.90 | 0.15 | 0.135 |
| **Total Clarity** | | | **0.848** |
| **Ambiguity** | | | **0.152 (~15%)** |

## Topology
| Component | Status | Description | Coverage / Deferral Note |
|-----------|--------|-------------|--------------------------|
| C1 · Right-panel hero redesign | active | Drop the spinning `favicon.svg`; replace with a self-contained animated pentest hero (headline + sub-copy over SVG/CSS motion). | Applies to **all 3 auth pages**: `Login.tsx`, `Register.tsx`, `ResetPassword.tsx`. Designer drafts 2–3 copy variants; user picks during build. |
| C2 · Pentest icon + favicon rebrand | active | Replace red shield icon with a pentest-themed glyph; propagate to favicon + all ~9 branding touchpoints. | Designer proposes 2–3 SVG favicons; user picks; then propagate. Product **name stays "OSA Platform"** (icon-only rebrand). |
| C3 · "Sign in with Claude" OAuth | active | Add subscription-based Anthropic OAuth (Claude-Code-style PKCE) alongside API key, **full end-to-end** so sessions run on the user's Pro/Max subscription. | Surfaced in New-session flow + central Credentials page. Unofficial/ToS-gray path explicitly accepted by user. |

## Goal
Redesign the OSA Platform auth/landing experience and extend Anthropic authentication:

1. **C1** — On all three auth pages, keep the LEFT panel (credential form, "OSA Platform" title) exactly as-is, and replace the RIGHT panel's spinning-icon animation with an impactful, self-contained hero: a bold headline (in the spirit of *"Fully autonomous AI-powered penetration testing platform"*) plus punchy sub-copy, laid over a pentest-themed animated background (e.g. scanning radar / terminal stream / network-graph motion in SVG/CSS). No external GIF/video asset required.
2. **C2** — Replace the red-shield `favicon.svg` with a pentest-themed icon (designer proposes 2–3 SVG concepts; user picks the winner), then propagate the chosen icon everywhere it appears: `favicon.svg`, `index.html` (`<link rel=icon>`, `<title>`, `theme-color`), `manifest.webmanifest`, the `SidebarShell` logo, and the 3 auth-page hero references (which C1 will largely replace). Keep the product name "OSA Platform".
3. **C3** — Add a "Sign in with Claude" OAuth option to Anthropic authentication in the New-session flow (and the central Credentials page), implemented end-to-end so an authenticated user can run real pentest sessions on their Claude Pro/Max subscription with **no API key**. Uses the Claude-Code-style PKCE flow against `claude.ai`.

## Constraints
- **Left panel is untouched** on all 3 auth pages — only the right `<aside>` (`Login.tsx:160-172` and equivalents in `Register.tsx:200-209`, `ResetPassword.tsx:185-194`) changes.
- **Icon-only rebrand** — do NOT rename the product; "OSA Platform" stays in title, manifest, sidebar, `osa-theme`/`osa-flow-shell` storage keys unchanged.
- Favicon must remain legible at 16px → favor simple, bold glyphs.
- Right-panel hero is **self-contained** (SVG/CSS) — no dependency on an external recording or new heavy binary asset.
- C3 OAuth is the **unofficial Claude subscription flow** (reuses a public client_id, `anthropic-beta: oauth-*` header, subscription-scoped token). User has explicitly accepted the ToS-gray / may-break-without-notice risk.
- Reuse existing infrastructure: `UserLLMCredential` already models `credential_type='oauth_token'`; the PKCE endpoints (`credentials.py:284-434`) and OOB-callback migration (`011_oob_callbacks`) already exist and should be completed rather than rebuilt.
- Preserve the existing Anthropic API-key path — OAuth is **additive**, not a replacement.
- Styling stays in Tailwind (no CSS modules / styled-components); dark mode is default.

## Non-Goals
- Renaming/re-branding the product away from "OSA Platform".
- Changing the LEFT login form, its fields, or auth logic.
- Adding OAuth for other providers (OpenAI/Google) in this effort — Copilot OAuth already exists and is the reference pattern only.
- App-level SSO (logging into OSA via Google/GitHub) — explicitly not what was requested.
- Shipping a real product screen-recording GIF (a self-contained designed hero was chosen instead).

## Acceptance Criteria
**C1 — Right-panel hero**
- [ ] The `animate-logo-spin` spinning `favicon.svg` is removed from the right `<aside>` on `Login.tsx`, `Register.tsx`, and `ResetPassword.tsx`.
- [ ] Each right panel renders a headline + sub-copy over a pentest-themed animated SVG/CSS background; designer produced 2–3 copy variants and the chosen one is wired in.
- [ ] Left panel (form + "OSA Platform" title) is visually unchanged.
- [ ] Right panel remains `hidden lg:flex` (mobile behavior preserved); no layout/CLS regressions; light + dark themes both look correct.
- [ ] The now-unused `logo-spin` keyframes/animation are removed from `tailwind.config.js` if no longer referenced anywhere.

**C2 — Icon + favicon rebrand**
- [ ] Designer delivered 2–3 SVG favicon concepts; the user-selected one replaces `public/favicon.svg`.
- [ ] New icon renders correctly in the browser tab (16px), `manifest.webmanifest` icons, and `SidebarShell` logo.
- [ ] `index.html` `<title>`, `theme-color`, and description are consistent with the new icon/color (name still "OSA Platform"); `dist/index.html` mirror updated or rebuilt.
- [ ] No stale references to the old shield remain in the ~9 mapped touchpoints.

**C3 — "Sign in with Claude" OAuth (end-to-end)**
- [ ] A "Sign in with Claude" button appears in the New-session Anthropic auth (`PentestWorkflow.tsx`) and the Credentials page (`CredentialsPage.tsx`), alongside the API-key option.
- [ ] Clicking it runs the PKCE flow (authorize on `claude.ai` → code → token exchange), completing via loopback or the existing OOB manual-paste callback (`011_oob_callbacks`).
- [ ] The resulting token is stored as an encrypted `UserLLMCredential` with `credential_type='oauth_token'` (Fernet, never returned in API responses), including refresh handling / `expires_at`.
- [ ] `AnthropicProvider` (`anthropic_provider.py:11-12`) accepts an OAuth bearer token: sends `Authorization: Bearer <token>` + `anthropic-beta: oauth-*` header and omits `x-api-key`; `credential_resolver`/`router` construct it from the `oauth_token` credential.
- [ ] **End-to-end proof:** a user who signed in with Claude (no API key present) can start and complete a real pentest session driven by their subscription.
- [ ] API-key auth still works unchanged (additive, no regression). Recommended: gate the subscription-OAuth path behind a reversible config flag for safety (see Assumptions).

## Assumptions Exposed & Resolved
| Assumption | Challenge | Resolution |
|------------|-----------|------------|
| "Anthropic OAuth" = an official third-party OAuth program | There is none for the Messages API | Use the **unofficial Claude subscription** flow (Claude-Code-style PKCE); user accepted the ToS/stability risk |
| "Main page" = dashboard/new-session | Code shows the spinning icon lives on the **Login** two-panel page | "Main page" = Login (`Login.tsx`); "New session" (`PentestWorkflow.tsx`) is a separate page for C3 |
| Right-panel change is Login-only | Same panel is duplicated in Register + ResetPassword | Apply C1 to **all 3 auth pages** for consistency |
| Need a real product GIF | Requires an asset + adds weight | **Designed self-contained hero** (SVG/CSS) — no asset needed |
| Rebrand includes renaming to "Pentagi" | User asked to swap the *icon*, not the name | **Icon-only**; product name stays "OSA Platform" |
| OAuth = just an auth UI | Hardest/ToS-grayest part is actually *calling* Claude via the token | User wants **full end-to-end** — sessions run on the subscription |
| Pick an icon now | Favicon must read at 16px and match brand | **Designer proposes 2–3 SVGs**, user picks before propagation |
| Lock hero copy now | "Impactful" is subjective | **Designer drafts 2–3 copy variants**, user picks during build |

## Technical Context (brownfield, verified via explore)
- **C1 target:** `frontend/src/pages/Login.tsx:160-172` (right `<aside>`, gradient bg + `animate-logo-spin` `favicon.svg`); duplicated in `Register.tsx:200-209`, `ResetPassword.tsx:185-194`. Animation defined in `tailwind.config.js:51-55` (`logo-spin`, 10s 360°). Tailwind + HSL theme vars in `index.css`. Assets in `frontend/public/`.
- **C2 touchpoints:** `public/favicon.svg` (primary), `index.html` (`:6` desc, `:7` theme-color `#991b1b`, `:8` icon link, `:10` title), `public/manifest.webmanifest` (name/short_name/theme/icons), `SidebarShell.tsx:98,101` (logo + "OSA Platform"), the 3 auth pages, `Dashboard.tsx:21`, `tailwind.config.js`, `index.css` (`--primary: 0 72% 51%`). Icon lib = `lucide-react` (UI nav only, separate from favicon). `dist/index.html` is a built mirror.
- **C3 backend:** `models/credential.py` (`UserLLMCredential`: provider ∈ anthropic/openai/google/copilot, credential_type ∈ api_key/oauth_token, Fernet-encrypted, `expires_at`); `api/v1/credentials.py` (PKCE `oauth_start`/`oauth_callback` `:284-434` with a **placeholder** `auth.anthropic.com` URL to replace; Copilot **device flow** `:442-585` as reference); `orchestrator/llm/router.py` (`get_client`/`route`), `credential_resolver.py:28-67` (per-request resolve/decrypt), `anthropic_provider.py:11-12` (api_key-only today — must accept OAuth token), `core/config.py:70-94` (settings), migrations `011_oob_callbacks` (OOB manual-paste callback — reuse for the claude.ai flow), `012` (credential schema).
- **C3 frontend:** `PentestWorkflow.tsx:43-90` (per-role provider/model select, Anthropic models opus-4-8/sonnet-4-6), `CredentialsPage.tsx`, `AddCredentialModal.tsx` (api_key entry), `CopilotConnectModal.tsx` (device-flow modal — reference pattern), `api/credentials.ts` (`startOAuth`/`startCopilotDevice`/`pollCopilotDevice`), `OAuthCallback.tsx` (PKCE callback handler).
- **OAuth mechanics (reference):** authorize on `claude.ai/oauth/authorize` with PKCE (S256), token exchange, subscription scopes; call Messages API with `Authorization: Bearer <access_token>` + `anthropic-beta: oauth-*` and **no** `x-api-key`. Redirect must be one the reused client_id permits → loopback or OOB paste (hence `011_oob_callbacks`). Token refresh required.

## Ontology (Key Entities)
| Entity | Type | Fields | Relationships |
|--------|------|--------|---------------|
| AuthPage / RightPanelHero | UI surface | headline, subCopy, animatedBackground, panelSide | Login/Register/ResetPassword each render one |
| BrandIcon | asset | svg, glyphConcept, color, size(16px…) | referenced by favicon, manifest, SidebarShell, index.html |
| UserLLMCredential | domain (existing) | provider, credential_type(api_key\|oauth_token), encrypted_value, expires_at | belongs to User; resolved by credential_resolver → LLMClient |
| Provider | enum-ish string | anthropic\|openai\|google\|copilot | selects LLMClient in router |
| ClaudeSubscriptionSession | flow | pkce_verifier, oauth_token, refresh, beta_header | AnthropicProvider uses token to run PentestSession |

## Ontology Convergence
| Round | Entity Count | New | Changed | Stable | Stability Ratio |
|-------|-------------|-----|---------|--------|----------------|
| 1 | 5 | 5 | - | - | N/A |
| 2 | 5 | 0 | 0 | 5 | 100% |
| 3 | 5 | 0 | 0 | 5 | 100% |
| 4 | 5 | 0 | 0 | 5 | 100% |
| 5 | 5 | 0 | 0 | 5 | 100% |

## Interview Transcript
<details>
<summary>Full Q&A (Round 0 + 5 rounds)</summary>

### Round 0 — Topology
**Q:** 3 components (right-panel hero / icon rebrand / Anthropic OAuth) — right shape? Include Register+ResetPassword?
**A:** Right — all 3 auth pages (apply right-panel redesign to Login + Register + ResetPassword).

### Round 1 — C3 OAuth intent (Goal/Constraint)
**Q:** What does "Anthropic OAuth" mean, given no official third-party program exists?
**A:** "Sign in with Claude" (subscription) — unofficial Claude-Code-style PKCE, risk accepted.

### Round 2 — C1 right panel (Goal)
**Q:** GIF vs designed hero; do you have an asset?
**A:** Designed hero, no asset needed (self-contained SVG/CSS + headline).

### Round 3 — C2 icon (Goal)
**Q:** Which pentest icon concept + color? (name stays "OSA Platform")
**A:** Designer proposes 2–3 SVG favicons; user picks.

### Round 4 — C3 OAuth depth (Success Criteria, Contrarian)
**Q:** End-to-end call via subscription token, or auth+store only?
**A:** Full end-to-end (run pentest sessions on the subscription).

### Round 5 — C1 hero copy (Success Criteria)
**Q:** Lock hero messaging; keep left-panel title?
**A:** Draft 2–3 copy variants, user picks; left panel keeps "OSA Platform" + form.

</details>
