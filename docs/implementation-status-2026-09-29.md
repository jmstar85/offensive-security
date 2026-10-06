# 계획 대비 구현 점검 — 2026-09-29

현재 작업 폴더의 계획 문서, 실제 호출 경로, 테스트를 대조한 결과다. 애플리케이션 코드는 변경하지 않았다. 배포 서버나 외부 점검 대상에 대한 실제 실행 성공을 확인한 보고서는 아니다.

**판정: 기본 플랫폼·자율 실행 경로·새 세션 UI는 상당 부분 구현되었지만, 최신 Interactive Flow 계획의 영속 이벤트 전달·다중 worker·서버 주도 인터뷰 복구는 미완성이다. XBOW 확장 기능과 운영 승인도 완료로 판단할 수 없다.**

## 1. 기준 계획과 상태 기록

| 기준 | 해석 |
|---|---|
| [Interactive Flow Rev 7](../.omc/plans/ralplan-osa-flow-interactive-pentest-v1.md), 4행 | 2026-07-17 실행 승인 명시. 현재 진척 판단의 최신 기준. A: 세션 진입 수정, C: 영속 이벤트, B: 자동 인터뷰, D: 다중 worker. |
| [팀 인수인계](../.omc/handoffs/team-plan.md), 3–13행 | A → migration 013 → C → B → D 순서, 최초 Wave 1은 A로 기록. 이후 실제 코드는 B/C 일부까지 존재한다. |
| [New-flow](../.omc/plans/ralplan-osa-newflow-pentagi-ui-v1.md), 3행 | 문서에는 “Not executed”지만 관련 UI·API·모델 라우팅은 구현됨. 상태 표기가 낡았다. |
| [인증 화면·Claude OAuth](../.omc/plans/ralplan-osa-mainpage-redesign-anthropic-oauth-v1.md), 3–19행 | pending approval 표기. 화면 구현과 Claude 구독 OAuth 미구현을 분리해서 평가. |
| [자율 실행 Milestone 1](../.omc/plans/ralplan-osa-xbow-autonomous-v1.md), [XBOW 전체](../.omc/plans/ralplan-osa-xbow-v1.md) | 단일 대상 자율 실행 경로와 전체 XBOW 기능의 완성은 별개다. |
| [PentAGI v4](../.omc/plans/osa-pentagi-port-autopilot-v4.0.md), 6–10행 | 이전 v3 계획의 일부를 대체한다. 옛 파일명이 없다는 이유만으로 이전 계획 전체를 미구현으로 계산하지 않았다. |

README와 `.omc/RESUME-CONTEXT.md`의 74/85개 테스트·구현 목록은 현 상태를 반영하지 않는다. 계획별 상태가 동기화되지 않아 전체 완료율을 단일 백분율로 계산하지 않았다.

## 2. 어디까지 구현되었는가

| 영역 | 현재 수준 | 확인한 구현 / 남은 범위 |
|---|---|---|
| 기본 플랫폼 | 구현 기반 존재 | 인증·사용자·프로젝트·세션·승인·도구 registry·보고서·감사·범위/위험/종료 통제 코드 및 관련 테스트 존재. 실제 배포 smoke는 이번에 미실행. |
| 자율 실행 Milestone 1 | 핵심 경로 연결됨 | `service.py:374,487,526,545`에서 Performer와 Pentester 실행. 역할별 LLM 선택, 공통 안전 실행 helper, 기존 결정론적 실행 경로 보존. Docker 실제 E2E는 별도 검증 필요. |
| New-flow UI | 대부분 구현 | provider/model/역할별 override, preset/template, Automation/Assistant 선택 및 API 전달. `PentestWorkflow.tsx:439,790,836,900`, `pentest_sessions.py:49`. |
| 별도 Assistant 모드 | 구현 | 세션별 Assistant 채팅/API 존재 (`PentestWorkflow.tsx:540,1052`, `pentest_sessions.py:406`). `/flow`의 Assistant 탭은 별도 sidechannel 기능으로 여전히 placeholder (`AssistantTab.tsx:15`). |
| 인증 화면·브랜딩 | 구현 | Login/Register/ResetPassword 공통 AuthHero, 테마/모션 대응, PNG favicon/아이콘. 계획의 SVG 형식과는 달라졌으며 시각 QA는 미실행. |
| Claude 구독 OAuth | 미구현 | 전용 PKCE·refresh·구독 토큰 사용 경로 없음. 일반 OAuth client ID는 placeholder (`credentials.py:312,360`). Copilot device flow 구현과 구분해야 함. |
| Kali v1 | 핵심 코드 구현, 빌드/운영 미완 | 독립 Kali backend, gobuster/sqlmap/nikto, allowlist, hardening 존재. 현재 lint 실패 및 실제 재현 빌드/soak 검증 부족. |
| XBOW 전체 | 부분 구현 | Coordinator/Understanding/Family/OOB 모델·화면·일부 함수 존재. family 실행, 확장 도구, MITM/headless/OOB 실제 실행과 비용 통제는 미완. |
| 운영·GA | 완료 증거 부족 | 체크리스트·runbook·metrics·workflow 파일은 있으나 여러 경로가 선언/placeholder 단계. GA hard gate 8개 모두 미체크. |

