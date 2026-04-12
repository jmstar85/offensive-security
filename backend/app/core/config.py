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
    anthropic_model: str = "claude-sonnet-4-20250514"

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
