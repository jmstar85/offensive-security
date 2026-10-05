# Phase 3 — 운영 통제 (비용·빌드·CI)  [상태: 추적 후속]

> 선행: Phase 2. 착수는 "이번 목표(Phase 0~2)" 완료 후. 세 작업(3a/3b/3c) 상호 독립. 공통 절차·Lore commit은 [README](./README.md).

## 목표 슬라이스
목표 이미지의 **#6 비용 통제**와 **#8 운영 GA**의 전제(재현 빌드·CI 회귀). 운영 진입 전 필수 통제.

## 3-a. Budget guard 실연결
- **현재 결함**: `backend/app/orchestrator/llm/budget_guard.py:80`이 `return 0.0`(일일 사용량 항상 0). `layer_a_check`(`:83`)/`layer_b_check`(`:90`)가 앱 내 호출되지 않음. `services/budget_guard.py:81–99`의 일일 사용량도 0. 설정값·테스트 helper 존재 ≠ 운영 비용 상한 보장.
- **할 일**: 일일/세션별 실제 사용량 집계(LLM 호출 기록 → 합산), layer_a_check(사전 추정)/layer_b_check(실제 한계 marginal)를 실제 LLM 호출 경로에 삽입해 상한 초과 시 차단.
- **완료기준**: 모의 사용량이 상한을 넘으면 실제 호출 경로가 차단됨을 테스트로 증명(0 반환 제거 확인).

## 3-b. Kali 빌드 수정
- **현재 결함**: `scripts/lint_kali_dockerfile.sh:47`은 `${KALI_APT_REPO_URL}`를 apt sources에서 요구하지만 `docker/kali/Dockerfile:36`은 digest-pinned 베이스의 rolling sources(deb822) 사용 → lint 실패, `make build-kali` 차단. 추가로 ffuf version ARG가 Makefile에서 Dockerfile로 전달 안 됨(`Dockerfile:24,47`, `Makefile:35`).
- **할 일**: lint와 Dockerfile 소스 방식 정합(둘 중 하나로 통일 — digest-pin을 유지하면 lint의 `${KALI_APT_REPO_URL}` 요구를 provenance 주석/실제 참조로 충족하거나 lint 조건을 현행 방식에 맞게 수정), ffuf ARG를 Makefile에서 전달.
- **완료기준**: `bash scripts/lint_kali_dockerfile.sh` exit 0, `make build-kali` 재현 성공(Docker 환경).

## 3-c. CI 회귀 자동화
- **현재 결함**: 4개 GitHub workflow에 일반 backend pytest·frontend build·migration gate 없음. full-session Playwright은 mock 탭/행 렌더 위주(`frontend/e2e/test_full_pentest_session_v4.spec.ts:106–140`).
- **할 일**: workflow 추가 — backend pytest(README 명령 기반), frontend build, migration up/down gate, **E2E(UI 생성→인터뷰→승인→실행)**, 다중 worker/restart 검증.
- **완료기준**: PR에서 위 게이트가 실제로 돌고 실패를 잡음.

## 검증·Lore commit
- 각 작업 README 기준 테스트 + 해당 게이트 실동작.
- 예시:
```
fix(cost): wire daily usage aggregation + layer_a/b checks into LLM call path

budget_guard가 일일 사용량 0을 반환하고 layer_a/b가 앱에서 호출되지 않아 상한이
무력했다. 호출 기록을 합산하고 사전/한계 검사를 호출 경로에 삽입한다.

Constraint: 기존 결정론 실행 경로 동작 보존
Rejected: 세션별 상한만 | 일일 총량 폭주를 못 막음
Confidence: high
Scope-risk: moderate
Not-tested: 분산 worker 동시 집계의 레이스(2c의 DB 공유 이후 재검토)
```
