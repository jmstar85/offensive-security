"""Integration: POST /api/v1/users/ admin-driven user creation + GET /users/teams.

Verifies:
  - Default team: new user joins the creating admin's team.
  - Existing team_id: user assigned to that team; unknown team_id → 404.
  - New team_name: a fresh team is created and the user joins it.
  - Duplicate email → 400, no second user written.
  - Role honoured (member / team_admin / admin), audit row written.
  - RBAC: require_admin rejects a non-admin actor with 403.
  - GET /users/teams returns all teams.

Hashing is patched with a deterministic stand-in so the endpoint logic is
exercised quickly and independently of bcrypt. Real bcrypt round-trips are
covered by tests/unit/test_security_password.py.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.api.v1.users import CreateUserRequest, create_user, list_teams
from app.models.audit import AuditLog
from app.models.user import Team, User, UserRole


def _fake_hash(password: str) -> str:
    return f"hashed::{password}"


async def _seed_admin(db: AsyncSession, *, team_name: str = "Admin Team") -> User:
    team = Team(name=team_name)
    db.add(team)
    await db.flush()
    admin = User(
        email="admin@kt.com",
        password_hash=_fake_hash("AdminPass123"),
        full_name="System Admin",
        role=UserRole.ADMIN,
        team_id=team.id,
    )
    db.add(admin)
    await db.flush()
    return admin


@pytest.fixture(autouse=True)
def _patch_hashing():
    with patch("app.api.v1.users.hash_password", side_effect=_fake_hash):
        yield


@pytest.mark.asyncio
async def test_create_user_defaults_to_admin_team(db: AsyncSession):
    admin = await _seed_admin(db)

    body = CreateUserRequest(
        email="member@kt.com",
        full_name="New Member",
        password="MemberPass123",
    )
    resp = await create_user(body=body, db=db, admin=admin)

    assert resp.email == "member@kt.com"
    assert resp.role == "member"
    assert resp.team_id == admin.team_id

    created = (
        await db.execute(select(User).where(User.email == "member@kt.com"))
    ).scalar_one()
    assert created.password_hash == _fake_hash("MemberPass123")
    assert created.is_active is True

    audit = (
        await db.execute(select(AuditLog).where(AuditLog.action == "user.created"))
    ).scalar_one()
    assert audit.actor_id == admin.id
    assert audit.target_id == str(created.id)
    assert audit.details_json == {
        "email": "member@kt.com",
        "role": "member",
        "team_id": str(admin.team_id),
    }


@pytest.mark.asyncio
async def test_create_user_existing_team_id(db: AsyncSession):
    admin = await _seed_admin(db)
    other = Team(name="Other Team")
    db.add(other)
    await db.flush()

    body = CreateUserRequest(
        email="t2@kt.com",
        full_name="Team Two",
        password="MemberPass123",
        team_id=other.id,
    )
    resp = await create_user(body=body, db=db, admin=admin)
    assert resp.team_id == other.id


@pytest.mark.asyncio
async def test_create_user_unknown_team_id_404(db: AsyncSession):
    import uuid

    admin = await _seed_admin(db)
    body = CreateUserRequest(
        email="ghost@kt.com",
        full_name="Ghost",
        password="MemberPass123",
        team_id=uuid.uuid4(),
    )
    with pytest.raises(HTTPException) as exc:
        await create_user(body=body, db=db, admin=admin)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_user_new_team_name(db: AsyncSession):
    admin = await _seed_admin(db)

    body = CreateUserRequest(
        email="lead@kt.com",
        full_name="Team Lead",
        password="MemberPass123",
        role=UserRole.TEAM_ADMIN,
        team_name="  Red Team Alpha  ",
    )
    resp = await create_user(body=body, db=db, admin=admin)
    assert resp.role == "team_admin"

    team = (
        await db.execute(select(Team).where(Team.name == "Red Team Alpha"))
    ).scalar_one()
    assert resp.team_id == team.id


@pytest.mark.asyncio
async def test_create_user_duplicate_email_400(db: AsyncSession):
    admin = await _seed_admin(db)

    body = CreateUserRequest(
        email="admin@kt.com",  # already taken by the seeded admin
        full_name="Dup",
        password="MemberPass123",
    )
    with pytest.raises(HTTPException) as exc:
        await create_user(body=body, db=db, admin=admin)
    assert exc.value.status_code == 400

    count = (
        await db.execute(
            select(func.count()).select_from(User).where(User.email == "admin@kt.com")
        )
    ).scalar_one()
    assert count == 1

    # The rejected attempt must not have written a 'user.created' audit row.
    audit_count = (
        await db.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "user.created")
        )
    ).scalar_one()
    assert audit_count == 0


@pytest.mark.asyncio
async def test_create_user_admin_role(db: AsyncSession):
    admin = await _seed_admin(db)
    body = CreateUserRequest(
        email="admin2@kt.com",
        full_name="Second Admin",
        password="MemberPass123",
        role=UserRole.ADMIN,
    )
    resp = await create_user(body=body, db=db, admin=admin)
    assert resp.role == "admin"


@pytest.mark.asyncio
async def test_require_admin_rejects_non_admin(db: AsyncSession):
    team = Team(name="Member Team")
    db.add(team)
    await db.flush()
    member = User(
        email="member-only@kt.com",
        password_hash=_fake_hash("x"),
        full_name="Member",
        role=UserRole.MEMBER,
        team_id=team.id,
    )
    with pytest.raises(HTTPException) as exc:
        await require_admin(current_user=member)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_list_teams_returns_all(db: AsyncSession):
    admin = await _seed_admin(db, team_name="Alpha")
    db.add(Team(name="Bravo"))
    await db.flush()

    teams = await list_teams(db=db, admin=admin)
    names = {t.name for t in teams}
    assert {"Alpha", "Bravo"} <= names


@pytest.mark.asyncio
async def test_create_user_team_id_takes_precedence_over_team_name(db: AsyncSession):
    """When both are supplied, the existing team_id wins and NO new team is made."""
    admin = await _seed_admin(db)
    existing = Team(name="Existing Team")
    db.add(existing)
    await db.flush()

    body = CreateUserRequest(
        email="both@kt.com",
        full_name="Both Supplied",
        password="MemberPass123",
        team_id=existing.id,
        team_name="Should Not Be Created",
    )
    resp = await create_user(body=body, db=db, admin=admin)
    assert resp.team_id == existing.id

    spurious = (
        await db.execute(
            select(func.count())
            .select_from(Team)
            .where(Team.name == "Should Not Be Created")
        )
    ).scalar_one()
    assert spurious == 0


@pytest.mark.asyncio
async def test_create_user_whitespace_team_name_falls_through_to_admin_team(
    db: AsyncSession,
):
    """A blank-after-strip team_name must not create an empty team."""
    admin = await _seed_admin(db)
    teams_before = (
        await db.execute(select(func.count()).select_from(Team))
    ).scalar_one()

    body = CreateUserRequest(
        email="ws@kt.com",
        full_name="Whitespace Team",
        password="MemberPass123",
        team_name="   ",
    )
    resp = await create_user(body=body, db=db, admin=admin)
    assert resp.team_id == admin.team_id

    teams_after = (
        await db.execute(select(func.count()).select_from(Team))
    ).scalar_one()
    assert teams_after == teams_before


@pytest.mark.asyncio
async def test_create_user_email_normalized_to_lowercase(db: AsyncSession):
    """A case-variant of an existing email is rejected, and stored email is lowered."""
    admin = await _seed_admin(db)  # seeds admin@kt.com

    # New mixed-case email is stored lowercased.
    body = CreateUserRequest(
        email="MixedCase@KT.com",
        full_name="Mixed",
        password="MemberPass123",
    )
    resp = await create_user(body=body, db=db, admin=admin)
    assert resp.email == "mixedcase@kt.com"

    # A case-variant of the existing admin email collides → 400.
    dup = CreateUserRequest(
        email="ADMIN@kt.com",
        full_name="Dup",
        password="MemberPass123",
    )
    with pytest.raises(HTTPException) as exc:
        await create_user(body=dup, db=db, admin=admin)
    assert exc.value.status_code == 400


def test_admin_user_endpoints_require_admin_dependency():
    """Regression guard: create_user / list_teams / list_users stay admin-gated.

    The functional tests call the endpoints directly (bypassing FastAPI's
    Depends resolution), so this inspects the wired router to ensure the
    require_admin dependency is not accidentally dropped.
    """
    from app.api.deps import require_admin
    from app.api.v1.users import router

    by_key: dict[tuple[str, str], object] = {}
    for route in router.routes:
        for method in route.methods:
            by_key[(method, route.path)] = route

    for key in [("POST", "/"), ("GET", "/teams"), ("GET", "/")]:
        route = by_key[key]
        dep_calls = {d.call for d in route.dependant.dependencies}
        assert require_admin in dep_calls, f"{key} is missing require_admin"


def test_create_user_short_password_rejected_by_schema():
    with pytest.raises(ValidationError):
        CreateUserRequest(
            email="x@kt.com",
            full_name="X",
            password="short",
        )
