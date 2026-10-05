# Phase 1 — P0 보안·정확성 (접근통제·상태전이)  [상태: 활성 목표]

> 선행: Phase 0. 세 작업(1a/1b/1c)은 상호 독립 → 병렬/분할 가능. 공통 절차·Lore commit은 [README](./README.md).

## 목표 슬라이스
목표 이미지의 **#7 접근통제**와 **#4 안전체인(상태전이 정확성)**, **#1 인터뷰 기준 일관성**을 확보한다. 기능 확장(Phase 2+)보다 앞서야 하는 보안/정확성 결함.

---

## 1-a. 대화 이력 접근통제 + 마스킹
- **현재 결함**:
  - `backend/.../performer.py:381` — 원문 `result.messages`를 그대로 저장(마스킹 없음).
  - `backend/.../api/.../pentest_sessions.py:669–688` — msgchains 조회가 **로그인만 확인**, 해당 세션의 **소유 팀 검증 없이** 원문 messages 반환. WS의 scrubbed/raw 분리만으로는 저장 이력 보호 미완.
- **할 일**:
  1. msgchains/세션/메시지 REST 조회에 **세션→프로젝트→소유 팀** 권한 검사 추가(요청자가 해당 팀 소속인지). 타 팀 접근은 403/404.
  2. 저장 시 또는 반환 시 민감정보 마스킹 적용(기존 WS scrubber 재사용 가능하면 동일 로직을 저장 경로에도).
- **완료기준**: 사용자 A(팀1)가 만든 세션 메시지를 사용자 B(팀2)가 REST로 못 읽음을 **실제 사용자×팀 조합 테스트**로 증명. 마스킹된 필드가 저장/반환 양쪽에서 가려짐.

## 1-b. 모호도(ambiguity) 임계치 단일화
- **현재 결함**: `workflow_service.py:196` helper는 **20%** 사용, 실제 Flow 호출은 `AmbiguityLoop`로 가며(`:473,506,512`) `ambiguity_loop.py:51–57`은 **35%** 설정을 직접 읽음. 화면 표기(20%)와 실제 판정(35%) 불일치. 기존 `test_interview_autoblock.py`는 별도 helper만 검사.
- **할 일**: 실제 Flow 경로(`AmbiguityLoop`)에 적용되는 **단일 임계치**로 통일(설정 1곳에서 읽기). 화면/문서 표기도 그 값과 일치. helper와 loop가 같은 소스를 쓰도록.
- **완료기준**: 실제 Flow 경로를 타는 테스트에서 임계치 전후로 `interviewing`/`ready_for_review` 전이가 단일 기준으로 결정됨. (참고: 보고서가 autoblock=True, ambiguity=0.30에서 ready_for_review 반환을 해당 소스함수 분리실행으로 확인한 바 있음 — 이 불일치를 없앨 것.)

## 1-c. Rescope 상태 전이
- **현재 결함**:
  - 실행 서비스는 `status=running` 저장(`service.py:101`)인데 Rescope는 `executing`만 허용(`rescope_service.py:121`) → 호출 실패.
  - 실패가 `performer.py:812`에서 처리돼 정상 pause로 이어지지 않음.
  - `paused_for_rescope` 결과가 일반 `abort_reason`으로 처리돼 `failed`로 종료될 수 있음(`service.py:551,402,419`).
- **할 일**: running/executing 상태 어휘 정합, rescope 호출이 정상 **pause→승인→재개** 흐름을 타도록, `paused_for_rescope`를 `failed`와 구분해 올바른 paused 상태로 종료.
- **완료기준**: 전 실행 경로(결정론·자율 양 레인)에서 rescope 요청 → pause → 승인 → 재개가 성공하고, pause 결과가 failed로 오분류되지 않음을 테스트+실경로로 확인.

---

## 검증 (공통)
- README 백엔드 테스트 명령 green + 1a/1b/1c 각각의 신규 회귀 테스트.
- 변경 파일 LSP 진단 0 error.
- 1a는 사용자×팀 실조합, 1c는 pause→승인→재개 실행을 수동 확인.

## Lore commit 예시 (1-a)
```
fix(api): enforce team ownership + masking on stored pentest message history

msgchains REST만 로그인 확인하고 소유 팀 검증 없이 원문 messages를 반환했다.
세션→프로젝트→팀 권한 검사를 추가하고 저장/반환 경로에 WS scrubber를 재사용한다.

Constraint: WS의 scrubbed/raw 분리는 유지 — 저장 이력 보호를 추가로 보장
Rejected: 반환 시점에만 마스킹 | 저장 원문이 다른 경로로 유출 가능
Confidence: high
Scope-risk: moderate
Not-tested: 레거시로 이미 저장된 비마스킹 이력의 소급 마스킹(마이그레이션 별도)
```

## 핸드오프
세 작업 머지 후 `feat/phase-2-interactive-flow`로 진행.
