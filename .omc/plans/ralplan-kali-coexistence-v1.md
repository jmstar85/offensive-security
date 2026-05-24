# RALPLAN: Kali-Docker Parallel Coexistence v1

**Status:** pending approval
**Mode:** consensus (deliberate)
**Source spec:** [.omc/specs/deep-interview-kali-docker-unified.md](.omc/specs/deep-interview-kali-docker-unified.md)
**Final spec ambiguity:** 18% (passed 20% threshold)
**Generated:** 2026-05-24T08:43:07Z
**Revision:** iter-2 (consensus refinement — applied Architect T1/T2/T3 + Critic S1-1/S1-2/S1-3 + S2-1..S2-5 + S3-1..S3-3 + S4-1..S4-2)

---

## RALPLAN-DR Summary

### Principles (5)
1. **Backward compatibility absolute** — 기존 9개 typed adapter 회귀 0건. 어떤 변경도 `get_adapter("nmap")` 등의 기존 호출 시맨틱을 바꾸지 않는다.
2. **Defense in depth across THREE LAYERS** — Kali 통합 컨테이너의 surface는 정확히 세 층으로 신뢰된다: ① 호출-전 게이트 layer (확장된 `filter_plan_steps` + `risk_filter` 가 `agent=kali_*` 및 `(tool_slug, args)` 까지 검증), ② 런타임 isolation layer (seccomp/cap_drop ALL/RO root/tmpfs/network policy), ③ daemon-경계 layer (`docker-socket-proxy` 가 backend 컨테이너와 호스트 dockerd 사이를 매개, allowlisted API endpoint만 노출). 어느 한 층도 *주장만으로* 통과되지 않는다 — 각 층은 자체 통합 테스트로 입증된다.
3. **Reproducibility before convenience** — digest pin이 `:latest`를 이긴다. apt 패키지도 **digest+snapshot 쌍**으로 pin 한다. SBOM이 "rebuilds work"를 이긴다.
4. **One whitelist, one location** — Kali 도구 화이트리스트는 `backend/app/safety/kali_allowlist.py` *한 곳*에만 존재하며, agents 모듈은 *import*만 한다. import-graph 테스트로 발산 방지.
5. **Coexist, do not migrate** — DockerBackend와 KaliBackend는 v1에서 동등 1급 시민. KaliBackend는 DockerBackend의 *subclass가 아닌 sibling* 으로 구현되어 기존 9개 adapter 경로에 어떠한 hardening도 *주입*하지 않는다.

### Decision Drivers (top 3)
1. **D1 — 도구 커버리지 확장**: Kali repo 의존 web/api 공격 도구 추가 비용 = 화이트리스트 엔트리 + 옵션 parser 플러그인. (Kali 전용 패키지 예: `kali-tools-web` 메타패키지가 묶는 `whatweb`, `dirb`, `joomscan`, `wfuzz` Kali 빌드 등 — R4 Contrarian 답변의 근거.)
2. **D2 — 측정 가능한 안전 동등성**: 위 Principle 2의 3층을 모두 *코드 + 테스트로 강제*. Critic S1-1이 식별한 silent-allow를 제거하기 위해 `filter_plan_steps`/`risk_filter` 는 v1에 *반드시* 확장한다.
3. **D3 — 감사·재현성**: image digest pin + apt snapshot pin + SBOM + CODEOWNERS-gated digest 변경 PR.

### Viable Options
| 옵션 | 한 줄 요약 | 핵심 trade-off |
|------|----------|--------------|
| **O1 (chosen): Parallel coexistence + per-slug typed entries(공유 adapter class)** | DockerBackend 유지 + KaliBackend(sibling, hardened) + `KaliExecAdapter`(공유 class) + **per-slug ToolEntry** (kali_gobuster/kali_sqlmap/kali_nikto, sqlmap=active_exploit) + 단일 safety/kali_allowlist + filter_plan_steps/risk_filter 확장 + docker-socket-proxy | (+) 회귀 0건, tier·risk_band 보존, 안전 layer 일관 (−) two-track 유지 비용, socket-proxy 인프라 추가 |
| **O2 (rejected): Full migration to KaliBackend** | 9개 기존 adapter도 모두 Kali base로 재타겟 | 회귀 위험, parsing 품질 손실, PR 비대 |
| **O3 (rejected): Single generic `kali_exec` ToolEntry** | 1차 초안 — Architect/Critic이 tier/risk 붕괴로 거절 | sqlmap이 `active_recon`/`MEDIUM`로 mis-tier → `approved_active_exploit` 세션 게이트 우회 |
| **O4 (rejected by R4 Contrarian): Debian-slim base** | Kali 포기 | Kali 전용 패키지 의존(R4 답)으로 객관적 부적합 |

### Invalidation rationale
- **O2** 거절: R6 Simplifier — 9개 typed adapter parsing logic은 finding 품질의 핵심.
- **O3** 거절(iter-2 추가): Critic S1-3 — 단일 `kali_exec` entry는 `filter_by_tier_flags`에서 sqlmap을 `active_exploit`으로 분류하지 못해 세션 승인 게이트를 silently 우회. **per-slug 다중 ToolEntry** 가 정답.
- **O4** 거절: R4 사용자 응답 + ADR 각주의 Kali-only 패키지 예시로 객관적 정당화.

### Pre-mortem (5 scenarios — S4-1 적용으로 F4/F5 추가)
1. **F1 — WhitelistShim 인자 우회 (file-read / SSRF / 자격증명 누출)**: `--wordlist=/etc/shadow`, `--output=/proc/self/environ`, `--proxy http://evil/`, `-x socks5://attacker/`, `--cookie-jar /root/.kube/config`, `--auth-cred user:$(cat /etc/passwd)` 등의 인자가 통과되면 호스트/사용자 정보 누출.
   - **사전 차단:** WhitelistShim에 (a) 도구별 positional/flag arg validator regex (≥10 negative test per tool), (b) **deny-flag set**: `--proxy`, `-x`, `--http-proxy`, `--https-proxy`, `--auth-cred`, `--cookie-jar`, `--load-cookies`, `--config`, `--rc-file`, `--shell`, `--os-shell`, `--sql-shell`, `--file-read`, `--file-write`, (c) **path denylist**: 인자 안 절대경로는 `/work/`(tmpfs)·`/wordlists/`(이미지내 RO 리소스) 만 허용, `..`/`/etc/`/`/proc/`/`/sys/`/`/var/run/`/`/root/`/`/.ssh/`/`$HOME` 모두 거부.
2. **F2 — Digest 핀 회귀 (이미지 + apt 두 축)**: Dockerfile에서 누군가 `kalilinux/kali-rolling:latest`로 수정하거나, digest는 그대로지만 apt update 시 패키지 버전이 바뀌어 재현성 손실.
   - **사전 차단:** CI lint(A3.1) + apt snapshot 파일 `.env.kali-apt-snapshot`(A3.5) + digest/snapshot 변경 PR은 분기별 워크플로우 봇만 생성 + **CODEOWNERS** (`docker/kali/**`, `.env.kali*`)로 security-reviewer 승인 강제 (A3.6).