## 3. 최신 Interactive Flow 계획의 실제 위치

| 단계 | 판정 | 근거와 미비점 |
|---|---|---|
| Group A — 신규 세션 진입 | 대부분 구현 | 프로젝트 자동 선택/picker (`FlowIndex.tsx:59`), 가시적 submit 오류 (`PentestWorkflow.tsx:441`), 60초 timeout (`api/client.ts:4`), 별도 트랜잭션의 credential-failure pause 저장 (`workflow_service.py:369`). 실제 브라우저 A6 smoke 증거는 미확인. |
| Group C — 영속 모니터링 | 부분 구현, 설계와 차이 큼 | `013_flow_replay.py:31`은 terminal_lines와 step_order만 추가. 계획의 task_events, agent_turn_events, pending_asks, device_flow_states, run_leases는 없음. Agents는 MsgChain, Tasks는 draft+execution overlay 사용. |
| Group B — 자동 인터뷰 | 부분 구현, 동작 불일치 | Q1은 브라우저 `useEffect`가 `/messages`를 호출 (`PentestWorkflow.tsx:603`). 서버 create는 draft 반환만 수행 (`pentest_sessions.py:254`). durable kickoff/re-drive/sweeper 없음. 20% 기준은 실제 Flow 경로에 적용되지 않음. |
| Group D — 다중 worker | 핵심 미구현 | `events.py:37`의 메모리 queue를 `ws.py:101`에서 구독. DB catch-up tailer 없음. Copilot 상태도 `_oauth_pending` dict (`credentials.py:88,477`). DB 연결 예산 검사와 계획의 Postgres max_connections=200 배포 설정 없음. |

구체적으로 남은 계약은 다음과 같다.

- **실행 중 독립 commit:** `terminal_sink.py:27,122`는 실행 트랜잭션에 flush만 한다. 자율 경로의 role 경계 commit은 있지만 (`performer.py:337,387`), 계획한 500ms/배치 단위 별도 pool·side-session commit은 없다. 실행 도중 다른 연결에서 항상 로그를 읽을 수 있다는 보장이 아니다.
- **무손실 재접속:** `useTopicWebSocket.ts:40,53`에 after_seq cursor가 없고 단순 재접속한다. 계획의 history→live 이어받기 및 중복/유실 방지 tailer가 없다.
- **자율 실행 Tasks 복원:** `performer.py:613`의 새 step은 order/status만 포함. `TasksTab.tsx:70,82,108`은 draft 행을 기준으로 갱신하므로 동적으로 생성된 도구 행의 상세/재생이 불완전하다.
- **인터뷰 영속 질문:** `pending_asks`, 원자적 kickoff_pending→kickoff_running, worker 재시작 후 재구동 경로가 없다. 화면의 최초 요청은 서버 보장형 자동 시작을 대체하지 못한다.
- **turn cap 후 계속 답하기:** `workflow_service.py:419`에서 409, `PentestWorkflow.tsx:1112`에서 입력 잠금. 최신 AC-3.5의 계속 답하기 선택지가 없다.
- **의도적으로 나중인 항목:** Phase-2 LISTEN/NOTIFY 최적화 및 v2 shadow-table 통합은 계획 자체가 후속으로 둔다. v1의 필수 tailer 미구현과 구분한다.

## 4. 우선 처리할 미비점

### P0 — 접근 통제와 실제 상태 전이

