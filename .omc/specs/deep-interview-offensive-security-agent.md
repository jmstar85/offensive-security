# Deep Interview Spec: Offensive Security Agent Platform

## Metadata
- Interview ID: osa-interview-001
- Rounds: 10
- Final Ambiguity Score: 14.5%
- Type: greenfield
- Generated: 2026-04-11
- Threshold: 20%
- Status: PASSED

## Clarity Breakdown
| Dimension | Score | Weight | Weighted |
|-----------|-------|--------|----------|
| Goal Clarity | 0.9 | 0.40 | 0.36 |
| Constraint Clarity | 0.85 | 0.30 | 0.255 |
| Success Criteria | 0.8 | 0.30 | 0.24 |
| **Total Clarity** | | | **0.855** |
| **Ambiguity** | | | **14.5%** |

## Goal
보안 컨설팅 회사가 고객사 환경(클라우드/온프레미스)을 대상으로 AI 기반 자율 침투테스트를 수행하는 웹 플랫폼. 컨설턴트가 자연어로 타깃 환경을 프롬프트하면, AI 오케스트레이터(Claude API)가 자동으로 타깃 분석 → 적절한 에이전트 선택 → 공격 시나리오 생성 → 스캔/익스플로잇 실행까지 전체 파이프라인을 자율 수행. 사람은 실시간 모니터링만 하며, 결과는 웹 대시보드 + PDF 리포트로 제공.

## Constraints

### Technical Stack
- **Backend:** Python (FastAPI) — API 서버 + AI 오케스트레이터
- **Frontend:** React — 웹 UI (대시보드, 모니터링, 리포트)
- **Database:** PostgreSQL — 사용자, 프로젝트, 리포트 저장
- **AI/LLM:** Claude API — 자연어 해석, 공격 계획 수립, 도구 오케스트레이션
- **Infrastructure:** Docker 컨테이너 — 각 에이전트를 Docker로 패키징, docker-compose로 오케스트레이션

### Pentest Agent Tools (4개 + 플러그인 확장)
1. **Nmap** — 네트워크 스캔, 포트 디스커버리, 서비스 탐지
2. **Nuclei (ProjectDiscovery)** — 템플릿 기반 취약점 스캐너 (CVE, 웹 취약점, misconfiguration)
3. **Metasploit Framework** — 취약점 익스플로잇, 포스트 익스플로잇
4. **PyRIT (Microsoft)** — AI Red Teaming, AI 모델 보안 테스팅
- **플러그인 구조:** 추가 도구를 쉽게 통합할 수 있는 어댑터 패턴

### User Management
- 단일 팀 기본 인증 (JWT)
- 고객사 프로젝트 단위 관리
- 멀티테넌트는 MVP 이후

### Safety Guards (MVP 필수)
- **화이트리스트:** 사용자 지정 타깃 IP/도메인 외 공격 차단
- **Kill Switch:** 실행 중 즉시 중단 버튼
- **위험도 제한:** DoS, 데이터 파괴 등 고위험 익스플로잇 자동 차단
- **감사 로그:** 모든 액션 상세 로깅 (법적 증거 보전)

### AI Orchestration Mode
- **완전 자율 (Full Auto):** 스캔 → 취약점 분석 → 익스플로잇까지 AI가 전체 수행
- 사람은 실시간 모니터링만 수행
- 안전장치 범위 내에서 자율 판단

## Non-Goals
- 멀티테넌트 (MVP 이후)
- 모바일 앱
- Kubernetes 배포 (MVP는 Docker Compose)
- 클라우드 VM 동적 프로비저닝
- 보안 교육/훈련 모드
- 커스텀 익스플로잇 개발 기능

## Acceptance Criteria
- [ ] 컨설턴트가 웹 UI에 로그인 가능 (JWT 인증)
- [ ] 새 프로젝트(고객사) 생성 가능
- [ ] 자연어로 타깃 환경 프롬프트 입력 가능 (예: "AWS EC2 3대, Ubuntu, 192.168.1.0/24")
- [ ] AI 오케스트레이터가 프롬프트를 해석하여 공격 계획 자동 수립
- [ ] 최소 4개 에이전트(Nmap, Nuclei, Metasploit, PyRIT) Docker 컨테이너 실행
- [ ] AI가 적절한 에이전트를 자동 선택하여 순차/병렬 실행
- [ ] 실시간 진행상황 모니터링 (웹소켓 기반 실시간 로그/상태)
- [ ] 화이트리스트 범위 밖 타깃 공격 차단 동작
- [ ] Kill Switch로 실행 중 즉시 중단 가능
- [ ] 고위험 익스플로잇 자동 차단 동작
- [ ] 모든 액션 감사 로그 기록
- [ ] 결과 리포트 웹 대시보드 표시
- [ ] 결과 리포트 PDF 다운로드 가능
- [ ] 클라우드 테스트 환경(AWS/GCP) 대상 전체 파이프라인 데모 성공

## Assumptions Exposed & Resolved
| Assumption | Challenge | Resolution |
|------------|-----------|------------|
| 여러 도구를 한 번에 통합해야 한다 | 1개 도구만으로 MVP 가능한가? (Contrarian) | 최소 3개+, 4개 도구로 확정 |
| 사람이 세부 설정을 해야 한다 | 완전 자율 vs 수동 오케스트레이션? | 완전 자율 (Full Auto) 선택 |
| 멀티테넌트가 필요하다 | MVP에서 필요한가? (Simplifier) | 단일 팀으로 충분, 멀티테넌트는 이후 |
| 안전장치 없이 자율 실행 가능 | 법적/윤리적 안전장치 필수 | 4가지 안전장치 모두 MVP에 포함 |

