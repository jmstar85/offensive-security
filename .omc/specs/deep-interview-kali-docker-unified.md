# Deep Interview Spec: Kali Linux Docker 통합 도구 실행 백엔드 도입 (Parallel Coexistence v1)

## Metadata
- Interview ID: di-kali-docker-unified-2026-05-24
- Rounds: 8
- Final Ambiguity Score: 18%
- Type: brownfield
- Generated: 2026-05-24T08:38:39Z
- Threshold: 0.2 (20%)
- Threshold Source: default
- Initial Context Summarized: no
- Status: PASSED
- Challenge Modes Used: Contrarian (R4), Simplifier (R6)
- Skipped: Ontologist (ambiguity < 0.3 at R8)

## Clarity Breakdown
| Dimension | Score | Weight | Weighted |
|-----------|-------|--------|----------|
| Goal Clarity | 0.95 | 0.35 | 0.3325 |
| Constraint Clarity | 0.88 | 0.25 | 0.22 |
| Success Criteria Clarity | 0.82 | 0.25 | 0.205 |
| Context Clarity (brownfield) | 0.71 | 0.15 | 0.1065 |
| **Total Clarity** | | | **0.864** |
| **Ambiguity** | | | **0.136 (18% — using weakest-component coverage)** |

## Topology
| Component | Status | Description | Coverage / Deferral Note |
|-----------|--------|-------------|--------------------------|
| execution-backend-strategy | active | DockerBackend(기존)과 KaliBackend(신규)의 공존 전략 결정 | Parallel coexistence 채택. KaliBackend는 `ExecutionBackend` ABC를 구현해 기존 DockerBackend와 동등 1급 시민. 기존 9개 typed adapter는 v1에서 손대지 않음. |
| tool-inventory-scope | active | 신규 도구 노출 granularity 및 초기 도구 셋 | 단일 `KaliExecAdapter` + 명시적 화이트리스트. v1 = gobuster + sqlmap + nikto. 도구별 옵셔널 parser 플러그인. |
| safety-sandboxing-model | active | 컨테이너 내부 능력 풍부화에 대한 safety 보강 | seccomp default + `--cap-drop=ALL` + 필요 cap만 add + `--read-only` rootfs + tmpfs + **호출 시점 명령 화이트리스트 shim**. 기존 mem/cpu/pids/network_disabled 유지. |
| build-operator-workflow | active | Dockerfile/태그 핀 정책/빌드 케이던스 | `kalilinux/kali-rolling@sha256:<digest>` 핀 + 분기별 + 온디맨드(보안 이슈) 재빌드. PR 시 SBOM 자동 생성. |

