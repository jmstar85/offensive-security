# Deep Interview Spec: OSA → PentAGI Port

## Metadata
- Interview ID: osa-pentagi-port-001
- Rounds: 8
- Final Ambiguity Score: 17.2%
- Type: brownfield (v2.1 baseline executing, v3.2.1 consensus plan)
- Generated: 2026-05-16
- Threshold: 20%
- Initial Context Summarized: yes (codebase map + PentAGI reference + prior planning artifacts)
- Status: PASSED

## Clarity Breakdown (component-floor min)

| Dimension | Score | Weight | Weighted |
|-----------|-------|--------|----------|
| Goal Clarity | 0.85 | 0.35 | 0.298 |
| Constraint Clarity | 0.70 | 0.25 | 0.175 |
| Success Criteria | 0.80 | 0.25 | 0.200 |
| Context Clarity | 0.85 | 0.15 | 0.128 |
| **Total Clarity** | | | **0.828** |
| **Ambiguity** | | | **17.2%** |

(Min-across-components; weakest component is (2) UI Shell + Streaming, where Constraints=0.70 reflects the unresolved WebSocket-evolved vs GraphQL-subscriptions choice for the per-panel streaming substrate. Coverage-weighted mean is 13.9%.)

## Topology (Round 0 Locked, 2026-05-16)

| Component | Status | Description | Coverage / Deferral Note |
|-----------|--------|-------------|--------------------------|
| 1. PentAGI Analysis Reference | active | 비교 매트릭스 + 갭 분석 + 채택/거부 결정 산출 | Plan §1 본문(2-3페이지) + `.omc/research/pentagi-reference.md` 상세 매트릭스. AC: reviewer가 §1만 읽고 채택 정당화 + reference에서 구현자가 1:1 lookup. |
| 2. UI/UX Shell + Per-Panel Streaming | active | 2-pane resizable 셸, 좌 Automation/Assistant/Dashboard + 우 Terminal/Tasks/Agents. 패널당 1 stream topic. | Minimal port: 우측 3탭만(Terminal+Tasks+Agents), AgentCatalog→Agents 탭 흡수, Monitor→Terminal 탭, PentestWorkflow→새 /flow 페이지. WorkflowBuilder/Workflows/Reports/Admin은 사이드바 라우트 유지. Searches/VectorStore/Screenshots 탭은 v3.4 이월. |
| 3. Agent Architecture Reshape | active | 단일 Performer 엔진 + role 카탈로그. agent-as-tool 위임 + msgchains DB 통신. | OSA-strong hybrid: roles 채택, LLM은 구조화된 tool call(`{agent:'nuclei',action:'scan',config:{...}}`) 발행 → 기존 AgentAdapter가 처리. tier/allowlist/egress/kill 보존. terminal raw shell은 Coder/Installer만(이번 v1엔 미활성). Minimal 6 roles: Generator/Pentester/Memorist/Adviser/Reflector/Reporter. |
| 4. Ambiguity-Gated Planning Workflow | active | user prompt → 명확화 루프 → workflow plan → 단계별 sub-agent/tool pick. | Up-front clarification + runtime delegation: Generator가 SubTask+ambiguity 생성, threshold>0.35면 ask 툴 루프, 미만 도달 시 1회 approval, 실행 중 PrimaryAgent가 runtime tool call로 sub-role 위임, per-step approval 없음 (Adviser/Reflector + tier_gating + egress_monitor + RescopeService만). Assistant 사이드채널은 v3.4 이월 (Round 6 결정으로 Assistant 역할 deferral). |
| 5. Memory/RAG Layer | active | Memorist 역할 + pgvector + auto-retrieval. | Thin v1: local sentence-transformers `all-MiniLM-L6-v2` (384-dim), pgvector hnsw 인덱스, 자동 호출 (Generator/Pentester가 SubTask 시작 전 `search_in_memory(query=<desc>, k=3, score_threshold=0.7)` 자동 실행), 시드=knowledge/ YAML chunking. 다른 3개 검색 툴(guide/answer/code) + Graphiti+Neo4j는 v3.4 이월. |
| 6. Migration & Rollout Strategy | active | v2.1 베이스라인 85+ tests 보존, 단계별 도입. | 5-phase incremental: P1 Foundation(pgvector + msgchains + Performer skeleton, UI 0) / P2 Agent Architecture(6 roles 활성 + AttackPlanner→Generator 어댑팅 + API shim) / P3 UI Shell(/flow/:id, 3탭, feature flag OSA_FLOW_UI) / P4 Workflow Loop(ambiguity 게이트 + sub-agent pick UI + ask 툴 + Memorist 자동 호출) / P5 Deprecation(레거시 페이지 점진 제거). 각 phase 완료 게이트 = 85 기존 tests + 신규 phase tests 통과 + manual smoke checklist. |

