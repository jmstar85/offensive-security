# 구현 Phase 패킷 — 독립 세션 실행 가이드

이 디렉터리의 각 `phase-*.md`는 **서로 다른 세션/모델이 컨텍스트 없이 집어서 독립 구현**할 수 있는 자족적 작업 패킷이다. 상위 맥락은 [재수립 계획](../implementation-plan-2026-10-05.md)과 [점검 보고서](../implementation-status-2026-09-29.md) 참조.

## 목표 이미지 (한 줄)
사용자가 웹에서 인가된 대상·범위를 입력 → AI Coordinator 범위 인터뷰 → 자율 멀티에이전트가 실제 보안도구를 격리 컨테이너에서 실행(정찰 자동·공격 승인게이트) → 안전통제·실시간 모니터링·비용상한·보고서까지 운영 수준으로 수행하는 **OSA→XBOW 자율 모의침투 플랫폼**.

## 범위 결정 (사용자 확정)
- **이번 목표 = Phase 0 → 1 → 2** (레포 무결성 + P0 보안 + Interactive Flow 핵심 자율루프).
- **Phase 3 → 4 = 추적 후속** (운영통제 / 전체 XBOW·OAuth·GA). 문서는 준비돼 있으나 착수는 Phase 2 완료 후.

## 의존성 DAG (순서 강제)
```
Phase 0 (repo·baseline)  ─┐
                          ├─▶ Phase 1 (P0 security) ─▶ Phase 2 (interactive flow) ─▶ [Phase 3] ─▶ [Phase 4]
```
- Phase 0은 모든 것의 선행. 이미 **git 복구는 완료**(아래 "현재 상태") 됐으므로 Phase 0의 잔여는 테스트 격리 수정뿐.
- Phase 1의 세 작업(1a/1b/1c)은 상호 독립 → 한 세션 안에서 병렬 가능 또는 3세션 분할 가능.
- Phase 2는 C(2a) → D1(2c) → B(2d) 순서 강제, 2b(cursor/tailer)는 2a 이후.

## 현재 상태 (2026-10-05 기준)
- 브랜치 `feat/kali-coexistence-v1` @ `ca78c58`, `origin`과 동기, `git fsck` 깨끗.
- **`.git/objects` 유실은 복구됨** (fetch로 pack 복원). 보고서 간극 분석은 이 커밋 기준으로 유효.
- 작업트리 미커밋 87건은 대부분 `.omc/` 운영상태·세션 JSON·일부 프론트 미세수정 — 핵심 백엔드 무관.

## 각 세션 공통 시작 절차
1. **브랜치**: 각 Phase는 전용 브랜치에서 작업. 네이밍 `feat/phase-<n>-<slug>` (예: `feat/phase-1-p0-security`). 선행 Phase 브랜치(또는 머지된 integration)에서 분기.
   ```sh
   cd /Users/minsung.jung/myproject/offensive-security
   git fetch origin
   git checkout feat/kali-coexistence-v1   # 또는 직전 Phase 머지본
   git checkout -b feat/phase-<n>-<slug>
   ```
2. **백엔드 테스트** (venv 경로가 깨져 있어 uv python 사용):
   ```sh
   cd backend
   PYTHONDONTWRITEBYTECODE=1 \
   PYTHONPATH=.:.venv/lib/python3.13/site-packages \
   OSA_E2E_DOCKER_SCANME=0 OSA_E2E_DVWA_URL='' OSA_E2E_JUICE_URL='' \
   /Users/minsung.jung/.local/bin/python3.13 -m pytest -q -p no:cacheprovider \
     tests/unit tests/orchestrator tests/api tests/ast tests/infra \
     tests/regression tests/integration --disable-warnings --tb=short
   ```
   - 환경의존 Docker 테스트 3건(`get_adapter`가 Docker socket 연결)은 소켓 없으면 실패 — 제품결함 아님. Docker 데몬이 있으면 통과.
3. **프론트엔드**: `cd frontend && npm install && npm run build` (node_modules 없음 — 먼저 설치).
4. **마이그레이션**: 신규 테이블은 `backend/alembic/versions/`에 014+ 번호로 추가. 현재 최신 `013_flow_replay.py`.

## 파일 포인터 규약
각 패킷의 `파일:라인`은 보고서(2026-09-29) 기준. **라인 번호는 드리프트할 수 있으니 구현 전 해당 파일에서 실제 위치를 재확인**하고 심볼/함수명으로 앵커를 잡는다. 파일 경로는 안정적.

