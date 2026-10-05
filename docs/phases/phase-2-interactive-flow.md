# Phase 2 — Interactive Flow 기반 (C → D1 → B)  [상태: 활성 목표]

> 선행: Phase 1. 순서 강제: 2a(C) → 2b(cursor/tailer) → 2c(D1) → 2d(B). 공통 절차·Lore commit은 [README](./README.md).
> **권장 구현 모델(성능 최우선)**: 2-a/2-c/2-d = deep-high `gpt-6-astra`(프로세스 경계 계약·동시성·원자성 불변식) · 2-b = deep-low `gpt-6.1-sol`(frontend 스킬). 리뷰: architect `claude-opus-4-8`. 이 Phase가 가장 난이도 높음 — 최고 레인 집중 배치. 상세 [README 모델 매핑](./README.md#모델-매핑-성능-최우선).

## 목표 슬라이스
목표 이미지의 **#5 실시간 모니터링**(영속 sink·무손실 재접속·다중 worker)과 **#1 서버 보장 인터뷰**를 완성한다. **마이그레이션 013 이름만으로 Group C 완료 처리 금지** — 실제 이벤트 테이블·tailer·run lease가 없다.

핵심 계약(보고서 §3): 실행 중 독립 commit / 무손실 재접속 / 자율 Tasks 복원 / 인터뷰 영속 질문 / turn cap 후 계속 답하기.

---

## 2-a. Group C — 영속 이벤트 sink
- **현재 결함**: `terminal_sink.py:27,122`는 실행 트랜잭션에 flush만. 자율 role 경계 commit은 있으나(`performer.py:337,387`) 계획한 **별도 pool·side-session commit**(500ms/배치)이 없어 "실행 중 타 연결에서 항상 읽힘"이 보장 안 됨. `013_flow_replay.py:31`은 terminal_lines/step_order만 추가 — 계획의 task_events/agent_turn_events/pending_asks/device_flow_states/run_leases 없음.
- **할 일**:
  1. 실행 트랜잭션과 **분리된 side-session**으로 terminal/이벤트를 주기(배치) commit하는 sink.
  2. append-only 이벤트 테이블 신설: `task_events`, `agent_turn_events`, `pending_asks` (+ 2c용 `run_leases`, `device_flow_states`). 신규 마이그레이션 **014+**.
- **완료기준**: 실행이 진행 중인 동안 다른 DB 연결에서 이벤트 행이 순증함을 확인(세션 중 polling 테스트).

## 2-b. Cursor/tailer — 무손실 재접속
- **현재 결함**: `useTopicWebSocket.ts:40,53`에 after_seq cursor 없이 단순 재접속 → history→live 이어받기·중복/유실 방지 tailer 없음. `TasksTab.tsx:70,82,108`은 draft 행 기준이라 동적 생성 도구행 상세/재생 불완전(`performer.py:613`의 새 step은 order/status만).
- **할 일**:
  1. 서버: 이벤트에 단조 증가 seq 부여, `after_seq` 쿼리로 history 재생 → live 구독 핸드오프.
  2. 프론트: `useTopicWebSocket`에 cursor 저장·재접속 시 after_seq 전송, 중복 dedup.
  3. `TasksTab`이 동적 생성된 도구 행의 상세/재생을 반영하도록 이벤트 기반 렌더.
- **완료기준**: 실행 중 WS 끊었다 재접속해도 유실·중복 없이 전체 타임라인 복원(강제 disconnect 테스트).

## 2-c. Group D1 — 다중 worker 상태 공유
- **현재 결함**: `events.py:37` 메모리 queue를 `ws.py:101`이 구독 → DB catch-up tailer 없음. Copilot 상태가 `_oauth_pending` dict(`credentials.py:88,477`). DB 연결 예산 검사·Postgres max_connections=200 배포 설정 없음.
- **할 일**:
  1. 메모리 queue 대신 **DB 기반 이벤트 공유**(2a 테이블 + tailer)로 worker 간 상태 공유.
  2. `run_leases`로 run 소유권 관리, device flow state를 DB 테이블로(dict 대체).
  3. 연결 예산 검사 + 배포 Postgres `max_connections` 설정.
- **완료기준**: **실제 2개 이상 worker**를 띄워 한 세션의 이벤트를 양쪽에서 일관 관찰, lease로 중복 실행 방지됨을 확인.

## 2-d. Group B — durable 서버 주도 인터뷰
- **현재 결함**: Q1을 브라우저 `useEffect`가 `/messages` 호출로 트리거(`PentestWorkflow.tsx:603`), 서버 create는 draft 반환만(`pentest_sessions.py:254`). durable kickoff/re-drive/sweeper 없음. turn cap은 409로 입력 잠금(`workflow_service.py:419`, `PentestWorkflow.tsx:1112`) — AC-3.5의 "계속 답하기" 없음.
- **할 일**:
  1. 서버 보장 kickoff: 원자적 `kickoff_pending → kickoff_running` 전이, `pending_asks` 영속.
  2. worker 재시작 후 미완 인터뷰 재구동 + sweeper(고아 pending 회수).
  3. turn cap 도달 후 사용자가 **계속 답하기**를 선택할 수 있는 경로(AC-3.5): 409 대신 연장/계속 옵션.
- **완료기준**: 화면 트리거 없이도 서버가 인터뷰 Q1을 자동 시작하고, worker 재시작 후에도 재구동되며, turn cap 후 계속 답하기가 동작함을 실경로로 확인.

---

## 검증 (공통)
- README 백엔드 테스트 green + 각 작업 회귀 테스트. 마이그레이션 up/down round-trip 확인.
- **2c는 실제 2+ worker**, 2b는 강제 재접속, 2d는 worker restart를 수동 실행해 증거 확보.
- 프론트 변경은 `npm run build` 통과 + 실제 브라우저에서 실행→재접속 확인.

## Lore commit 예시 (2-a)
```
feat(flow): add append-only event tables + side-session sink for live replay

실행 트랜잭션 flush만으로는 진행 중 타 연결에서 로그가 안 보였다. task_events/
agent_turn_events/pending_asks(+run_leases/device_flow_states)를 신설하고 별도
세션에서 배치 commit한다. 마이그레이션 014.

Constraint: 실행 트랜잭션과 분리된 pool — role 경계 commit에 의존하지 않음
Rejected: Phase-2 LISTEN/NOTIFY 최적화 선반영 | 계획이 후속으로 둔 범위
Confidence: medium
Scope-risk: broad
Not-tested: 고부하 soak에서의 배치 commit 지연 상한
```

## 핸드오프
Phase 2 완료 시 "이번 목표" 달성. 이후 [Phase 3](./phase-3-ops-controls.md)(후속) 착수 판단.