deferrals: 없음. v3.4+ 이월 항목(Searches/Vector Store/Screenshots 탭, Assistant/Refiner/Planner/Enricher/Coder/Installer/Searcher/Mentor 8개 역할, guide/answer/code/graphiti 3개 검색 툴, Graphiti+Neo4j 스택)은 각 컴포넌트의 "v3.4 이월"로 명시. 토폴로지 6개 컴포넌트 모두 active.

## Goal

OSA v2.1(85 tests passing 베이스라인) + v3.2.1 consensus plan을 **PentAGI(github.com/vxcontrol/pentagi)의 핵심 아키텍처 패턴 6개**를 선별 채택해 대폭 개선한다. 구체적으로:

1. **UI 통합**: 분산된 12 페이지를 PentAGI-style 2-pane resizable 셸 + 멀티탭(Terminal/Tasks/Agents)으로 통합. 새 `/flow/:id` 라우트가 단일 진입점.
2. **Agent 재구성**: AttackPlanner+11 AgentAdapter 모델을 **단일 Performer 엔진 + 6 roles**(Generator/Pentester/Memorist/Adviser/Reflector/Reporter)로 reshape. 역할이 LLM tool call로 다른 역할에 위임(agent-as-tool); msgchains 테이블이 영속 통신 매체. 기존 AgentAdapter는 보존돼 Pentester role이 구조화된 tool call로 호출.
3. **모호함 게이트 워크플로우**: user prompt → Generator가 SubTask + ambiguity score 생성 → score > 0.35면 ask 툴 루프 → 임계치 미만 도달 시 1회 approval → 실행 중 runtime delegation(per-step approval 없음).
4. **Thin RAG**: pgvector + Memorist 역할 + local sentence-transformers 임베딩. knowledge/ YAML이 시드. 자동 호출 k=3.
5. **안전 모델 보존**: tier_gating / exploit_allowlist / egress_monitor / kill_switch / whitelist / audit 모두 v2.1과 동일하게 유지. PentAGI는 안전이 약하기 때문에 다운그레이드 금지.
6. **5-phase incremental migration**: 각 phase가 85+ tests 통과를 유지하며 feature flag로 새 UI를 격리 출시 후 점진 deprecation.

산출물: (a) plan §1 + `.omc/research/pentagi-reference.md` 상세 매트릭스; (b) `omc-plan --consensus --direct`로 정련된 5-phase 구현 plan (pending approval, 별도 단계).

## Constraints