## Lore commit 규약 (전 Phase 공통, 필수)
모든 커밋은 결정 맥락을 trailer로 보존한다. 형식:
```
<type>(<scope>): <명령형 요약>

<본문: 왜 이렇게 했는지, 제약·근거>

Constraint: 이 결정을 강제한 활성 제약
Rejected: 고려했으나 버린 대안 | 버린 이유
Directive: 후속 수정자를 위한 경고/지시 (선택)
Confidence: high | medium | low
Scope-risk: narrow | moderate | broad
Not-tested: 테스트로 못 덮은 엣지/시나리오
```
- type: feat/fix/refactor/test/docs/chore. 사소한 커밋은 trailer 생략 가능하나, Phase 작업 커밋은 최소 `Constraint`/`Confidence`/`Scope-risk` 포함.
- 한 커밋 = 한 논리 단위(원자적). 각 Phase 패킷 하단에 그 Phase용 예시 커밋 제공.

## 완료 판정 (전 Phase 공통)
코드 + 통과하는 테스트(1회 실행 green) + 실제 경로 수동검증 3요소 충족. 보안/상태전이는 사용자×팀 조합·pause→승인→재개를 실제로 돌려 확인. 테스트 수만으로 완료 선언 금지.

## 모델 매핑 (성능 최우선)

비용·속도보다 **구현 정확성**을 최우선으로 배정한다. 배정 원칙:
- **비가역적 정확성·불변식·프로세스 경계 횡단·동시성·in-repo 패턴 없음** → 최고 추론 레인 **deep-high (`gpt-6-astra`)**.
- **읽고 결정 가능한 백엔드/로직/알고리즘·in-repo 패턴 존재** → 강력 실행 레인 **deep-low (`gpt-6.1-sol`)**; 기계적으로 명확한 건 **`gpt-6.1-sol-fast`**.
- **프론트엔드(React)** → frontend 스킬 로드한 deep-low (`gpt-6.1-sol`).
- **리뷰는 저자와 다른 레인**(프로젝트 규칙: self-approve 금지) → architect/critic **(`claude-opus-4-8` / `claude-fable-5-1`)**, 보안 Phase는 security-reviewer.

| Phase·작업 | 성격 | 구현 모델(성능 최우선) | 리뷰 모델 | 근거 |
|---|---|---|---|---|
| 0-b 테스트 격리 | 디버깅, settleable | **deep-low `gpt-6.1-sol`** (debugging 스킬) | architect `claude-opus-4-8` | module reload 간섭 가설검증, in-repo |
| 1-a authz+마스킹 | 멀티테넌트 보안 불변식 | **deep-high `gpt-6-astra`** | **security-reviewer** + architect | 팀 경계 정확성, 저장/반환 경계 횡단 |
| 1-b 임계치 단일화 | 기계적 통일 | **deep-low-fast `gpt-6.1-sol-fast`** | architect `claude-fable-5-1` | 설정 1곳 통일, 리스크 낮음 |
| 1-c rescope 상태전이 | 상태기계 정확성 | **deep-high `gpt-6-astra`** | architect `claude-opus-4-8` | running/executing·양 레인 횡단, failed 오분류 |
| 2-a 이벤트테이블·side-sink | 프로세스 경계 계약·불변식 | **deep-high `gpt-6-astra`** | architect `claude-opus-4-8` | in-repo 패턴 없음, 별도 pool commit 보장 |
| 2-b cursor/tailer(+React) | 알고리즘+프론트 | **deep-low `gpt-6.1-sol`** (frontend 스킬) | architect `claude-opus-4-8` | 2a 이후 settleable, seq/dedup 알고리즘 |
| 2-c 다중worker/lease | 동시성 정확성 | **deep-high `gpt-6-astra`** | architect `claude-opus-4-8` | run lease·연결예산 불변식, 2+ worker 실검증 |
| 2-d durable 인터뷰 | 원자적 상태전이 | **deep-high `gpt-6-astra`** | architect `claude-opus-4-8` | kickoff_pending→running 원자성, 재구동 |
| 3-a budget 실연결 | 백엔드 집계 | **deep-low `gpt-6.1-sol`** | architect `claude-fable-5-1` | 집계·호출경로 삽입, settleable |
| 3-b Kali 빌드 | docker/build 설정 | **deep-low `gpt-6.1-sol`** | architect `claude-fable-5-1` | lint↔Dockerfile 정합, ARG 전달 |
| 3-c CI 회귀 | workflow 작성 | **deep-low-fast `gpt-6.1-sol-fast`** | architect `claude-fable-5-1` | 기존 명령 기반 게이트 추가 |
| 4-a 확장 도구 어댑터 | 백엔드, in-repo 패턴 | **deep-low `gpt-6.1-sol`** | architect `claude-fable-5-1` | 기존 어댑터 패턴 복제 |
| 4-b Family/Understanding | 오케스트레이션 메커니즘 | **deep-high `gpt-6-astra`** | architect `claude-opus-4-8` | family 스케줄링·LLM 전개 설계 |
| 4-c 메모리 검색 | parser+연결 | **deep-low `gpt-6.1-sol`** | architect `claude-fable-5-1` | YAML parser·delegator 분기 연결 |
| 4-d Claude 구독 OAuth | 보안 프로토콜 | **deep-low `gpt-6.1-sol`** + document-specialist(docs) | **security-reviewer** | PKCE 표준 문서화됨, 보안 리뷰 필수 |
| 4-e 운영 자동화·GA | ops·증거 | **deep-low `gpt-6.1-sol`** | architect `claude-opus-4-8` | canary/rotation/digest, 8 hard gate |