3. **F3 — backend 컨테이너 prompt-injection → docker.sock 권한 남용**: LLM-driven prompt injection 또는 backend 의존성 RCE → docker daemon 권한을 통해 `docker run --privileged --pid=host -v /:/host` 가능. Kali 컨테이너의 `cap_drop=ALL`은 *공격자가 새 컨테이너를 만드는* 권한을 막지 않음.
   - **사전 차단(v1 채택, iter-3 N4 수정):** `tecnativa/docker-socket-proxy` 사이드카 + **proxy 앞단의 Python middleware `backend/app/infra/socket_proxy_filter.py`** 조합. **KaliBackend의 docker client만** proxy 경유 (DockerBackend는 host socket 직접 — Principle 5 보존). Proxy 환경변수는 A2.5에 enumerate된 endpoint allowlist만 허용 (6개). middleware는 `POST /containers/create` body의 `Image` 필드를 `^osa-kali:` 정규식으로만 허용 (KaliBackend는 자신의 이미지만 만들 수 있음). `IMAGE_FILTER` 등 미검증 proxy 기능 사용 안 함 (Critic N4). 미설치 시 v1 출시 차단.
4. **F4 — 마이그레이션 사고로 기존 9개 adapter가 KaliBackend로 라우팅 (Principle 1 위반)**: registry.py 리팩터링 중 `get_adapter("nmap")` 가 KaliBackend를 반환 → 기존 adapter들이 의도치 않은 hardening 변화로 부분 실패.
   - **사전 차단:** A4.3 회귀 테스트가 *9개 모든 도구*에 대해 `isinstance(backend, DockerBackend) and not isinstance(backend, KaliBackend)` 어서션. registry.py 변경 시 CODEOWNERS에 security-reviewer 자동 추가.
5. **F5 — Planner LLM이 generic kali_exec 호출을 선호하여 typed adapter 사용 빈도 감소 (Principle 5 위반 — coexist가 점진 미그레로 변질)**: per-slug 등록(O1)으로 일차 차단되지만, planner prompt가 "use kali_exec when uncertain" 같은 hint를 학습하면 우회 가능.
   - **사전 차단:** Planner prompt 명시 — "기존 9개 typed adapter가 적용 가능하면 우선 사용. `kali_*` 는 *명시적으로 Kali 전용 도구가 필요할 때만*." Telemetry: 주간 dashboard로 typed adapter 호출 비율 모니터, 기준선 대비 -20%p 이상 하락 시 alarm.

### Expanded Test Plan (unit / integration / e2e / observability) — Critic 지적 보강

#### Unit
- `tests/unit/test_kali_whitelist.py` — `WhitelistShim.verify()` 입출력 매트릭스. 도구별 (positional/flag, allowed/denied) ≥10건 per tool × 3 tools = 30+ 케이스. **추가:** deny-flag set 각 항목당 1건 + path denylist 8건.
- `tests/unit/test_kali_exec_adapter.py` — `build_command()` 단위 테스트. `tool_slug` 누락/오타/대소문자/공백/path traversal/abuse 시도.
- `tests/unit/test_kali_backend_hardening.py` — `KaliBackend.start()` 호출이 docker-py `containers.run()`에 `security_opt`, `cap_drop=["ALL"]`, `cap_add ⊆ KALI_ALLOWED_CAPS` (v1=`frozenset()`), `read_only=True`, `tmpfs={...}` 를 *항상* 전달하는지 mock 검증.
- `tests/unit/test_kali_allowlist_single_source.py` — **(신규, Critic S1-2)** import-graph 테스트: `agents/kali_whitelist.py` 가 `safety.kali_allowlist` 에서 `ALLOWED_TOOLS`를 *import*만 하고 자체 정의를 갖지 않음을 AST로 검증. 두 곳 분기 시 fail.
- `tests/unit/test_filter_plan_steps_kali.py` — **(신규, Critic S1-1)** `filter_plan_steps({"agent":"kali_sqlmap", "tool_slug":"sqlmap", "args":["--os-shell"]})` 가 blocked + audit_log emit. gobuster `--wordlist=/etc/shadow` 도 blocked. 정상 args는 passed.
- `tests/unit/test_risk_filter_kali_tool_slug.py` — **(신규, Critic S1-1)** `risk_filter.assess_step({"agent":"kali_sqlmap", ...})` 가 `risk_band=HIGH` 반환 (per-slug). gobuster 는 `MEDIUM`.
- `tests/unit/test_kali_allowed_caps_empty.py` — **(신규, Critic S2-3)** `KALI_ALLOWED_CAPS == frozenset()` 및 `ALLOWED_TOOLS` 의 어떤 entry도 `cap_add` 비어있지 않으면 fail.

#### Integration
- `tests/integration/test_kali_backend_safety.py` — 실제 Docker 데몬으로:
  - (a) `security_opt` 누락된 변형 시도 → 컨테이너 시작 거부
  - (b) `WhitelistShim` 외 명령 시도 → exec 도달 전 차단 + audit_log 기록
  - (c) tmpfs 밖 디렉터리(`/etc/`)에 쓰기 시도 → read-only fs 에러
  - (d) `cap_add` 없이 raw socket 시도 → permission denied
  - (e) **(신규, iter-3 Critic P2 확장 — ≥6 negative assertion)** `docker-socket-proxy` allowlist 외 endpoint들이 모두 403:
    - (e.1) `POST /images/create` → 403
    - (e.2) `GET /networks` → 403
    - (e.3) `POST /containers/{id}/exec` → 403
    - (e.4) `POST /volumes/create` → 403
    - (e.5) `GET /info` → 403
    - (e.6) `POST /containers/create` body `Image=alpine` (allowlist 외) → middleware regex 차단 → 403
    - (e.7) **양성 대조**: `POST /containers/create` body `Image=osa-kali:<digest>` → 200/201 (정상 시작)
- `tests/integration/test_kali_filter_plan_steps.py` — **(신규, Critic S1-1)** `filter_plan_steps` 가 `agent=kali_sqlmap` step에 대해 `--os-shell`/`--sql-shell`/`--file-write` 인자를 reject. `agent=kali_gobuster` 에 대해 `--wordlist=/etc/shadow` reject.
- `tests/integration/test_kali_tier_band_gate.py` — **(신규, Critic S1-3)** session 에 `approved_active_exploit=False` 일 때 `kali_sqlmap` step 이 `filter_by_tier_flags` 에서 reject. `approved_active_exploit=True` 일 때 passed.
- `tests/integration/test_kali_socket_proxy.py` — **(신규, Critic S2-1)** docker-compose stack에 socket-proxy 포함하여 backend 가 `docker.sock`에 직접 접근 불가, proxy 통해 `containers/create` (osa-kali image) 만 성공.
- `tests/integration/test_kali_reproducibility.py` — 같은 digest + 같은 **apt snapshot** + 같은 fixture target → finding JSON deepEqual. (Critic S2-2 적용으로 apt snapshot 차원 추가)
- `tests/integration/test_pipeline.py` — 기존 9개 도구 통합 테스트 *전부 그대로 통과* (회귀 0건).