## Goal
이 프로젝트의 공격 도구는 현재 **도구당 별도 Docker 이미지** ([backend/app/agents/backends/docker.py](backend/app/agents/backends/docker.py), 9개 등록 도구 [backend/app/agents/registry.py:55-171](backend/app/agents/registry.py#L55-L171))로 격리 실행됩니다. **도구 커버리지 확장**이 핵심 동기였고, 이를 가장 효율적으로 달성하기 위해:

1. `ExecutionBackend` ABC를 구현하는 **`KaliBackend`** 를 새로 추가하여, 기존 `DockerBackend`와 *공존*시킨다.
2. 단일 **`KaliExecAdapter`** 를 도입하여, 사전 정의된 *화이트리스트*에 등록된 Kali 도구를 임의로 실행 가능하게 한다 (도구별 typed adapter 1:1 매핑 폐기).
3. v1에서는 **gobuster + sqlmap + nikto** 세 개 도구를 화이트리스트 시드로 추가하여 web/api 팔레트의 명백한 gap을 메운다.
4. 기존 9개 typed adapter는 **회귀 0건** 으로 유지하고, 마이그레이션은 v2 이후의 별도 결정으로 미룬다.
5. 컨테이너 내부 능력 풍부화 trade-off는 **B+ tier hardening**(seccomp default + cap-drop ALL + read-only rootfs + tmpfs + 호출 시점 명령 화이트리스트 shim)으로 보강한다.
6. 재현성은 **`kalilinux/kali-rolling@sha256:<digest>` 핀 + 분기별 재빌드** 로 보장한다.

## Constraints
- **Backend coexistence**: KaliBackend는 DockerBackend를 *대체하지 않으며*, 기존 9개 typed adapter의 `docker_image` 참조는 변경되지 않는다.
- **v1 화이트리스트 시드**: `gobuster`, `sqlmap`, `nikto` 세 개. 추가 도구는 후속 PR로 화이트리스트 엔트리 + (선택) parser 플러그인을 추가.
- **Base image**: `kalilinux/kali-rolling@sha256:<digest>`. floating `:latest` 금지. `kali-linux-headless` 대신 *명시적 apt install*(빌드 단계에서 v1 도구만 설치)로 이미지 크기 통제.
- **Tag pinning**: 디지스트 핀 + Dockerfile 내 `ARG KALI_DIGEST` + CI에서 정책 검증.
- **Rebuild cadence**: 분기별 (Q1/Q2/Q3/Q4 초) + 온디맨드 (보안 issue 발생 시).
- **Hardening 계약**: 모든 KaliBackend 컨테이너에 다음 자동 적용 — `security_opt=["no-new-privileges:true", "seccomp=default"]`, `cap_drop=["ALL"]`, `cap_add=` 도구별 최소 cap, `read_only=True`, `tmpfs={"/tmp":..., "/work":...}`.
- **호출 시점 명령 화이트리스트 shim**: `KaliExecAdapter.build_command()` 결과를 exec 직전 `WhitelistShim.verify(command, allowed_binaries, arg_pattern)` 으로 검증, 실패 시 즉시 abort + audit_log 기록.
- **SBOM**: `syft` 또는 `docker sbom`로 PR 시 자동 생성, `.omc/sbom/kali-base-<digest>.json` 으로 저장.
- **기존 safety layer 호환**: [backend/app/safety/](backend/app/safety/) — `risk_filter`, `exploit_allowlist`, `egress_monitor`, `whitelist`는 그대로 통과. KaliExecAdapter의 명령은 기존 risk_filter / target whitelist 검증을 거친 후에야 컨테이너로 전달.
- **Runtime resource limits**: 기존 `mem_limit`/`cpu_quota`/`pids_limit`/`network_disabled` 그대로 적용. KaliExecAdapter는 도구별 `_resource_limits()` 오버라이드를 지원.
- **재현성 임계**: 같은 digest 안에서 같은 입력 → finding 동일성 보장 (CI에 회귀 테스트 추가).

## Non-Goals
- 9개 기존 typed adapter (nmap, nuclei, metasploit, pyrit, passive_recon, subfinder, dnsx, httpx, cloudenum, wappalyzer)를 v1에서 KaliExecAdapter로 마이그레이션하지 않는다.
- v1에서 운영자 인터랙티브 셸(터미널 어태치) 제공하지 않는다. 모든 도구 호출은 어댑터 경로로만.
- AppArmor/SELinux 호스트 LSM 프로파일은 v1 범위 외. 호스트 OS 일관성 요구가 큼.
- Debian-slim 기반 빌드는 v1 범위 외 (R4에서 "Kali 전용 패키지 필요"로 객관적 정당화됨).
- 신규 LLM tool-calling 스키마 변경 — `KaliExecAdapter`는 단일 tool로 LLM에 노출되며, `tool_slug` + `args`를 입력 파라미터로 받는다 (typed adapter 9개와의 LLM 표면 통합은 v2+).
- v1에서는 운영자가 화이트리스트에 도구를 *런타임*에 추가하지 않는다. 화이트리스트는 코드/설정 빌드 타임에 잠금.

## Acceptance Criteria

### 기능 (Functional)
- [ ] `KaliBackend(ExecutionBackend)` 클래스가 [backend/app/agents/backends/](backend/app/agents/backends/)에 추가되고 `DockerBackend`와 동등 인터페이스(`start`/`stream_logs`/`stop`/`cleanup`)를 구현한다.
- [ ] `KaliExecAdapter(AgentAdapter)` 가 `tool_slug`, `args`(list[str]), `expected_output_format` 을 config로 받아 화이트리스트에 등록된 도구를 실행한다.
- [ ] `KaliExecAdapter`의 `agent_type="kali_exec"` 로 [registry.py](backend/app/agents/registry.py)에 추가되고, `palette_for_domain({"web", "api"})` 호출 시 결과에 포함된다.
- [ ] 화이트리스트 시드 3개 도구(`gobuster`, `sqlmap`, `nikto`)가 도구별 arg 스키마 + 출력 parser 플러그인과 함께 등록된다.
- [ ] LLM Planner는 `kali_exec` 도구를 호출할 때 `tool_slug` 파라미터를 화이트리스트 안의 값으로만 채울 수 있도록 강제된다.

### Safety 보강 (Security)
- [ ] KaliBackend로 시작한 모든 컨테이너는 다음 옵션을 *전부* 적용한다 — `no-new-privileges:true`, `seccomp=default`, `cap_drop=["ALL"]`, `read_only=True`, `tmpfs={"/tmp":"size=128m,mode=1777", "/work":"size=512m,mode=1777"}`.
- [ ] 도구별 `cap_add`는 명시 화이트리스트로만 (gobuster=[], sqlmap=[], nikto=[]; v1 기준 모두 비어 있음).
- [ ] `WhitelistShim.verify()` 통과 실패 시 `subprocess.Popen` / `containers.run` 까지 도달하지 않고 `SafetyViolation` 예외 + `audit_log.write({"event":"shim_block", "command":..., "reason":...})`.
- [ ] 동일 digest에서 회귀 테스트: `tests/integration/test_kali_backend_safety.py` — (a) `--security-opt` 누락 시 컨테이너 시작 거부, (b) 화이트리스트 외 명령 거부, (c) tmpfs 밖 쓰기 시도 시 read-only fs 에러.

### 재현성 (Reproducibility)
- [ ] Dockerfile에 `ARG KALI_DIGEST` + `FROM kalilinux/kali-rolling@sha256:${KALI_DIGEST}`. `kali-rolling:latest` 사용 시 CI 실패.
- [ ] `make build-kali` 가 SBOM(`docker sbom` 또는 `syft`)을 `.omc/sbom/kali-base-<digest>-<date>.json` 으로 생성.
- [ ] 같은 digest + 같은 fixture 입력 → finding JSON deepEqual 보장 (CI: `tests/integration/test_kali_reproducibility.py`).

### 회귀 0건 (Backward Compatibility)
- [ ] 기존 9개 typed adapter 통합 테스트 100% 통과 — [backend/tests/integration/test_pipeline.py](backend/tests/integration/test_pipeline.py), [backend/tests/unit/test_agents.py](backend/tests/unit/test_agents.py).
- [ ] `get_adapter("nmap")` / `get_adapter("nuclei")` 등 기존 호출 시 여전히 `DockerBackend`로 인스턴스화 (KaliBackend로 떨어지지 않음).
- [ ] `palette_for_domain` 결과가 v1 전후 동일 항목 + `kali_exec` 추가만 차이.

### 운영 (Operational)
- [ ] 이미지 빌드 시간 ≤ 10분 (v1 도구 3개 + Kali base 기준).
- [ ] 최종 이미지 크기 ≤ 3GB.
- [ ] 분기별 재빌드를 위한 GitHub Actions workflow `.github/workflows/kali-quarterly-rebuild.yml` (cron + workflow_dispatch).

## Assumptions Exposed & Resolved
| Assumption | Challenge | Resolution |
|------------|-----------|------------|
| "Kali full image가 통합으로 더 효과적" | R1: 동기가 무엇인가? | "도구 커버리지 확장" — 따라서 *어떻게* 확장하느냐가 진짜 결정. |
| "통합 이미지는 안전성을 약화시킨다 → 받아들일 수 없다" | R2: 일관성과 능력 풍부화를 받아들일 의향? | 사용자: "OK, 일관성 우선" — 단, R5의 hardening 계약으로 trade-off 보강. |
| "도구당 typed adapter 1:1 매핑이 표준" | R3: granularity 재고 — generic exec? | 단일 `KaliExecAdapter` + 화이트리스트 채택. 새 도구 추가 = 화이트리스트 엔트리. |
| "Kali가 필요하다" (전제) | R4 Contrarian: Debian-slim + apt 화이트리스트로 충분하지 않은가? | 사용자: Kali 전용 패키지(예: kali-tools-* 메타패키지)가 필요 — 객관적 정당성 확인. |
| "전면 대체가 v1 범위" | R6 Simplifier: 9개 모두 한 번에 마이그? | parallel coexistence — 기존 9개 무손상, 신규 1-3개만 새 경로. |
| "Kali rolling은 floating으로 써도 충분" | R7: 감사·재현성 영향? | digest pin + 분기별 재빌드 + SBOM. |
| "초기 도구는 광범위하게" | R8: v1 범위? | gobuster + sqlmap + nikto (web/api 팔레트 핵심 gap). |

## Technical Context (Brownfield Findings)

### 현재 구조 (변경하지 않음)
- **추상화**: [backend/app/agents/base.py:34-56](backend/app/agents/base.py#L34-L56) — `ExecutionBackend` ABC + `AgentAdapter` ABC. 이미 백엔드 플러그형 설계.
- **DockerBackend**: [backend/app/agents/backends/docker.py](backend/app/agents/backends/docker.py) — `docker-py` SDK + `ThreadPoolExecutor`, `/var/run/docker.sock` sibling-container 패턴 ([docker-compose.yml:35](docker-compose.yml#L35)).
- **현재 도구 9개**: [backend/app/agents/registry.py:55-171](backend/app/agents/registry.py#L55-L171) — nmap, nuclei, metasploit, pyrit, passive_recon, subfinder, dnsx, httpx, cloudenum, wappalyzer.
- **Safety layer**: [backend/app/safety/risk_filter.py](backend/app/safety/risk_filter.py), [exploit_allowlist.py](backend/app/safety/exploit_allowlist.py), [egress_monitor.py](backend/app/safety/egress_monitor.py), [whitelist.py](backend/app/safety/whitelist.py) — 논리적 게이트. KaliExecAdapter도 이 계층을 *통과*해야 함.

### 신규 추가
- [backend/app/agents/backends/kali.py](backend/app/agents/backends/kali.py) — `KaliBackend(ExecutionBackend)`. DockerBackend의 `start()`를 확장하여 hardening 옵션을 항상 부여.
- [backend/app/agents/kali_exec.py](backend/app/agents/kali_exec.py) — `KaliExecAdapter(AgentAdapter)`. `tool_slug`/`args`를 검증하여 명령 조립.
- [backend/app/agents/kali_whitelist.py](backend/app/agents/kali_whitelist.py) — `WhitelistShim` + 도구별 arg 스키마 + parser 플러그인 표.
- [docker/kali/Dockerfile](docker/kali/Dockerfile) — `ARG KALI_DIGEST` + `FROM kalilinux/kali-rolling@sha256:${KALI_DIGEST}` + `apt install gobuster sqlmap nikto`.
- [.github/workflows/kali-quarterly-rebuild.yml](.github/workflows/kali-quarterly-rebuild.yml) — cron 분기별 + workflow_dispatch.
- 회귀/통합/안전 테스트 3종 — `tests/integration/test_kali_backend_safety.py`, `test_kali_reproducibility.py`, `test_kali_exec_adapter.py`.

### 잠재 충돌·주의
- [backend/app/orchestrator/executor.py](backend/app/orchestrator/executor.py)에서 `get_adapter(agent_type)` 호출 — `kali_exec` agent_type에 대한 라우팅이 자연스럽게 동작하는지 추가 검증 필요.
- [backend/app/orchestrator/planner.py](backend/app/orchestrator/planner.py) — LLM이 `kali_exec`을 generic으로 호출 가능하게 하려면 tool description 업데이트 필요.

## Ontology (Key Entities)
| Entity | Type | Fields | Relationships |
|--------|------|--------|---------------|
| ExecutionBackend (ABC) | core domain | start, stream_logs, stop, cleanup | implemented by DockerBackend, KaliBackend |
| AgentAdapter (ABC) | core domain | agent_type, docker_image, risk_level, build_command, parse_output | uses ExecutionBackend |
| ToolEntry | core domain | slug, adapter_cls, docker_image, tier, capabilities, applicable_domain_tags, default_risk_band, is_destructive_capable | registered in registry |
| KaliBackend | core domain (new) | + hardening_options | extends ExecutionBackend |
| KaliExecAdapter | core domain (new) | tool_slug, args, expected_output_format | extends AgentAdapter, uses KaliBackend, references WhitelistShim |
| WhitelistShim | core domain (new) | allowed_binaries, arg_pattern, verify() | enforced by KaliExecAdapter |
| Container | external system | mem_limit, cpu_quota, pids_limit, network_disabled, security_opt, cap_drop, read_only, tmpfs | started by ExecutionBackend |
| SafetyLayer | supporting | risk_filter, exploit_allowlist, egress_monitor, whitelist | gates AgentAdapter calls |
| KaliImage | external system (confirmed) | digest, package_set, sbom_path | base for KaliBackend containers |

## Ontology Convergence
| Round | Entity Count | New | Changed | Stable | Stability Ratio |
|-------|-------------|-----|---------|--------|----------------|
| 1 | 7 | 7 | 0 | 0 | N/A |
| 2 | 7 | 0 | 0 | 7 | 100% |
| 3 | 8 | 1 (KaliExecAdapter) | 0 | 7 | 87.5% |
| 4 | 8 | 0 | 0 | 8 | 100% |
| 5 | 9 | 1 (WhitelistShim → 사실상 R3에 잠재했던 entity 명시) | 0 | 8 | 88.9% |
| 6 | 9 | 0 | 0 | 9 | 100% |
| 7 | 9 | 0 | 0 | 9 | 100% |
| 8 | 9 | 0 | 0 | 9 | 100% |

**Ontology 수렴 진단:** R6-R8 3라운드 연속 100% stability → 도메인 모델 완전 수렴. 핵심 entity 9개 모두 spec 안에 명확한 역할로 매핑됨.

## Interview Transcript
<details>
<summary>Full Q&A (8 rounds)</summary>

### Round 0 (Topology)
**Q:** 이 검토가 다루는 top-level component를 다음 4가지로 분해했습니다. 토폴로지가 맞나요? (1) Execution backend 전략 (2) 도구 인벤토리 범위 (3) Safety·Sandboxing 보존 (4) Build·Operator 워크플로우
**A:** 4개 모두 맞음 — 그대로 진행

### Round 1 (Goal Clarity — C1)
**Q:** Kali full Docker 이미지로 가면 "더 효과적"이라고 판단한 근거는 무엇인가요?
**A:** 도구 커버리지 확장
**Ambiguity:** 69% (Goal: 0.40, Constraints: 0.22, Criteria: 0.20, Context: 0.65)

### Round 2 (Goal Clarity — C3)
**Q:** Kali 통합 이미지는 한 도구만 실행해도 컨테이너 내부에 손 닿는 범위의 공격 바이너리가 공존합니다. safety 계층은 "컨테이너 당 한 도구"를 전제로 깔고 있는데, 이 전제가 약해져도 괜찮은가요?
**A:** OK, 일관성 우선 — 전면 대체
**Ambiguity:** 59%

### Round 3 (Goal Clarity — C2)
**Q:** Kali 안의 도구들을 어떤 형태로 노출할까요?
**A:** Generic KaliExecAdapter 중심 (Recommended)
**Ambiguity:** 56%

### Round 4 (Contrarian Mode — C4 Goal)
**Q:** Generic exec + 화이트리스트라면 Debian-slim 기반이 동기를 더 잘 달성할 수 있지 않은가? Kali가 정말 필요한가요?
**A:** Kali 유지 — 특정 Kali 전용 패키지 필요
**Ambiguity:** 47%

### Round 5 (Constraints — C3)
**Q:** Kali 통합 이미지의 넘친 내부 surface를 보완하기 위한 safety 보강 쪽점은 어디까지 둘까요?
**A:** B+ 명령 화이트리스트 shim 추가 (Recommended)
**Ambiguity:** 43%

### Round 6 (Simplifier Mode — C4)
**Q:** 아키텍처가 작동하는지 증명하면서도 회귀 위험을 최소화하는 v1 컷은 무엇인가요?
**A:** Parallel coexistence (Recommended)
**Ambiguity:** 27%

### Round 7 (Constraints — C4)
**Q:** Kali base 이미지의 태그 핀 정책은 무엇으로 하시겠어요?
**A:** Digest pin + 분기별 재빌드 (Recommended)
**Ambiguity:** 23%

### Round 8 (Goal+Constraints — C2)
**Q:** v1에 실을 초기 Kali 도구 셋은 어느 카테고리가 최우선인가요?
**A:** Web 공격 계열 — gobuster + sqlmap + nikto
**Ambiguity:** 18% ✅ (Threshold met)

</details>