1. **대화 이력의 권한·마스킹 공백.** `performer.py:381`은 원문 result.messages를 저장한다. `pentest_sessions.py:669–688`의 msgchains 조회는 로그인만 확인하고 해당 세션의 소유 팀 확인 없이 원문 messages를 반환한다. WS의 scrubbed/raw 분리만으로 저장 이력 보호가 완성되지 않는다. 세션/메시지 REST 권한과 마스킹을 실제 사용자·팀 조합으로 검증해야 한다.
2. **화면의 20% 기준과 실제 35% 판정 불일치.** `workflow_service.py:196`의 helper는 20%를 쓰지만 실제 Flow 호출은 `AmbiguityLoop`로 가며 (`:473,506,512`), `ambiguity_loop.py:51–57`은 35% 설정을 직접 읽는다. 이번에 해당 소스 함수를 분리 실행해 autoblock=True, ambiguity=0.30에서 ready_for_review 반환을 확인했다. 기존 `test_interview_autoblock.py`는 별도 helper만 검사한다.
3. **Rescope와 실행 상태 불일치.** 실행 서비스는 status=running을 저장 (`service.py:101`)하지만 Rescope는 executing만 허용 (`rescope_service.py:121`). 호출 실패는 `performer.py:812`에서 처리되어 정상 pause로 이어지지 않는다. paused_for_rescope 결과도 일반 abort_reason으로 처리되어 failed로 종료될 수 있다 (`service.py:551,402,419`). 전체 실행 경로의 pause→승인→재개 검증이 필요하다.

### P1 — 최신 계획 완결과 운영 통제

4. **C→D1→B의 필수 기반 마무리.** 별도 세션 영속 sink, append-only Tasks/Agents 이벤트, cursor/tailer, run lease, retention, rollback 표시, durable kickoff를 구현하고 실제 2개 이상 worker로 검증해야 한다. 이미 존재하는 migration 013의 이름만으로 계획 C0 완료로 처리하면 안 된다.
5. **비용 제한의 실제 연결.** 일일 사용량 함수가 항상 0을 반환 (`services/budget_guard.py:81–99`). 다른 2단계 budget guard의 layer_a_check/layer_b_check는 app 내 호출이 발견되지 않았다 (`orchestrator/llm/budget_guard.py:83,90`). 설정값과 테스트 helper의 존재를 운영 비용 상한 보장으로 볼 수 없다.
6. **깨진 Kali 빌드.** `bash scripts/lint_kali_dockerfile.sh` 실패를 재현. lint는 KALI_APT_REPO_URL 주입을 요구 (`scripts/lint_kali_dockerfile.sh:47`), Dockerfile은 rolling sources 사용 (`docker/kali/Dockerfile:36`). `make build-kali`의 선행 조건이라 표준 빌드가 차단된다. 추가로 Dockerfile의 ffuf version ARG가 Makefile에서 전달되지 않는다 (`Dockerfile:24,47`, `Makefile:35`).
7. **회귀 검증 자동화.** 현재 4개 GitHub workflow에는 일반 backend pytest·frontend build·migration gate가 없다. 실제 UI 생성→인터뷰→승인→실행 E2E, 다중 worker 및 restart 검증을 추가해야 한다. 현재 full-session Playwright 테스트는 mock 탭/행 렌더 위주다 (`frontend/e2e/test_full_pentest_session_v4.spec.ts:106–140`).

### P2 — 전체 XBOW 및 후속 기능

8. **등록만 된 확장 도구.** xsstrike/dalfox/ffuf/commix가 모두 KaliGobusterAdapter를 가리킴 (`registry.py:317–359`). 실제 어댑터는 gobuster slug/parser를 강제 (`kali_exec.py:40,61`). MITM/headless/interactsh는 stub execution ID의 로그만 읽는 경로로 실제 생성 호출이 빠져 있다 (`mitmproxy.py:59–67`, `headless_browser.py:58–65`, `interactsh.py`).
9. **Family·Understanding 확장.** 실제 topological 실행은 generator/pentester/reporter 중심 (`service.py:526–545`). Family row 생성과 family별 실행 스케줄링은 다르다. LLM build_understanding/derive_plan_of_work도 app 내 실제 호출을 찾지 못했다. 전체 XBOW의 13 vulnerability vector와 현재 target-kind 5종 모델은 범위가 다르다 (`roles/seed_xbow.py:18–35`).
10. **메모리 검색 연결.** seed parser는 YAML 최상위 description/entries만 처리 (`knowledge/seed_memory.py:75–99`)하는데 현재 지식 파일은 SKILL.md와 다른 구조의 dorks YAML이다. Pentester가 광고하는 search_in_memory는 delegator의 adapter/role 분기와 연결되지 않는다 (`service.py:527`, `runtime_delegator.py:64,68,130`).
11. **Claude 구독 OAuth 및 운영 자동화.** 구독 인증은 별도 미구현 범위. canary helper의 실제 session 적용, key rotation workflow의 echo 대체, sidecar digest 갱신 파일 쓰기, 유효한 기본 digest와 재현 빌드/soak 증거도 남았다.

