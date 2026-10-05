# Phase 0 — 레포·베이스라인 무결성  [상태: git복구 완료 / 잔여: 테스트격리]

> 선행: 없음 (모든 Phase의 기반). 공통 절차·Lore commit 규약은 [README](./README.md) 참조.
> **권장 구현 모델(성능 최우선)**: 0-b = deep-low `gpt-6.1-sol`(debugging 스킬) / 리뷰 architect `claude-opus-4-8`. 상세는 [README 모델 매핑](./README.md#모델-매핑-성능-최우선).

## 목표 슬라이스
디스크 상태를 추적 가능하게 만들고(완료), suite가 1회 실행으로 안정적으로 green이 되도록 테스트 격리 결함을 제거한다. 이게 돼야 이후 Phase의 커밋·CI·회귀검증이 신뢰 가능.

## 작업

### 0-a. git 레포 복구 — ✅ 완료 (2026-10-05)
- 증상: `.git/objects` 통째 유실로 "not a git repository".
- 조치: `mkdir -p .git/objects/{pack,info}` → `git fetch origin feat/kali-coexistence-v1`. `git fsck --connectivity-only` 깨끗.
- 결과: `feat/kali-coexistence-v1` == `origin` == `ca78c58`. **추가 작업 불필요.** (기록만: 재발 시 동일 절차.)

### 0-b. 테스트 격리 결함 수정 — 🔲 잔여
- **증상**: 전체 선택 suite에서 6건 실패 중 3건이 테스트 간 간섭. `tests/.../test_provider_response_normalization.py`의 **module reload**(보고서 `:38`)가 `per_role_routing`과 섞이면, 기존에 import된 class와 reload 후 class의 identity가 달라져 mock이 실제 class에 안 붙고 의도치 않은 Anthropic 연결 시도로 실패.
- 단독 실행 시: `per_role_routing` 13 passed. 조합 실행 시: 3 failed 재현.
- **할 일**:
  1. reload 기반 테스트를 격리(예: `importlib.reload` 제거하고 fixture로 설정 주입, 또는 해당 모듈 테스트를 subprocess/독립 세션으로 분리, 또는 mock 대상을 reload 후의 class 참조로 교정).
  2. mock이 "실제로 사용되는 class 객체"를 패치하도록 보장(모듈 경로 패치 vs import된 심볼 패치 구분).
  3. 환경의존 Docker 3건(`get_adapter` → Docker socket)은 소켓 없을 때 skip되도록 마커/가드 확인(제품결함 아님, green 집계에서 분리).
- **완료기준**: README의 백엔드 테스트 명령을 **순서·조합 무관하게 1회 실행** 시 비(非)Docker 테스트 전부 green. Docker 3건은 소켓 유무에 따라 pass/skip, 간섭성 3건 소멸.

## 검증
```sh
# 조합 재현 확인: 둘을 같이 돌려도 green
cd backend && PYTHONPATH=.:.venv/lib/python3.13/site-packages /Users/minsung.jung/.local/bin/python3.13 -m pytest -q -p no:cacheprovider \
  tests/.../test_provider_response_normalization.py tests/.../test_per_role_routing.py --tb=short
# 전체 선택 suite green(Docker 제외분)
```
+ 변경 파일 LSP 진단 0 error.

## Lore commit 예시
```
test(orchestrator): isolate provider-normalization reload so per_role_routing mocks hold

importlib.reload rebuilt the provider class, so mocks patched the stale symbol
and per_role_routing tried a real Anthropic call. Patch the post-reload class
and scope the reload to a fixture teardown.

Constraint: 기존 venv/site-packages 변경 금지, uv python 3.13 사용
Rejected: 전체 suite를 -p no:randomly로 고정 | 간섭 원인을 숨길 뿐 근본 해결 아님
Confidence: high
Scope-risk: narrow
Not-tested: Docker socket 존재 환경에서의 get_adapter 3건(별도 환경 필요)
```

## 다음 Phase 핸드오프
Phase 0 머지 후 `feat/phase-1-p0-security`를 이 브랜치에서 분기.