> 주의: deep-high/deep-low는 이 환경의 `task` 레인이다. 프로젝트의 OMG/OMC 오케스트레이션을 쓰면 deep-high↔`@architect`+강모델, deep-low↔`@executor`(opus), 보안리뷰↔`@security-reviewer`로 대응시킨다. 모델명이 환경에서 바뀌면 "레인(성격)"을 기준으로 동급 최상위를 고른다.

## 모델 매핑 (성능 최우선)

비용·속도보다 **구현 정확성을 최우선**으로 배정한다. 원칙:
- **비가역적 정확성·불변식·프로세스 경계 횡단·동시성·in-repo 패턴 없음** → 최고 추론 레인 **deep-high (`gpt-6-astra`)**.
- **읽고 결정 가능한 백엔드/로직/알고리즘·in-repo 패턴 존재** → 강력 실행 레인 **deep-low (`gpt-6.1-sol`)**, 기계적으로 명확한 건은 **`gpt-6.1-sol-fast`**.
- **리뷰는 저자와 다른 레인** → architect/critic **(`claude-opus-4-8` / `claude-fable-5-1`)**, 보안 Phase는 `@security-reviewer`. (프로젝\�score 규칙: 저자≠리뷰어, 동일 컨텍스트 자가승인 금지.)
- 프론트엔드 비중 작업(2b)은 동일 레인에서 `frontend` 스킬 로드.

| Phase·작업 | 성ꈁ | 구현 모델(성능 최우선) | 리뷰 모델 | 근거 |
|---|---|---|---|---|
| 0-b 테스트 격리 | 디버깅 | deep-low `gpt-6.1-sol` | architect | 가설구동, settleable |
| 1-a authz+마스킹 | 보안·불변식 | **deep-high `gpt-6-astra`** | `@security-reviewer` | 멀티테넌트 정확성, 경계 횡단 |
| 1-b 임계치 통일 | 기계적 | deep-low-fast `gpt-6.1-sol-fast` | architect | 단일 소스로 통일, 저위험 |
| 1-c rescope 상태전이 | 상태기계 정확성 | **deep-high `gpt-6-astra`** | architect | 양 레인 횡단 pause/승인/재개 불변식 |
| 2-a 이벤트테이블·side-session | 계약·불변식 | **deep-high `gpt-6-astra`** | architect | 프로세스 경계 계약, in-repo 패턴 없음 |
| 2-b cursor/tailer(+React) | 알고리즘+UI | deep-low `gpt-6.1-sol` (+`frontend`) | architect | 2a 이후 settleable |
| 2-c 다중 worker/lease | 동시성 | **deep-high `gpt-6-astra`** | architect | 동시성 정확성을 불변식으로 증명 |
| 2-d durable 인터뷰 | 원자성 | **deep-high `gpt-6-astra`** | architect | 원자적 kickoff 상태전이 |
| 3-a budget 연결 | 백엔드 | deep-low `gpt-6.1-sol` | architect | 집계 로직, settleable |
| 3-b kali 빌드 | 빌드·docker | deep-low `gpt-6.1-sol` | architect | 구성 수정 |
| 3-c CI 회귀 | 인프라 | deep-low-fast `gpt-6.1-sol-fast` | architect | 명확한 workflow |
| 4-a 확장 어댑터 | 백엔드 | deep-low `gpt-6.1-sol` | architect | in-repo 어댑터 패턴 존재 |
| 4-b family/understanding | 오케스트레이션 메커니즘 | **deep-high `gpt-6-astra`** | architect | 메커니즘 설계, 패턴 없음 |
| 4-c 메모리 검색 | 백엔드 | deep-low `gpt-6.1-sol` | architect | parser+연결, settleable |
| 4-d Claude 구독 OAuth | 보안 프로토콜 | deep-low `gpt-6.1-sol` (+`document-specialist`) | `@security-reviewer` | PKCE 표준·문서 존재, 보안리뷰 필수 |
| 4-e 운영 자동화·GA | 운영 | deep-low `gpt-6.1-sol` | architect + `@security-reviewer` | 기존 파일 구체화 |

대체(레인 미가용 시): deep-high→`claude-opus-4-8`, deep-low→`gpt-5.6-sol`/`claude-opus-4-8`. OMG/OMC 래퍼 사용 시 deep-high≈`@architect`로 설계 후 `@executor`(opus) 구현, deep-low≈`@executor`, 리뷰≈`@code-reviewer`/`@security-reviewer`.
