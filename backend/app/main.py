import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from app.api.v1 import agents, auth, projects, sessions, reports, audit_logs, workflows
from app.api.v1 import users as users_router
from app.api.v1 import domain_agents as domain_agents_router
from app.api.v1 import pentest_sessions as pentest_sessions_router
from app.api.v1 import feature_flags as feature_flags_router
from app.api.v1 import ws
from app.core.config import settings
from app.core.database import async_session
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
            email=settings.admin_email,
            password_hash=hash_password(settings.admin_password),
            full_name=settings.admin_full_name,
            role=UserRole.ADMIN,
            team_id=team.id,
        )
        session.add(admin)
        await session.commit()
        logger.info("Seeded initial admin user: %s", settings.admin_email)


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

# WebSocket
app.include_router(ws.router, tags=["websocket"])


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": settings.app_name}
