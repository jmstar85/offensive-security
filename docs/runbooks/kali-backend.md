# Kali coexistence backend — operational runbook

This runbook covers the v1 Kali coexistence path (KaliBackend + KaliExecAdapter
+ docker-socket-proxy chain). Read this before:

- Adding a new tool to the Kali allowlist
- Bumping any package version pin in `docker/kali/kali-apt-snapshot.env`
- Modifying `KALI_ALLOWED_CAPS` (currently `frozenset()` — empty)
- Responding to a docker-socket-proxy / image-regex middleware incident
- Performing the quarterly rebuild + digest/apt-snapshot rotation
- Investigating a typed-adapter call-rate drop alert (F5 dashboard)

## (a) Whitelist tool addition PR checklist

A new Kali tool entry **only** ships when every checkbox below is signed off
by the @security-reviewer team (CODEOWNERS enforces this for
`backend/app/safety/kali_allowlist.py`).

1. **ToolEntry registration** in `backend/app/agents/registry.py` with the
   correct tier, capabilities, applicable domain tags, and
   `is_destructive_capable` flag.
2. **`ALLOWED_TOOLS` entry** in `backend/app/safety/kali_allowlist.py`:
   - `binary` absolute path inside `osa-kali:`
   - `arg_validators` regex per supported flag
   - `value_flags` for flags whose value lives in the next argv element
   - `cap_add` (must be `()` — subset of `KALI_ALLOWED_CAPS=frozenset()`)
   - `risk_band_score` (0.0–1.0)
   - `tier` (`active_recon` or `active_exploit`)
   - `is_destructive_capable`
3. **WhitelistShim coverage**: ≥10 negative test cases against the new tool
   (deny-flag, path traversal, regex mismatch), ≥3 positive cases.
4. **Parser plugin** in `backend/app/agents/parsers/<slug>.py` exporting
   `parse(raw_output, agent_type) -> AgentResult` and registered in
   `backend/app/agents/parsers/__init__.py`. **Generic line-mode fallback is
   forbidden** — the adapter must raise `NotImplementedError` if no parser
   is registered.
5. **Per-slug adapter subclass** in `backend/app/agents/kali_exec.py`
   (3 lines: `agent_type`, `tool_slug`, optional `risk_level`).
6. **Apt pin** in `docker/kali/kali-apt-snapshot.env` if the tool isn't
   already in the base image. Rebuild + SBOM diff approved.
7. **`kali_exec_allowlist` audit coverage**: `filter_plan_steps_kali` test
   shows that deny-flag and path-deny scenarios are blocked for the new slug.

## (b) `KALI_ALLOWED_CAPS` modification procedure

`KALI_ALLOWED_CAPS` is `frozenset()` in v1. Any expansion is a Tier-0 ADR
requiring:

1. New ADR file in `.omc/adrs/` enumerating the capability requested, the
   tool that requires it, the threat-model delta, and the LSM mitigation
   (seccomp profile diff, AppArmor profile diff if applicable).
2. Security-reviewer approval (CODEOWNERS on
   `backend/app/safety/kali_allowlist.py`).
3. CI test added that asserts `set(entry["cap_add"]) ⊆ KALI_ALLOWED_CAPS`
   for the new tool entry.
4. Staging soak with the cap enabled — A5.6 quantitative thresholds apply.

## (c) docker-socket-proxy ops + F3 incident response

The Kali path's daemon-boundary defence is two-tier:

- `tecnativa/docker-socket-proxy` enforces the endpoint allowlist (only
  `POST /containers/create|start|stop`, `GET /containers/{id}/json|logs`,
  `DELETE /containers/{id}`).
- `backend/app/infra/socket_proxy_filter.py` enforces the body filter
  (`Image` field must match `^osa-kali(:|@)`).

**On incident**:

