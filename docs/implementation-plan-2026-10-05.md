# 재수립 구현 계획 — 2026-10-05

기준 문서: [점검 보고서 2026-09-29](./implementation-status-2026-09-29.md). 본 계획은 보고서의 미비점을 현재 작업트리와 재대조한 뒤, **목표 이미지(target image)** 를 먼저 못박고 그 간극을 단계별로 닫는 순서로 작성한다.

> **독립 세션 실행용 Phase 패킷**: 각 Phase는 다른 세션/모델이 컨텍스트 없이 집어서 구현할 수 있도록 [`docs/phases/`](./phases/README.md)에 자족적 패킷으로 분할돼 있다(브랜치 전략·의존성 DAG·Lore commit 규약 포함). 이번 목표 = Phase 0~2, Phase 3~4 = 추적 후속.
>
> **git 복구 완료(2026-10-05)**: `.git/objects` 유실은 `origin`에서 fetch로 복구(`ca78c58`, `git fsck` 깨끗). 아래 §1의 git 항목은 해소됨 — 보고서 간극은 이 커밋 기준으로 유효.

---

## 0. 목표 이미지 (구현이 끝났을 때의 모습)

**OSA → XBOW 자율 모의침투 플랫폼.** 한 문장: *사용자가 웹에서 인가된 대상·범위를 입력하면, AI Coordinator가 범위를 명확화하는 인터뷰를 거쳐, 자율 멀티에이전트가 실제 보안도구를 격리 컨테이너에서 돌려 취약점을 찾고(정찰 자동·공격 승인게이트), 안전 통제·실시간 모니터링·비용 상한·보고서까지 운영 수준으로 수행하는 제품.*

구체적 완성 상태(acceptance image):

1. **세션 생성·범위 인터뷰** — 웹 UI에서 대상 + 범위 + 역할별 LLM(provider/model)을 선택해 세션을 만들면, 서버가 보장하는 durable 인터뷰가 자동 시작되고, 모호도(ambiguity) 임계치 하나의 기준으로 `interviewing → ready_for_review`가 판정된다. worker가 재시작해도 인터뷰가 재구동된다.
2. **자율 실행 루프** — 범위 승인 후 Understanding → Plan of Work → Family별 취약점 테스트 → 정찰(자동) → 공격(사람 승인 게이트) → 보고의 위상 순서로 실제 도구가 실행된다.
3. **실도구 실행** — nmap·gobuster·sqlmap·nikto·nuclei·ffuf·dalfox·xsstrike·commix·mitmproxy·headless browser·interactsh(OOB)가 각자 **고유** 어댑터로 Kali/도구 컨테이너에서 실제로 실행된다(현재처럼 전부 gobuster 어댑터를 가리키지 않는다).
4. **안전 체인** — 범위 allowlist, 위험 게이팅, egress 통제, kill 스위치(상태 정확 전파), rescope pause→승인→재개가 전 실행 경로에서 검증된다.
5. **실시간 모니터링 UI** — 실행 중 다른 연결에서도 항상 로그가 보이는 영속 sink, 무손실 재접속(after_seq cursor), 2개 이상 worker 동시 동작, Tasks/Agents 탭이 실제 실행을 반영한다.
6. **비용 통제** — 세션별·일일 budget guard가 실제로 집계·차단한다(항상 0 반환 아님).
7. **접근 통제** — 저장된 대화 이력이 세션 소유 팀 기준으로 권한 검사되고 민감정보가 마스킹된다.
8. **운영 GA** — 재현 가능한 Kali 빌드, CI 회귀(backend/frontend/migration/E2E/multi-worker), 키 로테이션 등 자동화, [GA hard gate 8개](./security/ga-readiness-checklist.md) 서명.