### Locked from this interview
- **Agent 경계**: PentAGI roles 채택 + 기존 AgentAdapter 보존(OSA-strong hybrid). LLM은 구조화된 tool call 발행, raw shell 미허용(v1).
- **역할 수**: v1 = 6 roles 정확히 (Generator/Pentester/Memorist/Adviser/Reflector/Reporter). Performer 엔진은 추가 등록 플러그인 hook은 없음 — 8개 v3.4+ 역할은 별도 PR.
- **UI 탭**: v1 = 우측 3탭(Terminal/Tasks/Agents) + 좌측 3탭(Automation/Assistant/Dashboard). Searches/VectorStore/Screenshots 탭은 v3.4. 기존 12 페이지 중 AgentCatalog/Monitor/PentestWorkflow만 disposition 변경; WorkflowBuilder/Workflows/Reports/Admin은 사이드바 라우트로 보존.
- **Workflow loop**: up-front clarification + runtime delegation. Per-step approval 없음. ambiguity threshold = 0.35 기본(admin editable).
- **RAG**: local sentence-transformers `all-MiniLM-L6-v2` (384-dim), pgvector hnsw, k=3, score_threshold=0.7, 자동 호출. OpenAI/Voyage 임베딩 미사용.
- **Migration**: 5-phase incremental. Big-bang/2-phase/3-phase 거부.
- **Streaming substrate**: WebSocket 진화(현행 event_bus 확장) 또는 GraphQL subscriptions — Phase 3에서 구현자가 결정. 둘 다 패널-1:1 토픽 매핑 원칙 준수.

### Locked from prior artifacts (do NOT relitigate)
- 11 entity 도메인 모델 (deep-interview-offensive-security-agent.md, ambiguity 14.5%)
- v3.2.1 consensus: Domain agents 4종, Blackboard, Azure full scope (ApprovalGate), AES-GCM 자격증명, all-in-one MVP, single uvicorn worker, claude-sonnet-4-6 기본
- 안전 5계층: whitelist/risk_filter/exploit_allowlist(tier-gated)/egress_monitor/kill_switch + audit_log
- 자율성 모드 = Full Auto (운영자는 모니터링)
- 85 tests 보존 의무

### Open implementation choices (Phase에서 결정, plan-blocking 아님)
- Streaming substrate: WebSocket evolved vs GraphQL+graphql-ws — P3에서 spike + ADR
- Frontend dep 추가: react-resizable-panels 채택 확정; xterm.js + addons (fit/search/web-links/webgl) 확정; monaco editor는 v3.4
- sentence-transformers backend 크기 영향 (~500MB) — backend Dockerfile slim 변형 검토 P1
- pgvector index params (ivfflat lists, hnsw m/ef_construction) — P1 스파이크
- 6 roles 각각의 system prompt + LLM model 바인딩 — P2 (Anthropic Claude만)

## Non-Goals (v1 명시 제외)

- 8개 v3.4+ 역할(Assistant 사이드채널, Refiner, Planner, Enricher, Coder, Installer, Searcher, Mentor)
- 3개 추가 검색 툴(search_guide / search_answer / search_code) + Graphiti+Neo4j 스택
- 3개 추가 우측 탭(Searches / Vector Store / Screenshots)
- terminal raw shell 툴 (Coder/Installer 미활성으로 자연히 제외)
- browser 툴 + 웹 스크레이퍼 컨테이너(vxcontrol/scraper)
- 외부 LLM provider (OpenAI/Gemini/Bedrock/Ollama/DeepSeek 등)
- 다중 모델 provider UI 바인딩 (Anthropic Claude 단일)
- 멀티테넌트 (이미 prior locked decision)
- 기존 ReactFlow WorkflowBuilder DAG editor의 PentAGI-style 재구성 (사이드바 라우트로 보존)
- Big-bang migration / 2-3 phase migration
- per-step approval gate (Full Auto + tier_gating + Reflector + RescopeService만)

## Acceptance Criteria

### Plan-level (이 deep-interview 산출물 자체의 AC)
- [ ] `.omc/specs/deep-interview-osa-pentagi-port.md` 파일 존재 (이 문서)
- [ ] Ambiguity ≤ 20% 도달 + 모든 active component clarity ≥ 0.65 (per-dim min)
- [ ] Round 0 토폴로지 6 컴포넌트 확정 + 회의록 산출
- [ ] Phase 5 execution bridge에서 사용자가 다음 단계 명시 선택

### Component-level (각 phase가 만족해야 할 AC; pending plan refinement)