#### E2E
- `tests/e2e/test_kali_web_palette.py` — Planner(LLM) 가 web target 에 대해 `kali_gobuster` / `kali_sqlmap` / `kali_nikto` 도구를 호출 → KaliExecAdapter → KaliBackend → (socket-proxy 경유) 컨테이너 실행 → finding emit → DB 저장. fixture target = `vulnerables/web-dvwa@sha256:<pinned>` (S3-1 적용).
- `tests/e2e/test_kali_backend_disabled_path.py` — feature flag (`OSA_KALI_BACKEND_ENABLED=false`) 시 `get_adapter("kali_gobuster")` 가 `KaliBackendDisabledError` raise 하고 `palette_for_domain` 이 `kali_*` 를 *제외* 함.
- `tests/e2e/test_existing_9_tools_unchanged.py` — **(신규, Critic S4-2 / Pre-mortem F4)** 9개 도구 각각에 대해 `get_adapter(slug)` 후 backend instance 가 `type(backend) is DockerBackend` (KaliBackend가 아님) 확인 + 각 adapter 의 통합 실행 정상.

#### Observability
- `audit_log` 신규 이벤트 타입 5종 (Critic 기존 3종 + 추가 2종): `kali_exec.start`, `kali_exec.shim_block`, `kali_exec.hardening_violation`, **`kali_exec.filter_plan_steps_block`**, **`kali_exec.tier_gate_block`**. 각 schema 정의 + dashboard rows.
- Prometheus counters: `osa_kali_exec_total{tool_slug, outcome}`, `osa_kali_shim_block_total{reason}`, `osa_kali_container_start_failures_total{reason}`, `osa_kali_socket_proxy_403_total{endpoint}`, `osa_kali_filter_plan_block_total{tool_slug, reason}`.
- 주간 dashboard: typed-adapter 호출 비율 / kali_* 호출 비율. 기준선 대비 ±20%p 변동 시 alert (F5 완화).
- SBOM diff: 분기별 재빌드 후 패키지 추가/제거 ≥5건 시 슬랙 webhook. **추가:** apt snapshot lock diff도 동일.

---

## Requirements Summary (Critic 반영)
1. `KaliBackend(ExecutionBackend)` — **DockerBackend의 sibling** (subclass 금지), 별도 docker client 인스턴스. [backend/app/agents/backends/kali.py](backend/app/agents/backends/kali.py).
2. `KaliExecAdapter(AgentAdapter)` — 공유 adapter class, 다중 `ToolEntry` 슬러그가 같은 클래스 인스턴스화. [backend/app/agents/kali_exec.py](backend/app/agents/kali_exec.py).
3. **Single source of truth allowlist**: [backend/app/safety/kali_allowlist.py](backend/app/safety/kali_allowlist.py) — `ALLOWED_TOOLS` dict + `KALI_ALLOWED_CAPS=frozenset()` + `kali_exec_allowlist(step)` 헬퍼.
4. `WhitelistShim` ([backend/app/agents/kali_whitelist.py](backend/app/agents/kali_whitelist.py)) — `safety.kali_allowlist`만 import. 자체 데이터 0.
5. **Safety layer 확장**: [backend/app/safety/exploit_allowlist.py](backend/app/safety/exploit_allowlist.py) `filter_plan_steps` 에 `agent.startswith("kali_")` 분기 추가. [backend/app/safety/risk_filter.py](backend/app/safety/risk_filter.py) `assess_step` 도 동일하게 `tool_slug` 까지 본다.
6. Kali base Dockerfile + apt 버전 pin + apt snapshot lock + SBOM ([docker/kali/Dockerfile](docker/kali/Dockerfile) + `.env.kali` + `.env.kali-apt-snapshot`).
7. **Per-slug v1 화이트리스트**: `kali_gobuster`(active_recon, MEDIUM, NOT destructive), `kali_sqlmap`(**active_exploit, HIGH, is_destructive_capable=True**), `kali_nikto`(active_recon, MEDIUM, NOT destructive).
8. **docker-socket-proxy 사이드카** — docker-compose.yml에 추가 (`tecnativa/docker-socket-proxy:latest@sha256:<digest>`), backend는 proxy에만 연결.
9. **CODEOWNERS** — `docker/kali/**`, `.env.kali*`, `backend/app/safety/kali_allowlist.py` 변경 시 security-reviewer 승인 강제.
10. **Mandatory parsers** — gobuster, sqlmap, nikto 3종 모두 parser plugin 의무 작성.
11. 분기별 재빌드 CI workflow + SBOM diff + apt snapshot diff 알림.
12. Feature flag `OSA_KALI_BACKEND_ENABLED` (default `False`), 이중 enforcement: `get_adapter` raise + `palette_for_domain` filter.
13. Runbook `docs/runbooks/kali-backend.md` — 화이트리스트 PR 체크리스트, `KALI_ALLOWED_CAPS` 변경 절차, F3 socket-proxy 점검, 분기별 재빌드 절차.
14. 기존 9개 typed adapter 통합 테스트 0건 회귀.

## Acceptance Criteria