> 범위 경계 결정 필요: 위 1~5·7(핵심 자율 루프+안전+모니터링+접근통제)까지를 "이번 목표"로 하고 6·8(비용/GA)과 Claude 구독 OAuth·전체 XBOW 13벡터는 후속으로 둘지, 아니면 8까지 전부 한 번에 추진할지는 사용자 확정 대기(본 문서 마지막 질문).

---

## 1. 재대조로 확정한 현재 상태

| 확인 항목 | 결과 | 의미 |
|---|---|---|
| git 레포 | **`.git` 손상/부재 — not a git repository** | 커밋·히스토리·CI·원자적 PR 불가. 메모리의 "12 PR 완료·PUSHED"가 디스크에 없음. **최우선 복구 대상.** |
| 마이그레이션 | 001~013까지만 (`013_flow_replay`) | Group C의 task_events/agent_turn_events/pending_asks/device_flow_states/run_leases 테이블 없음 — 보고서 일치. |
| budget_guard | `orchestrator/llm/budget_guard.py:80 return 0.0` | 일일 사용량 항상 0, layer_a/layer_b 앱 내 미연결 — 보고서 일치. |
| Kali lint | lint는 `${KALI_APT_REPO_URL}` 참조 요구, Dockerfile은 rolling sources 사용 | 표준 빌드 차단 — 보고서 일치. |

**결론: 보고서는 현재 작업트리를 정확히 반영한다. 계획은 디스크 상태 기준으로 세운다.**

---

## 2. 단계별 구현 계획

각 Phase는 "완료 = 코드 + 통과하는 테스트 + 실제 경로 수동검증"을 충족해야 다음으로 넘어간다.

### Phase 0 — 레포·베이스라인 무결성 (선행 필수)
- **P0-a. git 레포 복구.** 현재 `.git`가 레포가 아님. 원격(있다면)에서 복구하거나 재초기화해 디스크 상태를 추적 가능하게 만든다. 이게 안 되면 이후 모든 커밋/CI/PR이 불가하므로 최우선.
- **P0-b. 테스트 격리 결함 수정.** `provider_response_normalization`의 module reload(`:38`)가 `per_role_routing`과 섞이면 3건 실패 재현. reload로 인한 class identity 깨짐을 고쳐 suite green을 1회 실행으로 보장.
- **검증:** 선택 suite 전부 통과(환경의존 Docker 3건은 명시적 분리), AST parse 0 오류 유지.

### Phase 1 — P0 보안·정확성 (접근통제·상태전이)
- **P1-a. 대화 이력 접근통제+마스킹.** `pentest_sessions.py:669–688` msgchains 조회에 세션 소유 팀 검사 추가, `performer.py:381` 원문 저장분에 마스킹 적용. 사용자×팀 조합으로 권한·마스킹 회귀 테스트.
- **P1-b. 모호도 임계치 단일화.** `workflow_service.py:196`의 20% helper와 `ambiguity_loop.py`의 35% 설정 불일치 해소. 실제 Flow 경로(`AmbiguityLoop`)에 적용되는 단일 기준으로 통일하고 그 경로로 테스트.
- **P1-c. Rescope 상태 전이.** `service.py:101`(running) vs `rescope_service.py:121`(executing 허용) 정합. pause→승인→재개가 정상 흐르고 paused_for_rescope가 failed로 종료되지 않도록 `service.py:551,402,419`·`performer.py:812` 경로 수정 + 전 경로 pause 검증.

