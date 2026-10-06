"""Real database, signed-token fixtures for the session history boundary."""
from collections.abc import AsyncIterator
from dataclasses import dataclass
import uuid

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.api.v1.pentest_sessions import router
from app.core.database import get_db
from app.core.security import create_access_token
from app.models.project import Project
from app.models.session import PentestSession
from app.models.user import Team, User, UserRole


@dataclass(frozen=True, slots=True)
class HistoryCase:
    db: AsyncSession
    app: FastAPI
    client: AsyncClient
    session: PentestSession
    users: dict[str, User]

    def headers(self, actor: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(str(self.users[actor].id))}"}

    @property
    def url(self) -> str:
        return f"/pentest-sessions/{self.session.id}"


@pytest_asyncio.fixture
async def history_case(engine: AsyncEngine) -> AsyncIterator[HistoryCase]:
    async with engine.connect() as connection, connection.begin():
        async with AsyncSession(
            connection, expire_on_commit=False, join_transaction_mode="create_savepoint",
        ) as db:
            teams = [Team(name=f"history-{uuid.uuid4()}") for _ in range(2)]
            db.add_all(teams)
            await db.flush()
            users = {
                name: User(
                    email=f"{name}-{uuid.uuid4()}@example.com",
                    password_hash="unused",
                    full_name=name,
                    team_id=teams[team_index].id,
                    role=role,
                )
                for name, team_index, role in (
                    ("owner", 0, UserRole.MEMBER),
                    ("member", 0, UserRole.MEMBER),
                    ("team_admin", 0, UserRole.TEAM_ADMIN),
                    ("outsider", 1, UserRole.MEMBER),
                    ("other_team_admin", 1, UserRole.TEAM_ADMIN),
                    ("admin", 1, UserRole.ADMIN),
                )
            }
            db.add_all(users.values())
            await db.flush()
            project = Project(name="History", client_name="Test", created_by=users["owner"].id)
            db.add(project)
            await db.flush()
            session = PentestSession(
                project_id=project.id, prompt="scan example.com", status="draft",
                team_id=None,
            )
            db.add(session)
            await db.flush()
            app = FastAPI()
            app.include_router(router, prefix="/pentest-sessions")

            async def database() -> AsyncIterator[AsyncSession]:
                yield db

            app.dependency_overrides[get_db] = database
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test",
            ) as client:
                yield HistoryCase(db, app, client, session, users)
            await db.rollback()