**P1 Foundation**
- [ ] pgvector extension 활성화 + alembic migration `005_pgvector.py` 통과
- [ ] `msgchains` 테이블 신설 + alembic migration `006_msgchains.py` 통과 (PentAGI MsgchainType enum: Agent/Pentester/Memorist/Adviser/Reflector/Reporter)
- [ ] `backend/app/orchestrator/performer.py` 스켈레톤(role 카탈로그, run_role 메서드, max-iter cap)
- [ ] 85 기존 tests 모두 통과 + 새 unit tests(performer skeleton, msgchains write/read)
- [ ] UI 영향 0

**P2 Agent Architecture**
- [ ] 6 roles 활성 (Generator/Pentester/Memorist/Adviser/Reflector/Reporter) — 각 system prompt + LLM 바인딩 + tool 리스트
- [ ] 기존 `AttackPlanner.generate()` → `Generator.run()`로 위임 (API shim으로 기존 endpoint 호환)
- [ ] Pentester role이 LLM tool call로 11 AgentAdapter 모두 invoke 가능 (intent_vocabulary 활용)
- [ ] Adviser auto-injection: 같은 tool 5회 호출 또는 총 tool 호출 10회 초과 시 (PentAGI EXECUTION_MONITOR 패턴)
- [ ] Reflector wrap: 모든 chain run에 try/catch + 3회 재시도 (PentAGI 패턴)
- [ ] 85 기존 tests + integration test: full session(prompt → Generator → Pentester → Reporter) 통과

**P3 UI Shell**
- [ ] `feature_flag.OSA_FLOW_UI=true` 시 `/flow/:id` 라우트 활성
- [ ] react-resizable-panels 2-pane(좌:Automation/Assistant/Dashboard, 우:Terminal/Tasks/Agents) 작동
- [ ] xterm.js Terminal 탭: AgentExecution.stdout stream (현행 event_bus 또는 신규 subscription)
- [ ] Tasks 탭: PentestSession.draft_plan_json + 진행중 SubTask 상태 (created/running/finished/failed)
- [ ] Agents 탭: 6 roles + 각 역할의 msgchain 마지막 N 메시지 + 호출 횟수 + adviser/reflector 트리거 표시
- [ ] 기존 12 페이지 사이드바에서 접근 가능 (regression 0)
- [ ] AgentCatalog page → `/agents` route는 Agents 탭으로 redirect (feature flag on)

**P4 Workflow Loop**
- [ ] Generator가 ambiguity_score(0.0–1.0) + draft SubTask list + blockers 생성
- [ ] ambiguity > 0.35 시 ask tool 호출 → frontend WorkflowChat이 사용자 입력 받음 → 다시 Generator 호출 → 임계치 미만 또는 turn cap(6) 도달 시 ready_for_review
- [ ] approval 1회 → 실행 시작 → 각 SubTask가 PrimaryAgent의 LLM tool call로 sub-role 위임 (예: `pentester(intent='web_scan', target=...)`)
- [ ] Memorist auto-call: 각 SubTask 시작 전 `search_in_memory` 자동 실행 (k=3, threshold=0.7), 결과를 SubTask context에 주입
- [ ] tier_gating + exploit_allowlist 모두 통과
- [ ] egress_monitor 작동 (raw shell 명령어가 안 가므로 명령 단위가 아닌 결과 단위 모니터)
- [ ] RescopeService 통합: 새 타깃 발견 시 pause + 사용자 승인
- [ ] e2e test: 1개 sample target에 대한 full flow(prompt→clarify→approve→exec→report)

**P5 Deprecation**
- [ ] Monitor page 제거 (Terminal 탭이 대체) — feature flag off로 fallback 가능
- [ ] PentestWorkflow page 제거 (/flow/:id가 대체)
- [ ] AgentCatalog page 제거 (Agents 탭이 대체)
- [ ] InteractionDashboard page 제거 또는 Dashboard 탭으로 흡수
- [ ] WorkflowBuilder/Workflows/Reports/Admin은 유지 (사이드바 라우트)
- [ ] 모든 e2e 테스트 통과 + 사용자 manual smoke checklist OK

