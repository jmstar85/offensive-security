from decimal import Decimal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    app_name: str = "Offensive Security Agent"
    debug: bool = False
    api_prefix: str = "/api/v1"

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/osa_db"

    # Auth
    secret_key: str = "change-me-in-production-use-a-real-secret-key"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    # Role assigned to public self-signups (/auth/register). Defaulted to "admin"
    # so that, for now, every account has full access and admin/regular users are
    # not distinguished. Set DEFAULT_SIGNUP_ROLE=member to re-introduce the split.
    default_signup_role: str = "admin"

    @field_validator("default_signup_role")
    @classmethod
    def _validate_signup_role(cls, v: str) -> str:
        # Fail fast at startup rather than 500-ing on the first signup: the value
        # must be a real UserRole the auth gates recognise (imported lazily to
        # avoid a config<->models import cycle).
        from app.models.user import UserRole

        valid = {r.value for r in UserRole}
        if v not in valid:
            raise ValueError(
                f"default_signup_role must be one of {sorted(valid)}, got {v!r}"
            )
        return v

    @field_validator("admin_email")
    @classmethod
    def _normalize_admin_email(cls, v: str) -> str:
        # Match the lowercasing done on the register/login lookup paths so the
        # seeded admin (written from this value) can actually log in.
        return v.strip().lower()

    @model_validator(mode="after")
    def _require_fernet_key_when_multi_provider(self) -> "Settings":
        # When osa_multi_provider_llm is ON the per-user credential vault is the
        # SOLE credential source: the process-env ANTHROPIC_API_KEY fallback is
        # disabled (credential_resolver.py:61-63) and every stored credential is
        # Fernet-encrypted at rest — so CREDENTIAL_FERNET_KEY is mandatory or the
        # app would 500 on the first credential decrypt (security.py:get_fernet).
        # Fail fast at startup instead. Gated to production (mirrors
        # validate_flag_topology's production-only enforcement) so dev/test can
        # run the flag ON while injecting a Fernet key per-test.
        if (
            self.environment == "production"
            and self.osa_multi_provider_llm
            and not self.credential_fernet_key
        ):
            raise ValueError(
                "CREDENTIAL_FERNET_KEY must be set when osa_multi_provider_llm=True: "
                "the per-user credential vault requires a Fernet key at rest and the "
                "process-env ANTHROPIC_API_KEY fallback is disabled."
            )
        return self

    # Claude API
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"  # legacy alias, prefer anthropic_default_model

    # Anthropic models (Open Q #1 resolved per plan v3.2.1 §1.3)
    anthropic_default_model: str = "claude-sonnet-4-6"
    anthropic_admin_model: str = "claude-opus-4-6"
    anthropic_default_model_anthropic_id: str = "claude-sonnet-4-6-20250514"
    anthropic_admin_model_anthropic_id: str = "claude-opus-4-6-20250514"

    # New-flow session/engine default (PR4, Principle 6 / PM3) — the user-facing
    # session default consumed ONLY by ModelSelector / session.model_id. Kept
    # DISTINCT from anthropic_default_model (the cheaper internal-role fallback,
    # unchanged) so making the engine default opus-4-8 does NOT invert the cost
    # of every internal anthropic role or silently promote the interview/chat turn.
    session_default_model: str = "claude-opus-4-8"
    session_default_model_anthropic_id: str = "claude-opus-4-8"
    # Cheap OpenAI model for the per-provider interview/chat resolver (Blocking 1).
    openai_interview_model: str = "gpt-4o-mini"
    # GitHub Copilot: the public device-flow client id every editor integration
    # uses (no client secret needed), plus the default Copilot model. Copilot
    # model ids are namespaced ``copilot/<model>`` so per-role routing can
    # disambiguate them from bare openai/anthropic ids.
    github_copilot_client_id: str = "Iv1.b507a08c87ecfe98"
    github_copilot_default_model: str = "copilot/gpt-4.1"

    # Interview loop
    workflow_max_interview_turns: int = 6
    workflow_ambiguity_threshold: float = 0.35
    # Group B (osa flow interview autoblock): when enabled, the session-start
    # interview must drive ambiguity down to the tighter target below before it
    # may reach ready_for_review — the deep-interview "until ≤ 20%" contract.
    # The operator can still one-click "Proceed to plan review" (ambiguity is
    # advisory; the whitelist scope stays the hard gate), and the turn cap
    # (workflow_max_interview_turns) remains the escape hatch to needs_human_review.
    osa_interview_autoblock_enabled: bool = True
    osa_interview_autoblock_threshold: float = 0.20
    # Interview/Generator response budget. MUST exceed every provider send
    # default (4096) so a multi-step draft_plan JSON is not truncated mid-response
    # — a truncated envelope collapses to ambiguity 1.0 and sticks the interview
    # (session 0f9c5646). Truncation salvage (ambiguity_loop) is the safety net;
    # this lowers the probability of hitting it.
    interview_max_tokens: int = 8192
    workflow_force_approve_min_reason_chars: int = 32
    workflow_opus_requires_admin: bool = True

    # Budget
    workflow_daily_usd_budget_default: Decimal = Decimal("5.00")
    workflow_team_pool_budget_enabled: bool = True

    # Rescope
    rescope_decision_timeout_seconds: int = 300

    # Model client retries
    anthropic_retry_max_attempts: int = 3
    anthropic_retry_backoff_seconds: list[float] = [0.2, 1.0, 5.0]

    # Knowledge (on-disk only — no DB)
    knowledge_dir: str = "/app/backend/app/knowledge"
    knowledge_required_sha256_path: str = "/app/backend/app/knowledge/MANIFEST.yaml"

    # Passive recon shared image
    passive_recon_image: str = "osa-passive-recon:latest"
    passive_egress_allowlist: list[str] = [
        "crt.sh",
        "*.haveibeenpwned.com",
        "api.github.com",
        "*.shodan.io",
        "viewdns.info",
        "dns.google",
        "cloudflare-dns.com",
    ]

    # Active tiers — explicit approval flags
    active_recon_requires_explicit_approval: bool = True
    active_exploit_requires_explicit_approval: bool = True

    # Docker
    docker_network: str = "osa_pentest_net"
    container_memory_limit: str = "512m"
    container_cpu_limit: float = 1.0
    container_pids_limit: int = 100
    metasploit_memory_limit: str = "2g"
    metasploit_cpu_limit: float = 2.0

    # Admin bootstrap
    admin_email: str = ""
    admin_password: str = ""
    admin_full_name: str = "System Admin"

    # Safety
    max_prompts_per_minute: int = 5
    session_heartbeat_timeout_seconds: int = 60
    kill_switch_timeout_seconds: int = 5

    # --- v4.0 PentAGI port additions (P1 Foundation) -------------------------
    # Memorist Thin v1 (sentence-transformers local embedding + pgvector hnsw)
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_vector_dim: int = 384
    memorist_k: int = 3
    memorist_score_threshold: float = 0.7

    # Feature flag for new /flow/:id route + 2-pane shell (PR10: default ON after the
    # scanme E2E verified the autonomous loop)
    osa_flow_ui_enabled: bool = True

    # Deployment environment (controls feature-flag topology enforcement)
    environment: str = "dev"

    # Kali coexistence backend (PR10: default ON; double-enforced at get_adapter + palette_for_domain)
    osa_kali_backend_enabled: bool = True
    # XBOW agent families (PR10: default ON; lazy-registered at startup via lazy_register_if_enabled)
    osa_xbow_families_enabled: bool = True
    # Kali docker socket proxy endpoint (used by KaliBackend only; PR-7 wires this into docker-compose)
    kali_docker_host: str = "tcp://docker-socket-proxy:2375"

    # Performer engine (ADR-003 concurrency model; SF-3 cap)
    performer_max_iter: int = 64
    max_concurrent_performer_sessions: int = 4
    # PR7: bound nested role launches through delegate_tool_call (only reachable
    # on the trusted automation lane, allow_role_invocation=True) — independent of
    # the per-session lease and the Assistant per-session turn mutex.
    max_sub_role_depth: int = 3
    # PR7: per-turn tool-dispatch step cap for the role-free AssistantService loop.
    assistant_max_steps_per_turn: int = 16

    # PentAGI brakes adopted in v4.0 (Adviser injection thresholds; Reflector retry counts)
    adviser_trigger_same_tool: int = 5
    adviser_trigger_total_tool: int = 10
    reflector_max_retries: int = 3
    reflector_retry_backoff_seconds: list[float] = [0.2, 1.0, 5.0]
    pentester_max_tool_calls: int = 100
    limited_role_max_tool_calls: int = 20
    # PR4b: wall-clock budget for a single Pentester live tool-use loop. Trips
    # IterationCapHit alongside the per-turn max_tool_calls cap.
    performer_wall_clock_seconds: int = 600

    # Set via env CREDENTIAL_FERNET_KEY (base64 32-byte). Required when osa_multi_provider_llm=True.
    credential_fernet_key: str = ""

    # Multi-provider LLM flag — when True, all requests MUST resolve a per-user
    # credential row; the process-env ANTHROPIC_API_KEY fallback is disabled
    # (credential_resolver.py:61-63). PR9: default ON — the per-user credential
    # vault is the sole credential source; a missing credential fails closed with
    # CredentialNotFound on both the fresh-plan engine run AND the interview/chat
    # turn. Resulting default flag tuple is T3 (multi_provider + coordinator +
    # xbow_families) — a supported production topology.
    osa_multi_provider_llm: bool = True

    # Coordinator service flags (PR10: coordinator default ON after verification)
    osa_coordinator_enabled: bool = True
    osa_coordinator_replay_enabled: bool = False
    # Demo/no-LLM lane: when True, the saved-workflow path builds the
    # deterministic UnderstandingOfTarget + PlanOfWork directly (bypassing
    # CoordinatorService.run's ReplayLaneViolation guard) so the Coordinator
    # panels populate and per-phase AgentFamilyInstance rows materialize on a
    # replay. Default OFF keeps the v1.1 byte-identical replay untouched.
    osa_coordinator_populate_on_replay: bool = False

    # PR7: Docker network the autonomous lane attaches tool containers to (the LLM
    # never specifies Docker networking). "bridge" works on a bare host; set to the
    # compose tool network (e.g. "osa-net") in docker-compose. A tool dispatched with
    # no network gets network_disabled=True and cannot reach the target.
    osa_agent_container_network: str = "bridge"

    # XBOW autonomous lane (PR4a): when True, OrchestratorService.run drives the
    # Performer engine (per-dispatch tier gate + shared runtime safety helper)
    # instead of the deterministic PlanExecutor (fresh-plan lane only; saved-workflow
    # replay always uses PlanExecutor → byte-identical). PR10: default ON after the
    # scanme E2E verified the full loop. The deterministic lane is the explicit-OFF
    # offline fallback.
    osa_xbow_autonomous_enabled: bool = True

    # Sidecar feature flags (W3) — UI gating only, sidecars are managed by
    # docker-compose and IMAGE_REGEX, not by these booleans
    osa_mitm_proxy_enabled: bool = False
    osa_headless_browser_enabled: bool = False
    osa_collaborator_enabled: bool = False

    # Planner LLM provider for the fresh-plan lane (AttackPlanner). "anthropic"
    # (default) uses ModelClient + the Anthropic API; "ollama" routes plan
    # generation to a local Ollama server (no external API key required).
    osa_llm_provider: str = "anthropic"
    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "qwen3-14b-96k:latest"
    ollama_temperature: float = 0.2
    ollama_timeout_seconds: int = 300

    # Coordinator iteration caps
    max_coordinator_iterations: int = 8
    max_coordinator_wall_clock_seconds: int = 600
    max_coordinator_total_tokens: int = 200_000

    # MITM traffic routing flag (default OFF; gates AttackAgent egress via mitmproxy sidecar)
    osa_traffic_via_mitm: bool = False

    # OAuth redirect URI for LLM provider OAuth flows
    oauth_redirect_uri: str = "http://localhost:8000/api/v1/auth/llm-providers/oauth/callback"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
