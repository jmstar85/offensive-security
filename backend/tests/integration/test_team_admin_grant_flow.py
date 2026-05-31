"""Integration: PATCH /api/v1/users/{user_id}/role grants TEAM_ADMIN role.

Verifies:
  - ADMIN actor can promote a user to team_admin → 200 + role updated in DB
  - Non-admin actor attempting the same PATCH → 403
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import Team, User, UserRole


def _make_user(role: UserRole = UserRole.MEMBER, is_active: bool = True) -> User:
    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.email = f"{role.value}_{uuid.uuid4().hex[:6]}@example.com"
    u.full_name = f"{role.value.title()} User"
    u.role = role.value
    u.is_active = is_active
    u.team_id = uuid.uuid4()
    return u


@pytest.mark.asyncio
async def test_admin_can_grant_team_admin(db: AsyncSession):
    """ADMIN seeded user can promote another user to team_admin."""
    team = Team(name="Grant Test Team")
    db.add(team)
    await db.flush()

    admin_user = User(
        email="admin_grant@example.com",
        password_hash="x",
        full_name="Admin",
        role=UserRole.ADMIN,
        team_id=team.id,
    )
    target_user = User(
        email="target_grant@example.com",
        password_hash="x",
        full_name="Target",
        role=UserRole.MEMBER,
        team_id=team.id,
    )
    db.add(admin_user)
    db.add(target_user)
    await db.flush()

    from app.api.v1.users import update_user_role, RoleUpdate

    body = RoleUpdate(role=UserRole.TEAM_ADMIN)
    response = await update_user_role(
        user_id=target_user.id,
        body=body,
        db=db,
        admin=admin_user,
    )

    assert response.role == "team_admin"

    # Confirm the DB row was updated
    from sqlalchemy import select
    result = await db.execute(select(User).where(User.id == target_user.id))
    refreshed = result.scalar_one()
    assert refreshed.role == UserRole.TEAM_ADMIN


@pytest.mark.asyncio
async def test_non_admin_cannot_grant_team_admin():
    """Non-admin actor hitting PATCH role → 403 from require_admin."""
    from app.api.deps import require_admin

    member = _make_user(role=UserRole.MEMBER)
    with pytest.raises(HTTPException) as exc_info:
        await require_admin(current_user=member)
    assert exc_info.value.status_code == 403