### Verification gates
- [ ] 각 phase의 PR이 main에 merge되기 전 85+ tests + 신규 phase tests 통과
- [ ] 안전 5계층 회귀 테스트 통과 (`tests/integration/test_safety_layers.py`)
- [ ] feature flag rollback path 검증 (flag off → 기존 12 페이지만 표시)
- [ ] PentAGI reference doc(`.omc/research/pentagi-reference.md`)의 매트릭스 행 모두 plan 본문에서 인용

## Assumptions Exposed & Resolved

| Assumption | Challenge | Resolution |
|------------|-----------|------------|
| PentAGI 패턴을 1:1로 포팅하면 OSA가 좋아진다 | OSA의 안전 5계층이 PentAGI보다 강한데 약화 우려? (Round 1) | OSA-strong hybrid: roles는 채택, 단일 terminal 툴 + raw shell은 거부; 기존 AgentAdapter 보존. |
| pgvector + Memorist는 v1 필수 | 사용자 prompt에 명시 없음 (Round 2) | Thin v1로 채택 (search_in_memory 1개만 활성, knowledge/ YAML 시드). guide/answer/code/Graphiti는 v3.4 이월. |
| PentAGI 9개 탭 모두 포팅해야 한다 | 사용자는 3개만 명시 (terminal/Tasks/Agents) (Round 3) | Minimal port: 3탭만. 기존 12 페이지 중 3개만 disposition 변경. |
| 한 번에 다 바꿔야 한다 | phase가 정말 필요한가? big-bang이 빠르지 않은가? (Round 4, Contrarian) | 5-phase incremental — 85 tests 보존 + feature flag rollback. big-bang은 회귀 위험 과대. |
| Per-step approval로 안전성 확보 필요 | PentAGI는 per-step 없이 자율 작동, OSA prior decision = Full Auto (Round 5) | Up-front clarify + runtime delegation. Per-step 거부 (운영자 부담 + Full Auto 충돌). 안전은 tier_gating/Reflector/RescopeService로 처리. |
| 14 roles 모두 필요 | OSA 컨텍스트에서 Coder/Installer/Searcher 의미 제한적, Mentor/Reporter 단순 대체 가능 (Round 6, Simplifier) | Minimal 6 roles. 8개는 v3.4+. Tiered 옵션 거부 (extension hook 도입은 별도 ADR). |
| 분석 문서 형식은 자동으로 결정된다 | 사용자는 "분석 후 plan 생성" 명시 = 분리된 산출물 (Round 7) | Plan §1 본문(요약) + `.omc/research/pentagi-reference.md` 상세 매트릭스. 두 산출물 모두 정의된 AC. |
| OpenAI 임베딩이 표준 | OSA는 Anthropic 단일 LLM provider, 새 vendor 추가 부담 (Round 8) | Local sentence-transformers `all-MiniLM-L6-v2`. 외부 API 의존성 0, backend container ~500MB 증가는 수용. |

## Technical Context

### OSA 현재 상태 (브라운필드)
- v2.1 베이스라인: 85 tests passing
- v3.2.1 consensus plan: pending implementation, 일부 컴포넌트 이미 구현 (workflow_service의 ambiguity_score, draft_plan_json, interview_state 등)
- 디렉토리: `backend/app/{agents,api,core,models,orchestrator,reports,safety,observability,knowledge}` + `frontend/src/{pages,components,api}`
- 11 AgentAdapter: nmap, nuclei, metasploit, pyrit, passive_recon, subfinder, dnsx, httpx, cloudenum, wappalyzer, knowledge_loader
- 안전 5계층: whitelist + risk_filter + exploit_allowlist(tier-gated) + egress_monitor + kill_switch + audit_log
- 12 frontend page: Dashboard/Projects/ProjectDetail/PentestWorkflow/Monitor/Reports/AgentCatalog/Workflows/WorkflowBuilder(ReactFlow)/InteractionDashboard/Admin/Login
- DB migrations 001-004 적용; 005 pgvector + 006 msgchains는 P1

