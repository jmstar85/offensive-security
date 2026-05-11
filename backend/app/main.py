from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import auth, projects, sessions, reports, audit_logs, agents, workflows
from app.api.v1 import ws
from app.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
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
app.include_router(
    audit_logs.router, prefix=f"{settings.api_prefix}/audit-logs", tags=["audit-logs"]
)
app.include_router(agents.router, prefix=settings.api_prefix)
app.include_router(workflows.router, prefix=settings.api_prefix)

# WebSocket
app.include_router(ws.router, tags=["websocket"])


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": settings.app_name}