### Phase 2 — P1 Interactive Flow 기반 (C → D1 → B)
- **P2-a. Group C 영속 sink.** 실행 트랜잭션과 **분리된 side-session commit**(배치/주기 단위)으로 terminal/이벤트를 기록. append-only 이벤트 테이블(task_events, agent_turn_events, pending_asks) + 신규 마이그레이션(014+). 실행 중 타 연결에서 항상 읽힘 보장.
- **P2-b. Cursor/tailer 무손실 재접속.** `useTopicWebSocket.ts:40,53`에 after_seq cursor 추가, history→live 이어받기, 중복/유실 방지 tailer(DB catch-up). `TasksTab.tsx:70,82,108`이 동적 생성 도구행도 반영하도록 복원.
- **P2-c. Group D1 다중 worker.** 메모리 queue(`events.py:37`) 대신 DB 기반 공유. run lease, DB-backed device flow state(`credentials.py:88,477`의 dict 대체), 연결 예산·Postgres max_connections 배포 설정. **실제 2개 이상 worker로 검증.**
- **P2-d. Group B durable 인터뷰.** 서버 보장 kickoff(원자적 kickoff_pending→running), pending_asks 영속, worker 재시작 후 재구동, sweeper. turn-cap(409, `workflow_service.py:419`) 후 "계속 답하기"(AC-3.5) 추가.

### Phase 3 — P1 운영 통제
- **P3-a. Budget guard 실연결.** 일일 사용량 실제 집계(`budget_guard.py:80`의 0 반환 교체), layer_a_check/layer_b_check를 실제 LLM 호출 경로에 연결.
- **P3-b. Kali 빌드 수정.** lint와 Dockerfile sources 방식 정합(`lint_kali_dockerfile.sh:47` ↔ `Dockerfile:36`), ffuf version ARG를 Makefile에서 전달(`Makefile:35`). 재현 빌드 성공.
- **P3-c. CI 회귀 자동화.** backend pytest + frontend build + migration gate + E2E(UI 생성→인터뷰→승인→실행) + 다중 worker/restart workflow 추가.

### Phase 4 — P2 전체 XBOW 확장 및 후속
- **P4-a. 확장 도구 실어댑터.** xsstrike/dalfox/ffuf/commix를 고유 slug/parser 어댑터로 분리(`registry.py:317–359`, `kali_exec.py:40,61`). MITM/headless/interactsh 실제 생성 호출 구현(`mitmproxy.py`, `headless_browser.py`, `interactsh.py`).
- **P4-b. Family/Understanding 실행.** family row 생성+스케줄링, LLM build_understanding/derive_plan_of_work 앱 내 연결. 13 벡터로 확장(현재 target-kind 5종).
- **P4-c. 메모리 검색 연결.** dorks YAML 구조용 seed parser(`seed_memory.py:75–99`), search_in_memory를 delegator 분기(`runtime_delegator.py`)에 연결.
- **P4-d. Claude 구독 OAuth.** PKCE/refresh/구독 토큰 경로 구현(Copilot device flow와 분리).
- **P4-e. 운영 자동화 + GA.** canary 실적용, key rotation workflow echo 대체, sidecar digest 파일쓰기, 유효 기본 digest, soak 증거, [GA hard gate 8개](./security/ga-readiness-checklist.md) 서명.

---

## 3. 권장 순서와 근거

1. **Phase 0 먼저.** git 없이는 어떤 작업도 안전히 추적·롤백·배포할 수 없다.
2. **Phase 1(P0)** — 접근통제·인터뷰 기준·rescope는 보안/정확성 결함이라 기능 확장보다 앞선다.
3. **Phase 2(C→D1→B)** — 마이그레이션 013 이름만으로 C 완료 처리 금지. 영속 기반이 있어야 멀티 worker·인터뷰 복구가 성립.
4. **Phase 3** — 비용·빌드·CI는 운영 진입 전 필수 통제.
5. **Phase 4** — 전체 XBOW·OAuth·GA는 별도 완료 기준으로 추적.

## 4. 범위·리스크 메모
- git 복구 방식(원격 존재 여부)에 따라 Phase 0 비용이 크게 달라짐 — 사용자 확인 필요.
- 실제 Docker/LLM/다중 worker/soak는 테스트 수로 대체 불가. 각 Phase 수동 통합검증 포함.
- 메모리의 "완료·PUSHED" 기록과 디스크 불일치 — 복구된 git에서 누락분을 식별해 중복 구현을 피한다.