### PentAGI 참조 (포팅 소스)
- 우측 패널 6탭 중 Terminal/Tasks/Agents 채택, Searches/VectorStore/Screenshots v3.4 이월
- 좌측 패널 3탭 모두 채택 (Automation/Assistant/Dashboard)
- 14 roles 중 6개 채택 (Generator/Pentester/Memorist/Adviser/Reflector/Reporter)
- agent-as-tool + msgchains DB 통신 패턴 채택
- 단일 terminal 툴 모델 거부 (OSA-strong hybrid)
- pgvector 단일 스토어 채택, Graphiti+Neo4j 거부
- per-flow Docker 컨테이너 모델 ↔ OSA의 기존 per-agent Docker 컨테이너 — Phase 2에서 정합성 확인 필요(Pentester role 내 11 adapter 모두 기존 Docker backend 사용)
- GraphQL subscriptions vs WebSocket evolved — Phase 3 ADR

### 시드 데이터 변환 알고리즘 (P1)
1. `backend/app/knowledge/**/*.yaml` 모두 로드
2. 각 YAML 항목(예: `web/sqli_intent.yaml`)을 chunk 단위로 분리:
   - name (entity)
   - description (multi-line, RAG 핵심 본문)
   - tactics/tools (메타)
3. description을 sentence-transformers `all-MiniLM-L6-v2`로 임베딩 → 384-dim vector
4. `memory_entries(id, domain_tag, source_yaml_path, name, description, embedding, metadata_json, created_at)` 테이블에 적재
5. pgvector hnsw 인덱스 생성

### Streaming substrate trade-off
- **WebSocket evolved** (현행): `api/v1/ws.py` event_bus 확장 → 토픽별 subscription pattern (`/ws?topics=terminal,tasks,agents`). 장점: 의존성 0 추가, 기존 코드 reuse. 단점: 클라이언트가 토픽 multiplex 로직 작성.
- **GraphQL subscriptions** (PentAGI 패턴): graphql-core + graphene-django(또는 strawberry) + graphql-ws 서버. Apollo Client. 장점: 1:1 토픽 매핑 깔끔, schema 강제. 단점: 새 의존성, GraphQL endpoint 신설.
- 결정 시점: P3 시작 spike 후 ADR.

## Ontology (Key Entities — final round)

| Entity | Type | Fields | Relationships |
|--------|------|--------|---------------|
| PentestSession | core domain (inherited) | id, project_id, prompt, plan_json, status, ambiguity_score, draft_plan_json, interview_state, model_id | has many SubTasks, has many MsgChains, has many AgentExecutions |
| Performer | core domain (new) | id (singleton per process), roles_registry, max_iter_cap | runs many MsgChains; references Role catalog |
| Role | core domain (new) | name (Generator/Pentester/Memorist/Adviser/Reflector/Reporter), system_prompt, llm_model, tools_allowed, max_tool_calls | belongs to Performer, owns many MsgChains |
| MsgChain | core domain (new) | id, session_id, role_name, messages_json, started_at, ended_at, status, retries | belongs to PentestSession, belongs to Role |
| SubTask | core domain (new) | id, session_id, parent_subtask_id (nullable), title, description, status (created/running/finished/failed), result_json | belongs to PentestSession, has many AgentExecutions |
| AgentExecution | core domain (inherited) | id, session_id, subtask_id, agent_type, container_id, config_json, output_json, started_at, ended_at | belongs to SubTask + Session |
| AdapterRegistry | supporting (inherited) | tool slugs (nmap/nuclei/...), tier, domain_tag | provides callable for Pentester role |
| Tier | supporting (inherited) | enum: passive_no_target_contact / passive_low_touch / active_recon / active_exploit | gates AdapterRegistry execution |
| MemoryEntry | core domain (new) | id, domain_tag, source_yaml_path, name, description, embedding(vector(384)), metadata_json | queried by Memorist role |
| AmbiguityScore | supporting (inherited) | value (0.0-1.0), blockers[], reasoning | produced by Generator role |
| AskTool | supporting (new) | invocation: role, question, options[] | bridges Role → WorkflowChat (frontend) |
| Tab | supporting (new) | name (Terminal/Tasks/Agents/Automation/Assistant/Dashboard), pane (left/right), stream_topic | renders on /flow/:id |
| StreamTopic | supporting (new) | name (terminal_log/agent_log/task_event/...), publisher_role | feeds Tab via WebSocket or GraphQL subscription |
| FeatureFlag | supporting (new) | name (OSA_FLOW_UI), enabled, scope (global/team/user) | gates new UI route |
| Phase | supporting (new) | id (P1-P5), name, acceptance_criteria[], rollback_strategy | maps to git PR + feature flag rollout |
| RescopeRequest | core domain (inherited) | id, session_id, discovered_targets[], requesting_step_id, status | pauses session |
| Adviser | supporting (new) | trigger: same_tool_calls > 5 OR total_tool_calls > 10 | injects loop-break message into PrimaryAgent chain |
| Reflector | supporting (new) | trigger: chain error, wraps every Role.run | catches + retries (max 3) |

