from decimal import Decimal

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

    # Claude API
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"  # legacy alias, prefer anthropic_default_model

    # Anthropic models (Open Q #1 resolved per plan v3.2.1 §1.3)
    anthropic_default_model: str = "claude-sonnet-4-6"
    anthropic_admin_model: str = "claude-opus-4-6"
    anthropic_default_model_anthropic_id: str = "claude-sonnet-4-6-20250514"
    anthropic_admin_model_anthropic_id: str = "claude-opus-4-6-20250514"

    # Interview loop
    workflow_max_interview_turns: int = 6
    workflow_ambiguity_threshold: float = 0.35
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

    # Feature flag for new /flow/:id route + 2-pane shell (gated; default OFF until P3-main)
    osa_flow_ui_enabled: bool = False

    # Deployment environment (controls feature-flag topology enforcement)
    environment: str = "dev"

    # Kali coexistence backend (v1 — default OFF; double-enforced at get_adapter + palette_for_domain)
    osa_kali_backend_enabled: bool = False
    # XBOW agent families (default OFF; lazy-registered at startup via lazy_register_if_enabled)
    osa_xbow_families_enabled: bool = False
    # Kali docker socket proxy endpoint (used by KaliBackend only; PR-7 wires this into docker-compose)
    kali_docker_host: str = "tcp://docker-socket-proxy:2375"

    # Performer engine (ADR-003 concurrency model; SF-3 cap)
    performer_max_iter: int = 64
    max_concurrent_performer_sessions: int = 4

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
    # credential row; the process-env ANTHROPIC_API_KEY fallback is disabled.
    osa_multi_provider_llm: bool = False

    # Coordinator service flags (default OFF)
    osa_coordinator_enabled: bool = False
    osa_coordinator_replay_enabled: bool = False
    # Demo/no-LLM lane: when True, the saved-workflow path builds the
    # deterministic UnderstandingOfTarget + PlanOfWork directly (bypassing
    # CoordinatorService.run's ReplayLaneViolation guard) so the Coordinator
    # panels populate and per-phase AgentFamilyInstance rows materialize on a
    # replay. Default OFF keeps the v1.1 byte-identical replay untouched.
    osa_coordinator_populate_on_replay: bool = False

    # XBOW autonomous lane (PR4a): when True, OrchestratorService.run drives the
    # Performer engine (per-dispatch tier gate + shared runtime safety helper)
    # instead of the deterministic PlanExecutor. Default OFF — the deterministic
    # lane is the offline fallback and stays byte-identical until this flips (PR10).
    osa_xbow_autonomous_enabled: bool = False

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
