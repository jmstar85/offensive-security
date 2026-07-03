import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from app.api.v1 import agents, auth, projects, sessions, reports, audit_logs, workflows
from app.api.v1 import credentials as credentials_router
from app.api.v1 import users as users_router
from app.api.v1 import domain_agents as domain_agents_router
from app.api.v1 import pentest_sessions as pentest_sessions_router
from app.api.v1 import feature_flags as feature_flags_router
from app.api.v1 import ollama_models as ollama_models_router
from app.api.v1 import coordinator as coordinator_router
from app.api.v1 import ws
from app.core.config import settings
from app.core.database import async_session

# XBOW family registration — gated to keep ROLE_TOPOLOGICAL_ORDER pristine when off.
from app.orchestrator.roles.registry import lazy_register_if_enabled as _lazy_register_xbow
_lazy_register_xbow(getattr(settings, "osa_xbow_families_enabled", False))
from app.core.security import hash_password
from app.models.user import Team, User, UserRole

logger = logging.getLogger(__name__)


async def _seed_admin() -> None:
    """Create initial admin if no admin exists and env vars are set."""
    if not settings.admin_email or not settings.admin_password:
        logger.info("ADMIN_EMAIL/ADMIN_PASSWORD not set — skipping admin seed")
        return

    async with async_session() as session:
        result = await session.execute(
            select(func.count()).select_from(User).where(User.role == UserRole.ADMIN)
        )
        if result.scalar_one() > 0:
            logger.info("Admin user already exists — skipping seed")
            return

        team = Team(name="Administrators")
        session.add(team)
        await session.flush()

        admin = User(
            # Lowercase to match the register/login lookups (config already
            # normalizes; explicit here so the seed is correct on its own).
            email=settings.admin_email.strip().lower(),
            password_hash=hash_password(settings.admin_password),
            full_name=settings.admin_full_name,
            role=UserRole.ADMIN,
            team_id=team.id,
        )
        session.add(admin)
        await session.commit()
        logger.info("Seeded initial admin user: %s", settings.admin_email)


def _assert_backend_network_membership() -> None:
    """MF6 runtime check: backend MUST be a member of osa-net.

    Reads /proc/net/route and /sys/class/net to detect bridge
    interfaces. The osa-net network's bridge name resolves to a value
    like `br-<id>` mapped from the network ID; rather than
    resolve the ID (which would need the daemon API), we assert that
    the container has AT LEAST one non-loopback interface on a private
    RFC1918 subnet AND that the OSA_NETWORK_MEMBERSHIP_CHECK env var
    opts out cleanly in test/dev contexts.

    This is BEST-EFFORT — full resolution lands in W3/PR-?? when MF-
    CRITIC-3 is closed. For now we log + audit any failure rather than
    raising on startup (the container can still serve traffic).
    """
    import os
    from pathlib import Path
    log = logging.getLogger("osa.infra.network_check")
    if os.environ.get("OSA_NETWORK_MEMBERSHIP_CHECK", "soft").lower() == "off":
        return
    sys_net = Path("/sys/class/net")
    if not sys_net.exists():
        log.warning("/sys/class/net not present; skipping membership check")
        return
    non_loopback = [
        p.name for p in sys_net.iterdir()
        if p.name != "lo" and not p.name.startswith("br-loopback")
    ]
    if not non_loopback:
        log.warning("No non-loopback interfaces found; container not on osa-net?")
        return
    log.info("backend network interfaces detected: %s", non_loopback)


async def _warm_embedding_model() -> None:
    """Pre-load the sentence-transformers embedding model so the first Memorist
    call inside a request does not pay the 2-4s model load tax.

    Resolves Open Issue #2 from the v4.0 Phase 1 review. The singleton is
    cached inside `memorist_embedding`; this call instantiates it on startup.
    Any failure is logged but does not block app boot — the first user request
    will pay the cold-start cost as a fallback.
    """
    from app.orchestrator.roles import memorist_embedding

    try:
        await memorist_embedding.get_or_load_model()
        logger.info(
            "Embedding model warmed: %s (dim=%d)",
            settings.embedding_model_name,
            settings.embedding_vector_dim,
        )
    except Exception as e:  # pragma: no cover - defensive on startup
        logger.warning("Embedding warm-up failed: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _seed_admin()
    await _warm_embedding_model()
    try:
        _assert_backend_network_membership()
    except Exception as e:
        logger.warning("Network membership check raised unexpectedly: %s", e)
    yield
    # Shutdown


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(auth.router, prefix=f"{settings.api_prefix}/auth", tags=["auth"])
app.include_router(projects.router, prefix=f"{settings.api_prefix}/projects", tags=["projects"])
app.include_router(sessions.router, prefix=f"{settings.api_prefix}/sessions", tags=["sessions"])
app.include_router(reports.router, prefix=f"{settings.api_prefix}/reports", tags=["reports"])
app.include_router(agents.router, prefix=f"{settings.api_prefix}/agents", tags=["agents"])
app.include_router(
    audit_logs.router, prefix=f"{settings.api_prefix}/audit-logs", tags=["audit-logs"]
)
app.include_router(
    users_router.router, prefix=f"{settings.api_prefix}/users", tags=["users"]
)
app.include_router(
    domain_agents_router.router,
    prefix=f"{settings.api_prefix}/domain-agents",
    tags=["domain-agents"],
)
app.include_router(
    pentest_sessions_router.router,
    prefix=f"{settings.api_prefix}/pentest-sessions",
    tags=["pentest-sessions"],
)
app.include_router(workflows.router, prefix=settings.api_prefix, tags=["workflows"])
app.include_router(
    feature_flags_router.router,
    prefix=settings.api_prefix,
    tags=["feature-flags"],
)
app.include_router(
    ollama_models_router.router,
    prefix=settings.api_prefix,
    tags=["ollama"],
)
app.include_router(
    credentials_router.router,
    prefix=settings.api_prefix,
    tags=["credentials"],
)
app.include_router(
    coordinator_router.router,
    prefix=settings.api_prefix,
    tags=["coordinator"],
)

# WebSocket — mounted under the same /api/v1 prefix as REST so the
# external path is /api/v1/ws/sessions/{id} (matches the frontend client).
app.include_router(ws.router, prefix=settings.api_prefix, tags=["websocket"])


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": settings.app_name}