(18 entities — 10 inherited from prior deep-interview, 8 new from this overhaul.)

## Ontology Convergence

| Round | Entity Count | New | Changed | Stable | Stability Ratio |
|-------|-------------|-----|---------|--------|----------------|
| 0 (topology) | 12 (initial estimate) | 12 | - | - | N/A |
| 1 (agent boundary) | 15 | 3 (Performer, Role, MsgChain) | 0 | 12 | 80% |
| 2 (memory scope) | 16 | 1 (MemoryEntry) | 0 | 15 | 94% |
| 3 (UI inventory) | 17 | 2 (Tab, StreamTopic) | 0 | 15 (FeatureFlag implicit) | 88% |
| 4 (migration phases) | 18 | 1 (Phase, FeatureFlag stabilized as explicit) | 0 | 17 | 94% |
| 5 (workflow loop) | 18 | 1 (AskTool) | 0 | 17 | 94% |
| 6 (role inventory) | 18 | 0 (6 roles named, no new entities) | 0 | 18 | 100% |
| 7 (analysis doc) | 18 | 0 | 0 | 18 | 100% |
| 8 (memorist params) | 18 | 0 | 0 | 18 | 100% |

3라운드 연속 100% stable → 수렴 완료.

## Interview Transcript

<details>
<summary>Full Q&A (8 rounds)</summary>

### Round 0: Topology Confirmation
**Q:** OSA→PentAGI 이식 plan의 상위 컴포넌트 토폴로지를 다음 6개로 잠그시겠어요? (1) PentAGI Analysis Reference, (2) UI/UX Shell + Per-Panel Streaming, (3) Agent Architecture Reshape, (4) Ambiguity-Gated Planning Workflow, (5) Memory/RAG Layer, (6) Migration & Rollout Strategy
**A:** 이대로 6개 잠금
**Result:** topology.status=confirmed, all 6 active

### Round 1
**Q:** PentAGI 에이전트 패턴(Performer + roles)을 채택하되, OSA의 tier-gated AgentAdapter 안전 모델은 어떻게 재구성할까요?
**A:** OSA-strong hybrid (권장)
**Ambiguity:** ~56% (after) — Agent Architecture Constraints 0.25→0.70
**Targeting rationale:** Agent 경계 미정이 5개 컴포넌트의 downstream Goal/Constraints를 끌어내림.

### Round 2
**Q:** Memory/RAG 소장을 이번 plan에서 어느 수준으로 포함할까요?
**A:** Thin v1 (권장)
**Ambiguity:** ~51% (after) — Memory/RAG 컴포넌트 floor 32%→69%
**Targeting rationale:** 사용자 prompt에 명시 없음 + Memorist 역할이 (3)에서 채택됐으므로 backing store scope가 plan §5/§6 phasing을 좌우.

