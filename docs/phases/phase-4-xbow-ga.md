# Phase 4 — 전체 XBOW 확장 · OAuth · GA  [상태: 추적 후속]

> 선행: Phase 3. 별도 완료 기준으로 추적. 공통 절차·Lore commit은 [README](./README.md).

## 목표 슬라이스
목표 이미지의 **#3 실도구(확장)**, Family/Understanding 전개, Claude 구독 OAuth, **#8 운영 GA 서명**까지. 전체 XBOW 비전 완성.

## 4-a. 확장 도구 실어댑터
- **현재 결함**: xsstrike/dalfox/ffuf/commix가 모두 `KaliGobusterAdapter`를 가리킴(`registry.py:317–359`), 실제 어댑터는 gobuster slug/parser 강제(`kali_exec.py:40,61`). MITM/headless/interactsh는 stub execution ID 로그만 읽음(`mitmproxy.py:59–67`, `headless_browser.py:58–65`, `interactsh.py`).
- **할 일**: 각 도구별 고유 slug/parser 어댑터 구현, MITM/headless/interactsh 실제 생성·실행 호출.
- **완료기준**: 각 도구가 실제 컨테이너에서 자기 출력으로 실행·파싱됨(E2E 대상 against 인가된 테스트 타깃).

## 4-b. Family/Understanding 전개
- **현재 결함**: 실제 topological 실행이 generator/pentester/reporter 중심(`service.py:526–545`), family row 생성·family별 스케줄링 없음. LLM `build_understanding`/`derive_plan_of_work` 앱 내 호출 없음. 13 vulnerability vector vs 현재 target-kind 5종(`roles/seed_xbow.py:18–35`).
- **할 일**: family row 생성+스케줄링, understanding/plan-of-work LLM 연결, 벡터 5→13 확장.
- **완료기준**: family 기반 실행이 실제로 스케줄·수행되고 understanding이 plan에 반영됨.

## 4-c. 메모리 검색 연결
- **현재 결함**: seed parser가 YAML 최상위 description/entries만 처리(`knowledge/seed_memory.py:75–99`)하나 실제 지식 파일은 dorks YAML 구조. Pentester의 `search_in_memory`가 delegator 분기와 미연결(`service.py:527`, `runtime_delegator.py:64,68,130`).
- **할 일**: dorks YAML 구조용 parser, search_in_memory를 delegator adapter/role 분기에 연결.
- **완료기준**: Pentester가 메모리 검색 결과를 실제로 활용.

## 4-d. Claude 구독 OAuth
- **현재 결함**: 전용 PKCE·refresh·구독 토큰 경로 없음, 일반 OAuth client ID는 placeholder(`credentials.py:312,360`). Copilot device flow와 구분 필요.
- **할 일**: Claude 구독용 PKCE/refresh/토큰 사용 경로 구현.
- **완료기준**: 구독 계정으로 인증→토큰 갱신→LLM 호출 성립.

## 4-e. 운영 자동화 + GA hard gate
- **현재 결함**: canary helper 실제 session 미적용, key rotation workflow가 echo, sidecar digest 갱신 파일쓰기 없음, 유효 기본 digest·재현 빌드/soak 증거 없음. `docs/security/ga-readiness-checklist.md:18–33`의 **8개 hard gate 전부 미체크**.
- **할 일**: canary 실적용, rotation workflow echo 대체, sidecar digest 파일쓰기, 기본 digest 설정, soak 증거 수집, 8 hard gate 충족+서명.
- **완료기준**: GA 체크리스트 8개 서명 증거 완비.

## Lore commit 예시 (4-a)
```
feat(tools): give xsstrike/dalfox/ffuf/commix their own adapters

4개 도구가 모두 KaliGobusterAdapter를 가리켜 gobuster slug/parser로 강제됐다.
도구별 고유 어댑터로 분리하고 실제 출력 파서를 붙인다.

Constraint: 안전 체인(allowlist/위험 게이트) 경유 유지
Rejected: 공통 파서에 분기 추가 | 도구별 출력 포맷 차이로 유지보수 악화
Confidence: medium
Scope-risk: broad
Not-tested: 각 도구의 비정상 종료/타임아웃 출력 파싱
```