## Technical Context
- Greenfield project — 빈 디렉토리에서 시작
- Python 생태계가 보안 도구(PyRIT, Metasploit API, python-nmap, Nuclei)와 가장 호환성 높음
- Docker 기반으로 각 에이전트를 격리 실행하여 보안성 확보
- Claude API를 오케스트레이터 LLM으로 사용하여 자연어 → 공격 계획 변환

## Ontology (Key Entities)

| Entity | Type | Fields | Relationships |
|--------|------|--------|---------------|
| User | core domain | id, email, password_hash, role, team_id | User belongs to Team, User creates Projects |
| Team | core domain | id, name, created_at | Team has many Users |
| Client Project | core domain | id, name, client_name, target_description, status, created_by | Project has many PentestSessions |
| Pentest Session | core domain | id, project_id, prompt, plan, status, started_at, ended_at | Session has many AgentExecutions |
| AI Orchestrator | core domain | llm_provider, model, system_prompt | Orchestrator manages Sessions |
| Agent Execution | core domain | id, session_id, agent_type, container_id, status, started_at, ended_at, output | Execution belongs to Session |
| Pentest Agent | supporting | name, docker_image, capabilities, risk_level | Agent runs in AgentExecution |
| Attack Scenario | supporting | id, session_id, steps, risk_assessment | Scenario belongs to Session |
| Target Environment | supporting | id, project_id, ip_ranges, domains, cloud_provider, whitelist | Target belongs to Project |
| Report | core domain | id, session_id, summary, findings, risk_score, pdf_url | Report belongs to Session |
| Audit Log | supporting | id, timestamp, actor, action, target, details | Log records all actions |

## Ontology Convergence

| Round | Entity Count | New | Changed | Stable | Stability Ratio |
|-------|-------------|-----|---------|--------|----------------|
| 1 | 5 | 5 | - | - | N/A |
| 2 | 7 | 2 | 0 | 5 | 71% |
| 3 | 8 | 1 | 0 | 7 | 88% |
| 4 | 8 | 0 | 0 | 8 | 100% |
| 5-7 | 9-11 | gradual | 0 | stable | 89-100% |
| 8-10 | 11 | 0 | 0 | 11 | 100% |

## Interview Transcript
<details>
<summary>Full Q&A (10 rounds)</summary>

### Round 1
**Q:** 이 플랫폼의 주요 사용자는 누구이며, 핵심 목표는 무엇인가요?
**A:** 보안 컨설팅 서비스
**Ambiguity:** 78% (Goal: 0.4, Constraints: 0.1, Criteria: 0.1)

### Round 2
**Q:** 컨설턴트가 이 플랫폼을 사용하는 전형적인 워크플로우는?
**A:** 자율 AI 오케스트레이션
**Ambiguity:** 68% (Goal: 0.65, Constraints: 0.1, Criteria: 0.1)

### Round 3
**Q:** 침투테스트 에이전트들은 어디에서 실행되나요?
**A:** Docker 컨테이너
**Ambiguity:** 60% (Goal: 0.65, Constraints: 0.35, Criteria: 0.1)

### Round 4 [Contrarian Mode]
**Q:** 단 하나의 도구만 통합해도 충분한 MVP가 된다면?
**A:** 3개+ 에이전트 + 기본 UI
**Ambiguity:** 52% (Goal: 0.65, Constraints: 0.35, Criteria: 0.4)

### Round 5
**Q:** 플랫폼의 기술 스택 선호도?
**A:** Python 중심 (FastAPI + React + PostgreSQL + Claude API)
**Ambiguity:** 44% (Goal: 0.65, Constraints: 0.6, Criteria: 0.4)

### Round 6 [Simplifier Mode]
**Q:** MVP에서 사용자 관리 기능은 어느 수준이 필요한가요?
**A:** 단일 팀 + 기본 인증
**Ambiguity:** 38% (Goal: 0.65, Constraints: 0.6, Criteria: 0.6)

### Round 7
**Q:** AI 오케스트레이터의 자율성 범위는?
**A:** 완전 자율 (Full Auto)
**Ambiguity:** 30% (Goal: 0.85, Constraints: 0.6, Criteria: 0.6)

### Round 8
**Q:** 완전 자율 모드의 안전장치는?
**A:** 전체 포함 (화이트리스트 + Kill Switch + 위험도 제한 + 감사 로그)
**Ambiguity:** 24% (Goal: 0.85, Constraints: 0.8, Criteria: 0.6)

### Round 9
**Q:** MVP 완성 판단을 위한 구체적 데모 시나리오는?
**A:** 클라우드 환경 데모 (AWS/GCP 대상 전체 파이프라인)
**Ambiguity:** 19.5% (Goal: 0.85, Constraints: 0.8, Criteria: 0.75)

### Round 10
**Q:** 구체적 오픈소스 도구 조합은?
**A:** 조합 C: Nmap + Nuclei + Metasploit + PyRIT (플러그인 구조)
**Ambiguity:** 14.5% (Goal: 0.9, Constraints: 0.85, Criteria: 0.8)

</details>