### A1. 코드 추가 (기능)
- [ ] **A1.1** `KaliBackend(ExecutionBackend)` 가 `ExecutionBackend` ABC의 4개 메서드 모두 구현. `DockerBackend`의 *subclass가 아님* (단위 테스트로 `not issubclass(KaliBackend, DockerBackend)` 어서션 — Critic S4-2).
- [ ] **A1.2** `KaliBackend.start()` 호출 시 docker-py `containers.run()` 이 다음을 *항상* 받음: `security_opt=["no-new-privileges:true", "seccomp=default"]`, `cap_drop=["ALL"]`, `cap_add=[]` (v1 — Critic N2 해소: `KALI_ALLOWED_CAPS=frozenset()` 의 부분집합은 항상 빈 리스트), `read_only=True`, `tmpfs={"/tmp":"size=128m,mode=1777", "/work":"size=512m,mode=1777"}`, `network_disabled=(network is None)`, `mem_limit`/`cpu_quota`/`pids_limit` 기존 설정.
- [ ] **A1.3** `KaliExecAdapter.build_command()` 가 `config["tool_slug"]`/`config["args"]` 를 `WhitelistShim.verify()` 통과 시에만 명령 리스트 반환. `parse_output()` 은 **도구별 mandatory parser plugin** 으로 dispatch (Critic S2-4).
- [ ] **A1.4** `WhitelistShim.verify(slug, args, target)` 가 등록된 도구별 arg validator regex + **deny-flag set** + **path denylist** 로 검증. 위반 시 `SafetyViolation` raise + `audit_log(event="kali_exec.shim_block", reason=...)`.
- [ ] **A1.5** [registry.py](backend/app/agents/registry.py) 의 `_REGISTRY` 에 **per-slug 엔트리 3종 추가** (Critic S1-3):
  ```python
  "kali_gobuster": ToolEntry(slug="kali_gobuster", adapter_cls=KaliExecAdapter, docker_image="osa-kali:<digest>", tier="active_recon", capabilities=("dir_brute","dns_brute","vhost_brute"), applicable_domain_tags=frozenset({"web","api"}), default_risk_band=RiskLevel.MEDIUM, is_destructive_capable=False),
  "kali_sqlmap": ToolEntry(slug="kali_sqlmap", adapter_cls=KaliExecAdapter, docker_image="osa-kali:<digest>", tier="active_exploit", capabilities=("sqli_detect","sqli_exploit"), applicable_domain_tags=frozenset({"web","api"}), default_risk_band=RiskLevel.HIGH, is_destructive_capable=True),
  "kali_nikto": ToolEntry(slug="kali_nikto", adapter_cls=KaliExecAdapter, docker_image="osa-kali:<digest>", tier="active_recon", capabilities=("web_vuln_scan",), applicable_domain_tags=frozenset({"web","api"}), default_risk_band=RiskLevel.MEDIUM, is_destructive_capable=False),
  ```
- [ ] **A1.6** **(Critic S2-4)** Parser plugin 세 개 작성 — `parse_gobuster`(라인 → `{type:"directory_found", path, status, size}`), `parse_sqlmap`(`--output-dir` JSON 파일 파싱 → `{type:"sql_injection", parameter, technique, payload, severity:"high"}`), `parse_nikto`(`-Format json` 파싱 → `{type:"web_vuln", id, message, severity}`). Adapter generic 'line' 모드는 **fallback이 아닌 명시 error** (모든 v1 도구는 parser 필수).