## 5. 이번에 실행한 검증

| 검증 | 결과 | 해석 |
|---|---|---|
| backend 선택 suite: unit/orchestrator/api/ast/infra/regression/integration | **1,134 passed, 6 failed, 3 skipped**, 10.50초 | 전체 테스트 트리 전부는 아님. safety/fuzz/perf/e2e/load 디렉터리는 이 집계에 포함하지 않았다. |
| credential pause·terminal replay·autoblock·AST·infra 집중 검사 | **69 passed, 1 skipped** | 위 suite와 중복되는 결과이므로 합산하지 않는다. |
| per_role_routing 단독 | **13 passed** | 전체 실행의 3건 실패가 단독 실행에서는 사라짐. |
| provider_response_normalization + per_role_routing | **13 passed, 3 failed** | 테스트 간 간섭을 좁힌 조합에서 재현. normalization의 module reload(`:38`)로 기존 class import에 대한 mock과 실제 class가 달라지는 문제와 일치한다. 실패는 의도하지 않은 Anthropic 연결 시도로 나타남. |
| Python 소스 AST parse | **381개 파일, 오류 0** | 구문 검사만 해당. runtime/typecheck 성공 의미 아님. |
| Kali Dockerfile lint | **실패**, exit 1 | `Dockerfile must reference ${KALI_APT_REPO_URL} in the apt sources line` |
| frontend build/Playwright | **미실행** | node_modules 부재. 이번 진단에서는 의존성을 설치하지 않았다. |
| 실제 Docker/LLM 대상 실행·다중 worker·migration round-trip·soak | **미검증** | 테스트 수로 대체할 수 없는 완료 조건. |

6건 실패 중 3건은 get_adapter가 Docker socket에 연결하려다 실패한 환경 의존 테스트다. 나머지 3건은 위 module reload 순서 간섭으로 재현된다. 따라서 이를 모두 제품 결함으로 집계하지 않았고, 전체 suite green이라고도 판단하지 않았다.

실행 환경의 `.venv/bin/python`은 없어진 Homebrew 경로를 가리켰다. 기존 venv를 변경하지 않고 설치된 uv Python 3.13과 기존 site-packages를 사용했다. 재현 명령은 다음과 같다.

```sh
cd backend
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=.:.venv/lib/python3.13/site-packages \
OSA_E2E_DOCKER_SCANME=0 OSA_E2E_DVWA_URL='' OSA_E2E_JUICE_URL='' \
/Users/minsung.jung/.local/bin/python3.13 -m pytest -q -p no:cacheprovider \
  tests/unit tests/orchestrator tests/api tests/ast tests/infra \
  tests/regression tests/integration --disable-warnings --tb=short
```

원 실행 로그: `/tmp/osa-implementation-audit-pytest.log`; 간섭 재현 로그: `/tmp/osa-audit-test-isolation.log`. 임시 경로이므로 영구 보관은 보장하지 않는다.

## 6. 완료 판단과 권장 순서

1. 저장 대화 접근 통제, 실제 인터뷰 기준, rescope 상태 전이를 먼저 정리한다.
2. 최신 계획의 영속 sink/이벤트 테이블 → tailer/다중 worker 상태 공유 → 서버 인터뷰 재구동을 순서대로 완성한다.
3. 비용 집계·Kali 빌드·테스트 격리를 정리하고 실제 Docker + DB + UI의 통합 검증을 남긴다.
4. 전체 XBOW 확장 도구/family, Claude OAuth 및 운영 자동화를 별도 완료 기준으로 추적한다.
5. `docs/security/ga-readiness-checklist.md:18–33`의 8개 hard gate와 서명 증거를 채운 뒤 운영 완료를 판단한다. 현재 저장소에서는 모두 미체크다.

Git의 `.git/objects`가 없어 commit/history/working-tree diff는 확인할 수 없었다. 본 보고서는 현재 파일의 상태를 평가하며 배포 상태나 병합 상태를 추정하지 않는다.