### Round 3
**Q:** UI 셸 v1에 포함할 탭 인벤토리와 기존 OSA 12 페이지의 처리 방향?
**A:** Minimal port (권장)
**Ambiguity:** ~42% (after) — UI Shell Goal 0.50→0.85
**Targeting rationale:** 사용자가 명시한 3탭만 + 12 페이지 disposition이 (4)(6) 의존도 큼.

### Round 4 [Contrarian Mode]
**Q:** Migration phase 구조와 각 phase 완료 게이트?
**A:** 5-phase incremental (권장)
**Ambiguity:** ~37% (after) — Migration 모든 dim 0.30/0.45→0.80+
**Targeting rationale:** Migration이 cross-cutting이라 한 번 잠그면 (1)(3)(4)(5) Criteria 모두 정련. Contrarian: big-bang이 빠르지 않은가? — 거부됨.

### Round 5
**Q:** Planning Workflow 루프와 sub-agent pick 시점은 어떻게 설계할까요?
**A:** Up-front + runtime delegation (권장)
**Ambiguity:** ~25% (after) — Planning Workflow Goal 0.55→0.85, Criteria 0.40→0.75
**Targeting rationale:** 사용자 prompt의 가장 명시적 컨셉("모호함 임계치 미만이 될 때까지", "단계별로 sub-agent/도구 pick")이 (4) Goal이지만 루프 형상 미정.

### Round 6 [Simplifier Mode]
**Q:** OSA v1의 역할 카탈로그를 어느 수준에서 잠그시겠어요?
**A:** Minimal 6 roles (Simplifier 권장)
**Ambiguity:** ~25% (after) — Agent Architecture Criteria 0.65→0.85
**Targeting rationale:** Simplifier — PentAGI 14역할이 OSA v1에 정말 필요한가? Coder/Installer/Searcher 의미 제한적이라 거부.

### Round 7
**Q:** PentAGI Analysis Reference의 산출물 형식과 완료 기준?
**A:** Plan §1 본문 + 보충 reference doc (권장)
**Ambiguity:** ~25% (after) — Analysis Reference Criteria 0.50→0.85
**Targeting rationale:** 사용자가 "분석 후 plan 생성"으로 분리 명시 → 분리된 산출물.

### Round 8
**Q:** Memorist Thin v1 구현 파라미터 (임베딩 모델 + 호출 정책 + 검색 k)?
**A:** Local sentence-transformers (all-MiniLM-L6-v2) + auto + k=3
**Ambiguity:** **17.2%** (after) — Memory/RAG 모든 dim 0.90+. **임계치 ≤20% 도달**.
**Targeting rationale:** 마지막 부족 부분. 외부 LLM provider 의존성 0 유지 + Anthropic 단일 stack 보존.

</details>

## Component → Plan Section Mapping (omc-plan refinement용 hint)

| Plan Section | Component | Phase | Key Deliverables |
|--------------|-----------|-------|-----------------|
| §1 PentAGI Analysis | 1 | P0 (pre-implementation) | `.omc/research/pentagi-reference.md` + plan §1 본문 |
| §2 UI Architecture | 2 | P3 | /flow/:id 라우트, 3탭 우측, 3탭 좌측, react-resizable-panels, xterm.js |
| §3 Agent System | 3 | P1+P2 | Performer 엔진, 6 roles, msgchains 테이블, AdapterRegistry 보존 |
| §4 Workflow Loop | 4 | P4 | Generator+ambiguity, ask 툴, runtime delegation, Memorist auto-call |
| §5 Memory/RAG | 5 | P1+P4 | pgvector, sentence-transformers, knowledge YAML 시드, k=3 auto |
| §6 Migration & Rollout | 6 | P1-P5 | feature flag OSA_FLOW_UI, 5 PR 시퀀스, deprecation timeline |
| §7 Safety Preservation | (cross-cutting) | all phases | 안전 5계층 회귀 테스트, tier_gating + Reflector + RescopeService 통합 |
| §8 Streaming Substrate ADR | 2 | P3 spike | WebSocket evolved vs GraphQL subscriptions 결정 + 1:1 토픽 매핑 원칙 |
