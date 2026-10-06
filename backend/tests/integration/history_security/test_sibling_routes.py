"""B1 regression: the legacy /sessions router must enforce the SAME authoritative
project-owner-team authorization + masking as /pentest-sessions (no divergent copy).
The session's cached team_id is deliberately poisoned to the OUTSIDER's team to
prove it is not trusted (ownership resolves via the project owner's team)."""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.sessions import router
from app.core.database import get_db
from app.core.security import create_access_token
from app.models.project import Project
from app.models.session import AgentExecution, PentestSession, TerminalLine
from app.models.user import Team, User, UserRole

SECRET = "sk-abc123def456ghi789jkl"


def _hdr(u: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(u.id))}"}


@pytest_asyncio.fixture
async def sibling_case(engine):
    async with engine.connect() as conn, conn.begin():
        async with AsyncSession(
            conn, expire_on_commit=False, join_transaction_mode="create_savepoint",
        ) as db:
            t1, t2 = Team(name=f"a-{uuid.uuid4()}"), Team(name=f"b-{uuid.uuid4()}")
            db.add_all([t1, t2])
            await db.flush()
            owner = User(email=f"o-{uuid.uuid4()}@x.y", password_hash="x", full_name="o", team_id=t1.id, role=UserRole.MEMBER)
            member = User(email=f"m-{uuid.uuid4()}@x.y", password_hash="x", full_name="m", team_id=t1.id, role=UserRole.MEMBER)
            outsider = User(email=f"out-{uuid.uuid4()}@x.y", password_hash="x", full_name="out", team_id=t2.id, role=UserRole.MEMBER)
            db.add_all([owner, member, outsider])
            await db.flush()
            project = Project(name="p", client_name="c", created_by=owner.id)
            db.add(project)
            await db.flush()
            # team_id poisoned to the OUTSIDER team; real ownership is owner(team1).
            session = PentestSession(project_id=project.id, prompt=SECRET, status="running", team_id=t2.id)
            db.add(session)
            await db.flush()
            db.add(AgentExecution(session_id=session.id, agent_type="nmap", status="completed", step_order=1))
            db.add(TerminalLine(session_id=session.id, execution_id=None, seq=1, agent_type="nmap", line=f"leak {SECRET}"))
            await db.flush()
            app = FastAPI()
            app.include_router(router, prefix="/sessions")

            async def _database():
                yield db

            app.dependency_overrides[get_db] = _database
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                yield SimpleNamespace(
                    db=db, client=client, session=session,
                    users={"owner": owner, "member": member, "outsider": outsider},
                )
            await db.rollback()


@pytest.mark.parametrize("suffix", ["", "/executions", "/terminal"])
async def test_outsider_denied_on_sibling_routes(sibling_case, suffix):
    c = sibling_case
    r = await c.client.get(f"/sessions/{c.session.id}{suffix}", headers=_hdr(c.users["outsider"]))
    assert r.status_code in (403, 404), r.text


async def test_member_read_allowed_and_masked(sibling_case):
    c = sibling_case
    r = await c.client.get(f"/sessions/{c.session.id}", headers=_hdr(c.users["member"]))
    assert r.status_code == 200, r.text
    assert SECRET not in r.text
    assert "REDACTED" in r.text


async def test_list_excludes_other_team_sessions(sibling_case):
    c = sibling_case
    r = await c.client.get("/sessions/", headers=_hdr(c.users["outsider"]))
    assert r.status_code == 200, r.text
    assert all(row["id"] != str(c.session.id) for row in r.json())


async def test_member_terminal_masks_secret(sibling_case):
    c = sibling_case
    r = await c.client.get(f"/sessions/{c.session.id}/terminal", headers=_hdr(c.users["member"]))
    assert r.status_code == 200, r.text
    assert SECRET not in r.text
