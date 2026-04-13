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

    # LLM Provider: "copilot" (Copilot Enterprise), "anthropic" (direct), or "github" (GitHub Models)
    llm_provider: str = "copilot"

    # Copilot Enterprise (uses gh CLI OAuth token — zero-cost with org subscription)
    copilot_endpoint: str = "https://api.enterprise.githubcopilot.com/chat/completions"
    copilot_model: str = "claude-sonnet-4.6"
    copilot_token: str = ""  # auto-detected from `gh auth token` if empty

    # Anthropic (direct API — usage-based billing)
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    # GitHub Models (uses GitHub PAT — requires Copilot Individual/Pro)
    github_token: str = ""
    github_models_endpoint: str = "https://models.github.ai/inference"
    github_model: str = "anthropic/claude-sonnet-4.6"

    # Docker
    docker_network: str = "osa_pentest_net"
    container_memory_limit: str = "512m"
    container_cpu_limit: float = 1.0
    container_pids_limit: int = 100
    metasploit_memory_limit: str = "2g"
    metasploit_cpu_limit: float = 2.0

    # Safety
    max_prompts_per_minute: int = 5
    session_heartbeat_timeout_seconds: int = 60
    kill_switch_timeout_seconds: int = 5

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
