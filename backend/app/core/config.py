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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