### A2. Safety 보강
- [ ] **A2.1** `tests/integration/test_kali_backend_safety.py` 의 (a)-(e) 모두 통과.
- [ ] **A2.2** [audit.py](backend/app/safety/audit.py) 에 5종 이벤트 schema 추가: `kali_exec.start`, `kali_exec.shim_block`, `kali_exec.hardening_violation`, **`kali_exec.filter_plan_steps_block`**, **`kali_exec.tier_gate_block`**. 각 필수 필드: `tool_slug`, `args`(redact), `reason`, `container_id`(있을 시), `step_id`, `session_id`, `timestamp`.
- [ ] **A2.3** **(Critic S1-1 핵심 수정 + iter-3 P1/N1 pin)** [exploit_allowlist.py](backend/app/safety/exploit_allowlist.py) `filter_plan_steps` 가 다음 분기를 *반드시* 포함 (필드 경로 확정 — Critic P1 + N1):
  ```python
  agent = step.get("agent","")
  if agent.startswith("kali_"):
      tool_slug = step.get("config", {}).get("tool_slug")
      args = step.get("config", {}).get("args", [])
      ok, reason = kali_exec_allowlist(agent, tool_slug, args)
      if not ok:
          audit_log("kali_exec.filter_plan_steps_block", {"slug": tool_slug, "reason": reason})
          continue  # drop step
  ```
  [risk_filter.py:65](backend/app/safety/risk_filter.py#L65) — `_AGENT_BASE_RISK.get(agent, 0.5)` 직전에 분기 *삽입*:
  ```python
  if agent.startswith("kali_"):
      tool_slug = step.get("config", {}).get("tool_slug")
      return ALLOWED_TOOLS[tool_slug]["risk_band_score"]  # per-slug, no fallthrough
  return _AGENT_BASE_RISK.get(agent, 0.5)
  ```
  `ALLOWED_TOOLS[slug]["risk_band_score"]` 필드는 PR-3에서 `kali_allowlist.py` 정의 시 동시 추가 (gobuster=0.5/MEDIUM, sqlmap=0.8/HIGH, nikto=0.5/MEDIUM).
- [ ] **A2.4** **(Critic S1-2 + iter-3 P1 expand)** [backend/app/safety/kali_allowlist.py](backend/app/safety/kali_allowlist.py) 가 화이트리스트 단일 소스. `agents/kali_whitelist.py` 는 `from app.safety.kali_allowlist import ALLOWED_TOOLS, KALI_ALLOWED_CAPS` 만 import (재정의 0). `tests/unit/test_kali_allowlist_single_source.py` 가 AST 검사로 다음을 *재귀적으로* 검증 (Critic 권고로 scope 확장):
  - `backend/app/agents/**/*.py` 와 `backend/tests/fixtures/**/*.py` 에서 모듈 레벨 `ALLOWED_TOOLS = ...` 할당이 *0건* (단일 소스 외부에서 재정의 금지)
  - 같은 트리에서 binary path literal (`"/usr/bin/gobuster"`, `"/usr/bin/sqlmap"`, `"/usr/bin/nikto"`) 가 *0건* (binary는 `ALLOWED_TOOLS[slug]["binary"]` 만)
  - `safety/kali_allowlist.py` 자신만 위 정의를 갖고 export
  AST 위반 시 즉시 fail + 위치 보고.
- [ ] **A2.5** **(Critic S2-1 / Pre-mortem F3 + iter-3 P0 fix)** [docker-compose.yml](docker-compose.yml) 에 `docker-socket-proxy` 사이드카 추가 (`tecnativa/docker-socket-proxy@sha256:<pinned>`). **단, KaliBackend 만 proxy 경유. 기존 DockerBackend는 변경 없음 — Critic iter-3 P0 (Principle 5) 해소** (구현은 PR-7 §2 two-client 패턴 참고).

  Proxy 설정 (`tecnativa/docker-socket-proxy` 환경변수):
  - `CONTAINERS=1`, `POST=1` (POST 메서드 전역 허용)
  - `IMAGES=0`, `NETWORKS=0`, `VOLUMES=0`, `EXEC=0`, `INFO=0`, `SERVICES=0`, `SWARM=0`, `SYSTEM=0`, `TASKS=0`, `BUILD=0`
  - 결과적으로 backend(KaliBackend client)가 호출 가능한 endpoint = `POST /containers/create`, `POST /containers/{id}/start`, `POST /containers/{id}/stop`, `GET /containers/{id}/json`, `GET /containers/{id}/logs`, `DELETE /containers/{id}` 6종 (Architect P0 — `containers.get()` 가 `GET /containers/{id}/json` 사용하므로 필수).

  Image regex 필터 — `tecnativa/docker-socket-proxy`는 endpoint 단위 허용만 제공하고 *body 필터링은 미지원*. 따라서 image regex (`^osa-(agent-|kali|passive-recon)` 또는 KaliBackend라면 `^osa-kali`) 강제는 **proxy 앞단의 small Python middleware** `backend/app/infra/socket_proxy_filter.py`가 단독 담당 (Critic N4 — `IMAGE_FILTER` 기능은 미검증 → 채택 안 함).

  Backend service 환경변수 (iter-3 Architect P0 — TLS 누락 시 from_env fail-back 위험 차단):
  ```yaml
  environment:
    # KaliBackend only — DockerBackend keeps from_env() unchanged
    KALI_DOCKER_HOST: tcp://docker-socket-proxy:2375
    DOCKER_TLS_VERIFY: ""   # explicit unset
    DOCKER_CERT_PATH: ""    # explicit unset
  ```
- [ ] **A2.6** **(Critic S2-5)** WhitelistShim deny-flag set: `--proxy`, `-x`, `--http-proxy`, `--https-proxy`, `--auth-cred`, `--cookie-jar`, `--load-cookies`, `--config`, `--rc-file`, `--shell`, `--os-shell`, `--sql-shell`, `--file-read`, `--file-write`, `--read-file`, `--write-file`. 도구별 arg에 등장 시 즉시 reject.

### A3. 재현성
- [ ] **A3.1** [docker/kali/Dockerfile](docker/kali/Dockerfile) 의 첫 `FROM` 라인 정규식: `^FROM kalilinux/kali-rolling@sha256:[a-f0-9]{64}$`. CI lint script `scripts/lint_kali_dockerfile.sh`.
- [ ] **A3.2** `make build-kali` 가 `.omc/sbom/kali-base-<digest>-<YYYYMMDD>.json` 생성. 미생성 시 build fail.
- [ ] **A3.3** **(Critic S2-2 + S3-1)** `tests/integration/test_kali_reproducibility.py` 는 같은 `(KALI_DIGEST, apt-snapshot-date, fixture-target-digest)` 트리플에서 finding JSON deepEqual 보장. Fixture target = `vulnerables/web-dvwa@sha256:<pinned>` (S3-1).
- [ ] **A3.4** `.github/workflows/kali-quarterly-rebuild.yml` cron `0 0 1 */3 *` + `workflow_dispatch`. SBOM diff 또는 apt snapshot diff ≥5건 시 슬랙 webhook.
- [ ] **A3.5** **(Critic S2-2)** Dockerfile 의 `apt-get install` 라인은 **버전 핀** + apt snapshot 사용:
  ```dockerfile
  RUN echo "deb [check-valid-until=no] https://snapshot.debian.org/archive/kali/<YYYYMMDDTHHMMSSZ>/ kali-rolling main" > /etc/apt/sources.list.d/snapshot.list \
      && apt-get update \
      && apt-get install -y --no-install-recommends \
           gobuster=<pinned-ver> sqlmap=<pinned-ver> nikto=<pinned-ver> ca-certificates \
      && rm -rf /var/lib/apt/lists/*
  ```
  (만약 snapshot.debian.org가 Kali rolling을 미러하지 않는 경우, Kali 자체 `kali-last-snapshot` 채널 사용 또는 자체 apt 미러로 대체. 결정은 PR-5 검증 단계에서.)
  Snapshot 날짜는 `.env.kali-apt-snapshot` 파일에 저장. CI lint가 Dockerfile의 snapshot URL과 `.env.kali-apt-snapshot` 일치 검증.
- [ ] **A3.6** **(Critic S3-2)** [.github/CODEOWNERS](.github/CODEOWNERS) 에 `docker/kali/** @security-reviewer`, `.env.kali* @security-reviewer`, `backend/app/safety/kali_allowlist.py @security-reviewer` 추가. branch protection 으로 dismiss stale review 활성. 분기별 워크플로우 봇 PR은 자동 머지 *금지*.

### A4. 회귀 0건
- [ ] **A4.1** [backend/tests/integration/test_pipeline.py](backend/tests/integration/test_pipeline.py) 전체 통과.
- [ ] **A4.2** [backend/tests/unit/test_agents.py](backend/tests/unit/test_agents.py) 전체 통과.
- [ ] **A4.3** **(Pre-mortem F4)** 9개 기존 슬러그(nmap, nuclei, metasploit, pyrit, passive_recon, subfinder, dnsx, httpx, cloudenum, wappalyzer) 각각에 대해 `get_adapter(slug).backend` 가 `DockerBackend` instance이고 `KaliBackend` instance가 *아님* — `tests/e2e/test_existing_9_tools_unchanged.py`.
- [ ] **A4.4** **(Critic S4-1에서 식별된 palette equality)** 기존 palette equality 테스트가 있다면, *subset assertion* 또는 *kali_\* 명시 추가 assertion* 으로 업데이트. 단순 equality 가 회귀하지 않도록 v1 PR에 포함.

### A5. 운영
- [ ] **A5.1** Kali base 이미지 최종 크기 ≤ 3GB.
- [ ] **A5.2** `make build-kali` cold cache 빌드 시간 ≤ 10분.
- [ ] **A5.3** **(Critic 명확화)** Feature flag `OSA_KALI_BACKEND_ENABLED` default `False`. 이중 enforcement: (a) `get_adapter(slug)` 가 `slug.startswith("kali_") and not settings.OSA_KALI_BACKEND_ENABLED` 시 `KaliBackendDisabledError` raise; (b) `palette_for_domain` 이 `kali_*` ToolEntry 를 결과에서 제외. 단위 테스트가 monkeypatch flag로 양쪽 검증.
- [ ] **A5.4** `docs/runbooks/kali-backend.md` — (a) 화이트리스트 도구 추가 PR 체크리스트(arg validator ≥10 tests, parser plugin 필수, security-reviewer 승인), (b) `KALI_ALLOWED_CAPS` 변경 절차(ADR 필수), (c) docker-socket-proxy 점검 절차(F3 incident response), (d) 분기별 재빌드/digest+apt snapshot 갱신 절차, (e) telemetry alert response(F5 dashboard).
- [ ] **A5.5** **(Critic S2-3)** `KALI_ALLOWED_CAPS: frozenset[str] = frozenset()` (v1 기준 *empty*). CI 테스트가 `ALLOWED_TOOLS` 의 모든 entry에 대해 `set(entry["cap_add"]) ⊆ KALI_ALLOWED_CAPS` 검증. 비어있지 않은 cap_add 도입 PR은 ADR 추가 + security-reviewer 승인 의무.
- [ ] **A5.6** **(Critic S3-3)** Staging 24h 관찰의 **정량 기준** — (a) `osa_kali_container_start_failures_total` 의 24h 증가량 = 0, (b) `osa_kali_socket_proxy_403_total{endpoint="containers/create"}` = 0 (정상 사용 시), (c) `osa_kali_filter_plan_block_total` 은 의도적 차단만 (테스트 트래픽 1건 이상으로 비-zero 확인), (d) `osa_kali_exec_total{outcome="success"}` ≥ 10 (실 사용 트래픽), (e) 기존 9개 도구 통합 테스트 staging 통과율 100%. 어느 하나라도 미달 시 prod toggle 차단 + 재현 → root-cause → 재시도.

## Implementation Steps

### Phase 1: 기반 추상화 + safety 단일 소스
1. **새 모듈 스켈레톤** (PR-1):
   - [backend/app/safety/kali_allowlist.py](backend/app/safety/kali_allowlist.py) — `ALLOWED_TOOLS = {}` (다음 PR에서 채움), `KALI_ALLOWED_CAPS = frozenset()`, `kali_exec_allowlist(step) -> tuple[bool, str]` 헬퍼 시그니처.
   - [backend/app/agents/backends/kali.py](backend/app/agents/backends/kali.py) — `KaliBackend(ExecutionBackend)` 골격 (NotImplementedError).
   - [backend/app/agents/kali_whitelist.py](backend/app/agents/kali_whitelist.py) — `from app.safety.kali_allowlist import ALLOWED_TOOLS, KALI_ALLOWED_CAPS` + `WhitelistShim.verify()` 시그니처.
   - [backend/app/agents/kali_exec.py](backend/app/agents/kali_exec.py) — `KaliExecAdapter(AgentAdapter)` 골격.
   - [backend/app/core/config.py](backend/app/core/config.py) 에 `OSA_KALI_BACKEND_ENABLED: bool = False`.
   - Tests: `test_kali_allowlist_single_source.py` (AST import-graph), `test_kali_allowed_caps_empty.py`.
   - **Gate:** A1.1 부분, A2.4, A5.3 부분, A5.5.

### Phase 2: Hardening + Shim
2. **`KaliBackend.start()` + sibling 패턴** (PR-2):
   - `KaliBackend.__init__` 이 **DockerBackend와 별개 docker client** 인스턴스 (`docker.DockerClient.from_env(timeout=60)`).
   - `start()` 는 docker-py `containers.run()` 호출 시 A1.2의 옵션 강제. `cap_add` 는 `set(per_tool_cap_add) - KALI_ALLOWED_CAPS` 가 비어있지 않으면 `SafetyViolation` raise.
   - `stream_logs/stop/cleanup` 은 `DockerBackend`와 동일 구조이나 *복사* (subclass 금지, Principle 5/A1.1).
   - Tests: `test_kali_backend_hardening.py`, `test_kali_backend_safety.py` (a)-(d).
   - **Gate:** A1.1 완료, A1.2, A5.5.

3. **`WhitelistShim` + v1 도구 3개 (single source)** (PR-3):
   - [backend/app/safety/kali_allowlist.py](backend/app/safety/kali_allowlist.py) 에 `ALLOWED_TOOLS` 채움 (per-tool validator + deny-flag set + path denylist).
   - `kali_exec_allowlist(step)` 구현 — `step["agent"]`/`tool_slug`/`args` 검증.
   - Tests: `test_kali_whitelist.py` (≥30 per-tool cases + 16 deny-flag + 8 path denylist), `test_filter_plan_steps_kali.py` (red — `filter_plan_steps` 미확장 상태).
   - **Gate:** A1.4, A2.6.

### Phase 3: Safety layer 확장 (Critic S1-1)
4. **`filter_plan_steps` + `risk_filter` 확장** (PR-4):
   - [exploit_allowlist.py](backend/app/safety/exploit_allowlist.py) `filter_plan_steps` 에 `if agent.startswith("kali_")` 분기 추가, `kali_exec_allowlist` 호출.
   - [risk_filter.py](backend/app/safety/risk_filter.py) `assess_step` 에 동일 분기, `ALLOWED_TOOLS[slug]["risk_band"]` 적용.
   - Tests: `test_filter_plan_steps_kali.py` 가 green, `test_risk_filter_kali_tool_slug.py`, `test_kali_tier_band_gate.py`.
   - **Gate:** A2.3.

### Phase 4: Adapter wiring + per-slug registry
5. **`KaliExecAdapter.build_command/parse_output` + registry per-slug** (PR-5):
   - [kali_exec.py](backend/app/agents/kali_exec.py) `build_command()` → `WhitelistShim.verify()` 후 `[entry["binary"], *args]`.
   - `parse_output()` → 도구별 mandatory parser dispatch. 미등록 slug → 명시 error.
   - Parser plugins: `parse_gobuster()`, `parse_sqlmap()`, `parse_nikto()` ([backend/app/agents/parsers/](backend/app/agents/parsers/) 신규 디렉터리).
   - [registry.py](backend/app/agents/registry.py) per-slug 3종 등록 (A1.5 코드 블록).
   - Tests: `test_kali_exec_adapter.py`, parser 단위 테스트 3종.
   - **Gate:** A1.3, A1.5, A1.6.

### Phase 5: Container image + apt snapshot

5.5. **(신규, iter-3 Critic P2)** **Apt snapshot strategy 1-hour spike** (PR-5.5, *PR-6 진입 전 의무*):
   - 결정 항목: (a) `snapshot.debian.org` 가 Kali rolling 을 미러하는지 1-hour 검증, (b) 미러 부재 시 Kali 공식 `kali-last-snapshot` 채널 활용 가능성, (c) 둘 다 부적합 시 자체 apt mirror 구축 (예: `aptly` 또는 `debmirror` + S3) 비용 평가.
   - 산출물: `.omc/research/apt-snapshot-strategy.md` 결정 문서, `.env.kali-apt-snapshot` 스키마 (snapshot URL + date + 해시), 1개 선택 옵션의 PR-6 Dockerfile 템플릿.
   - **PR-6 진입 게이트:** 위 문서 + 스키마가 commit 되어 있어야 PR-6 시작 가능.

6. **Kali Dockerfile + apt pin + SBOM + lint** (PR-6):
   - [docker/kali/Dockerfile](docker/kali/Dockerfile) 신규 (A3.5 코드 블록, PR-5.5 결정에 따른 snapshot URL 사용).
   - `.env.kali` (KALI_DIGEST), `.env.kali-apt-snapshot` (PR-5.5 스키마에 따른 snapshot 정보).
   - `Makefile` target `build-kali`: build + SBOM 생성 + apt snapshot lock 출력.
   - `scripts/lint_kali_dockerfile.sh` — A3.1 정규식 + apt snapshot URL/`.env.kali-apt-snapshot` 일치 검증.
   - **Gate:** A3.1, A3.2, A3.5, A5.1, A5.2.

### Phase 6: docker-socket-proxy + CODEOWNERS
7. **socket-proxy 사이드카 (Kali 전용) + CODEOWNERS** (PR-7, iter-3 P0 two-client 적용):
   - [docker-compose.yml](docker-compose.yml) 에 `docker-socket-proxy` 서비스 추가. backend service의 `/var/run/docker.sock` 마운트 **유지** (DockerBackend는 변경 없음 — Principle 5 보존). 신규 환경변수 `KALI_DOCKER_HOST=tcp://docker-socket-proxy:2375` 만 추가 + `DOCKER_TLS_VERIFY=""` + `DOCKER_CERT_PATH=""`.
   - **Two-client 패턴:**
     - `DockerBackend.__init__` — `self._client = docker.from_env()` (unchanged, host socket 직접).
     - `KaliBackend.__init__` — `self._client = docker.DockerClient(base_url=settings.KALI_DOCKER_HOST, timeout=60)` (proxy 경유 전용).
     - 두 client는 완전 분리. KaliBackend 실패가 DockerBackend에 영향 없음.
   - Image regex 필터 — proxy 앞단 small Python middleware [`backend/app/infra/socket_proxy_filter.py`](backend/app/infra/socket_proxy_filter.py): KaliBackend는 `^osa-kali:` 이미지만 생성 가능. 미들웨어는 단일 endpoint(`POST /containers/create`) 에서만 body 검사.
   - [.github/CODEOWNERS](.github/CODEOWNERS) 신규 또는 갱신.
   - Tests: `test_kali_socket_proxy.py` (integration — A2.1.(e.1)~(e.7) 7건), `test_existing_9_tools_unchanged.py` (Principle 5 회귀 가드 — 9개 도구가 여전히 host socket 직접 사용).
   - **Gate:** A2.5, A3.6, A4 (회귀 검증: 기존 9개 도구 *변경 없음*).

### Phase 7: Audit + observability
8. **Audit 이벤트 + 메트릭 + 분기별 워크플로우** (PR-8):
   - [audit.py](backend/app/safety/audit.py) 에 5종 이벤트 schema 추가.
   - Prometheus counters 등록.
   - [.github/workflows/kali-quarterly-rebuild.yml](.github/workflows/kali-quarterly-rebuild.yml) — cron + `workflow_dispatch` + SBOM diff + apt snapshot diff + 슬랙.
   - **Gate:** A2.2, A3.4.

### Phase 8: E2E + 회귀 + runbook + rollout
9. **E2E + 회귀 + runbook + staging→prod** (PR-9):
   - `tests/e2e/test_kali_web_palette.py`, `test_kali_backend_disabled_path.py`, `test_existing_9_tools_unchanged.py`.
   - `docs/runbooks/kali-backend.md`.
   - Staging `OSA_KALI_BACKEND_ENABLED=true` → A5.6 정량 기준 24h 관찰 → prod 토글.
   - **Gate:** A4, A5.3, A5.4, A5.6.

## Risks and Mitigations

| 위험 | 영향 | 가능성 | 완화 |
|------|------|--------|------|
| **R1** WhitelistShim arg regex 느슨/엄격 | shim 우회 또는 정상 사용 차단 | 중 | 도구당 ≥10 negative + 양성 케이스, deny-flag set, path denylist, staging 24h 정량 관찰 |
| **R2** Kali digest/apt snapshot이 floating으로 회귀 | 재현성 손실 | 저-중 | CI lint(A3.1+A3.5) + CODEOWNERS(A3.6) + 분기별 봇 PR 자동 머지 금지 |
| **R3** F3 backend prompt-injection으로 docker.sock 권한 남용 (Kali 경로) | 호스트 전면 노출 | 저(가능성), 매우 높음(영향) | A2.5 socket-proxy 사이드카 + **Python middleware** (image regex) + endpoint allowlist (6종) + runbook |
| **R10** **(신규, iter-3 Architect 권고)** DockerBackend는 host socket 직접 사용 유지 (Principle 5 보존) → 기존 9개 도구의 F3 surface는 v1 baseline 그대로 | 호스트 전면 노출 (legacy path) | 저-중 | v1: documented residual; v2: F-V2-6 (DockerBackend proxy 마이그레이션) — Follow-up |
| **R4** KaliExecAdapter parser 품질 저하 | finding 손실 | 중 → 저 | A1.6 — parser 의무 + 3개 도구 모두 mandatory |
| **R5** docker-py 옵션이 silent fail | hardening 미적용 | 저 | mock 검증 + integration `docker inspect <cid>` 어서션 |
| **R6** 기존 9개가 KaliBackend로 회귀 | 회귀 + 안전 가정 깨짐 | 저 | A4.3 회귀 테스트 (Pre-mortem F4) + registry CODEOWNERS |
| **R7** SBOM 생성 도구 가용성 변화 | 분기별 빌드 실패 | 저 | Makefile fallback chain (`syft` → `docker sbom` → fail) |
| **R8** **(신규)** socket-proxy 자체 취약점 | 우회 가능성 | 저 | proxy 이미지도 digest pin, version 추적, 분기별 점검 |
| **R9** **(신규, F5)** Planner LLM이 kali_* 를 generic-cheaper로 선호 | typed adapter 사용 비율 하락 | 중 | Planner prompt 명시 + weekly telemetry alert (-20%p) |

## Verification Steps

### CI 게이트 (모든 PR)
1. `pytest backend/tests/unit/test_kali_*.py` — 신규 단위 테스트 통과
2. `pytest backend/tests/integration/test_kali_*.py` — 신규 통합 테스트 통과
3. `pytest backend/tests/integration/test_pipeline.py` — 회귀 0건
4. `pytest backend/tests/e2e/test_kali_*.py backend/tests/e2e/test_existing_9_tools_unchanged.py`
5. `bash scripts/lint_kali_dockerfile.sh` — Dockerfile + apt snapshot lint
6. `python -m ruff check backend/app/agents/ backend/app/safety/`
7. `python -m mypy backend/app/agents/kali_exec.py backend/app/agents/kali_whitelist.py backend/app/agents/backends/kali.py backend/app/safety/kali_allowlist.py`
8. `make build-kali` — 빌드 + SBOM 생성 성공
9. **(신규)** AST import-graph 테스트가 `ALLOWED_TOOLS` 단일 소스 유지 검증

### Staging 검증 (PR-9 직후, **정량 임계 — Critic S3-3**)
10. `OSA_KALI_BACKEND_ENABLED=true` 24h 관찰
11. A5.6의 5개 정량 기준 모두 충족 (container_start_failures 24h = 0, socket_proxy_403{create}=0, filter_plan_block 의도 차단만, exec_total{success}≥10, 기존 9개 staging 통과율 100%)
12. typed-adapter 호출 비율이 기준선 대비 -20%p 이내 (F5 dashboard)
13. 미달 시 prod toggle 차단, 재현·root-cause·재시도

### Prod 검증
14. 첫 1주 daily KaliBackend incident 0건
15. 첫 분기말 재빌드 cron 성공 + digest+apt snapshot diff 리뷰 통과 (CODEOWNERS 승인)

---

## ADR — Architecture Decision Record

### Decision
**KaliBackend (DockerBackend의 sibling) + KaliExecAdapter (공유 클래스) + per-slug ToolEntry 3종 (kali_gobuster/kali_sqlmap/kali_nikto) + single-source 화이트리스트 (`safety/kali_allowlist.py`) + 확장된 `filter_plan_steps`/`risk_filter` + B+ hardening + docker-socket-proxy 사이드카 + Kali digest + apt snapshot 2축 핀 + mandatory parser + CODEOWNERS + feature flag 이중 enforcement** 의 parallel coexistence v1.

### Drivers
- D1: 도구 커버리지 확장 속도
- D2: 측정 가능한 안전 동등성 (3층 defense in depth, 모두 코드+테스트로 강제)
- D3: 감사·재현성 (image digest + apt snapshot + SBOM + CODEOWNERS)

### Alternatives Considered
- **O2 (Full migration)**: 9개 모두 KaliBackend로 — 거절. 회귀 위험·parsing 손실·PR 비대.
- **O3 (Single `kali_exec` ToolEntry, iter-1 초안)**: tier/risk_band 붕괴로 Critic이 거절. **per-slug 다중 ToolEntry** 가 동일 코드 비용에 안전 게이트 보존.
- **O4 (Debian-slim base)**: 거절 — R4 Contrarian 응답 ("Kali 전용 패키지 필요"). ADR 각주(아래)에 패키지 예시.

> **각주 (ADR fair-rejection 근거, Critic 권장)**: Kali repo-only 또는 Kali에서 *최신 빌드/패치*가 제공되어 Debian apt와 동치성이 떨어지는 패키지 예시 — `kali-tools-web` 메타패키지가 묶는 `whatweb`/`dirb`/`joomscan` Kali 빌드, `wfuzz` Kali 패치 버전, `crackmapexec`(→`netexec`) Kali 패키지, `bloodhound`/`bloodhound-python` Kali 빌드, `pacu` Kali 패키지. v2+ 후보 도구가 여기 다수 포함됨.

### Why Chosen (O1, iter-2)
1. 기존 9개 도구 회귀 위험 = 0
2. 신규 도구 확장 비용을 *코드 → 설정*으로 낮춤
3. 안전 약화 trade-off가 *3층 hardening 계약 + 코드+테스트 강제*로 보강. Critic S1-1/S1-2/S1-3 이 식별한 silent-allow / 단일 소스 위반 / tier 붕괴 모두 iter-2에서 해소.
4. v2에서 점진 마이그레이션이 가능 (옵션으로만)

### Consequences
- (+) v1 PR 시리즈가 9개로 분할되어 각각 회귀 면적 통제 가능
- (+) Kali 이미지 1개 + apt 한 줄로 후속 신규 도구 확장 (CODEOWNERS 통해 안전 검토)
- (+) docker-socket-proxy 도입으로 F3 threat가 측정 가능한 mitigation 보유
- (−) DockerBackend + KaliBackend two-track 유지 비용 + hardening 진화 시 동기화 필요
- (−) Kali 이미지 크기 ≤3GB로 슬림 이미지보다 큼
- (−) socket-proxy 사이드카가 새 의존성 → digest pin + runbook으로 통제
- (−) per-slug 등록(O1)이 LLM tool-call surface를 늘림 (3개 신규 tool) — 비용보다 tier/risk_band 보존 가치 우위

### Follow-ups (v2+)
- F-V2-1: nikto/sqlmap parser plugin 정확도 retrospective + 개선
- F-V2-2: passive_recon tier 일부 도구 KaliBackend로 점진 마이그레이션 (Principle 5 보존)
- F-V2-3: AppArmor/SELinux 호스트 LSM 프로파일
- F-V2-4: 신규 Kali 도구 추가 (위 ADR 각주의 후보들)
- F-V2-5: `KALI_ALLOWED_CAPS` 확장 필요한 도구 등장 시 ADR + security 검토
- F-V2-6: **(iter-3 Architect)** DockerBackend (기존 9개 도구) 도 socket-proxy 경유로 마이그레이션 검토 — R10 residual 해소. v1에서 보존된 baseline 위에 점진 도입.
- F-V2-7: **(iter-3 Architect P3 옵션)** middleware TOCTOU 방어 심화 — `POST /containers/{id}/start` 시점에 image ID 재검증 정수 비교

---

## Changelog
- 2026-05-24 (iter-1): Planner 초안 (RALPLAN-DR + Deliberate Pre-mortem + Expanded Test Plan).
- 2026-05-24 (iter-2): Architect T1/T2/T3 + Critic S1-1/S1-2/S1-3/S2-1..S2-5/S3-1..S3-3/S4-1..S4-2 모두 반영. 핵심 변경: (a) 단일 `kali_exec` → **per-slug 3종 ToolEntry** (sqlmap=active_exploit), (b) `filter_plan_steps`/`risk_filter` 명시적 확장, (c) `safety/kali_allowlist.py` 단일 소스 + import-graph 테스트, (d) `docker-socket-proxy` 사이드카 의무 도입, (e) apt snapshot 핀 + CODEOWNERS, (f) parser plugin mandatory, (g) deny-flag set/path denylist 확장, (h) `KALI_ALLOWED_CAPS=frozenset()` 강제, (i) staging 정량 임계, (j) Pre-mortem F4/F5 추가, (k) Principle 2를 *3층 명시*로 재정의, Principle 4를 *단일 소스 위치*로 재정의, Principle 5를 *sibling, not subclass*로 재정의.
- 2026-05-24 (iter-3): Architect P0/P1/P2 + Critic 10-edit minimum set 반영. (a) **A2.5 proxy endpoint allowlist enumerate** — `containers.get()`/`stop()`/`cleanup()` 가 사용하는 `GET /containers/{id}/json` 포함 6종, (b) **PR-7 two-client 패턴** — DockerBackend는 `from_env()` 유지(host socket 직접, Principle 5 보존), KaliBackend만 `KALI_DOCKER_HOST=tcp://docker-socket-proxy:2375` 경유, (c) **A2.3 필드 경로 pin** — `step["config"]["tool_slug"]`/`step["config"]["args"]` + risk_filter.py:65 정확한 분기 삽입 위치, (d) **A2.4 AST 스캔 scope 확장** — `agents/**` + `tests/fixtures/**` 재귀 검사, binary path literal 차단, (e) **A2.1.(e) negative assertion ≥6** — endpoint 7종 (positive 1 + negative 6), (f) **PR-5.5 apt snapshot spike** — 1-hour 결정 문서를 PR-6 진입 gate로, (g) **A1.2 `cap_add=[]` 명시** (subset-of-empty 모호성 제거 — N2), (h) **F3 mitigation에서 미검증 `IMAGE_FILTER` 제거** — Python middleware 단일 경로로 확정 (N4), (i) `DOCKER_TLS_VERIFY=""`/`DOCKER_CERT_PATH=""` 명시 unset (Architect P0), (j) middleware 단일 endpoint 검사 (`POST /containers/create` body만).