1. Pull recent `osa_kali_socket_proxy_403_total` per endpoint. A non-zero
   value on any endpoint other than `containers/create` indicates someone
   tried to reach a denied endpoint — capture the originating step / session
   from `kali_exec.start` audit events.
2. Pull `osa_kali_filter_plan_block_total` for spikes. Image-regex
   rejections at the middleware layer mean a backend code path is asking
   to launch a non-`osa-kali` image — likely a prompt-injection attempt.
3. Inspect the relevant `audit_log` rows (action prefix `kali_exec.`) and
   the surrounding session for compromise indicators before re-enabling.

**Bypass procedures are not provided**. If a legitimate non-kali image
must be launched, do it through `DockerBackend`, not the proxy chain.

## (d) Quarterly rebuild + digest/apt-snapshot rotation

The `.github/workflows/kali-quarterly-rebuild.yml` workflow runs `0 0 1 */3 *`
and also accepts `workflow_dispatch`. Steps:

1. Workflow pulls upstream `kalilinux/kali-rolling`, captures the new digest.
2. Runs `make build-kali`, which produces a new SBOM under `.omc/sbom/`.
3. Diffs the new SBOM against the previous one. ≥5 added/removed lines or
   an apt-snapshot date rotation triggers the Slack webhook
   (`KALI_QUARTERLY_SLACK_WEBHOOK` secret).
4. Bot opens a PR updating `docker/kali/kali.env` (KALI_DIGEST) and
   `docker/kali/kali-apt-snapshot.env` (snapshot date + package SHAs).
5. Human merges only after CODEOWNERS approval. Auto-merge of bot PRs is
   explicitly disabled per A3.6.

## (e) F5 telemetry — typed-adapter call-rate drop

Dashboard tracks the ratio of legacy-typed-adapter calls vs `kali_*` calls
on a 7-day rolling window. If `kali_*` exceeds the 7-day baseline by
≥20 percentage points (i.e. the planner has started preferring generic
Kali tools over the typed adapters), F5 alarm fires. Response:

1. Check `osa_kali_exec_total{tool_slug}` to see which Kali tool is
   over-fired.
2. Pull recent planner prompts from `audit_log` and look for tool-selection
   hints that bias toward `kali_*`.
3. If the planner has learned a generic bias, update the prompt template
   to reaffirm: "Prefer existing typed adapters when applicable; only use
   `kali_*` for Kali-only tools."
4. Roll the prompt change with a 24h staging soak before prod toggle.

## Staging quantitative thresholds (A5.6)

Before the prod toggle on `OSA_KALI_BACKEND_ENABLED`, staging must exhibit
all five within a 24-hour window:

- `osa_kali_container_start_failures_total` 24h increase = 0
- `osa_kali_socket_proxy_403_total{endpoint="containers/create"}` = 0 in
  normal use
- `osa_kali_filter_plan_block_total` > 0 (the synthetic deny-flag test
  must have run at least once)
- `osa_kali_exec_total{outcome="success"}` ≥ 10 across real traffic
- Existing 9-tool integration tests pass at 100% on the same staging build

Any miss → block prod toggle, root-cause, re-attempt.

## Feature flag

`OSA_KALI_BACKEND_ENABLED` (boolean, default `False`). Double-enforced at:

- `app.agents.registry.get_adapter` — raises `KaliBackendDisabledError`
- `app.agents.registry.palette_for_domain` — filters `kali_*` out

Local override: `export OSA_KALI_BACKEND_ENABLED=true` before launching the
backend.

## Related plan + spec

- Plan: [.omc/plans/ralplan-kali-coexistence-v1.md](../../.omc/plans/ralplan-kali-coexistence-v1.md)
- Spec: [.omc/specs/deep-interview-kali-docker-unified.md](../../.omc/specs/deep-interview-kali-docker-unified.md)
- Apt strategy: [.omc/research/apt-snapshot-strategy.md](../../.omc/research/apt-snapshot-strategy.md)
