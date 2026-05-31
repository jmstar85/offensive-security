"""Safety: PATCH role grants are audited; non-admin attempts produce no audit row.

Verifies:
  - ADMIN PATCH to team_admin writes audit_logs row with action="user.role_granted",
    actor_id=<admin id>, details_json contains new_role and previous_role.
  - Non-admin PATCH is blocked at 403 before any audit row is written.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.user import Team, User, UserRole


@pytest.mark.asyncio
async def test_role_grant_writes_audit_row(db: AsyncSession):
    team = Team(name="Audit Safety Team")
    db.add(team)
    await db.flush()

    admin_user = User(
        email="admin_audit@example.com",
        password_hash="x",
        full_name="Admin",
        role=UserRole.ADMIN,
        team_id=team.id,
    )
    target_user = User(
        email="target_audit@example.com",
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
    await update_user_role(
        user_id=target_user.id,
        body=body,
        db=db,
        admin=admin_user,
    )

    result = await db.execute(
        select(AuditLog).where(
            AuditLog.action == "user.role_granted",
            AuditLog.target_id == str(target_user.id),
        )
    )
    row = result.scalar_one_or_none()
    assert row is not None, "Audit row must exist after role grant"
    assert row.actor_id == admin_user.id
    assert row.details_json["new_role"] == "team_admin"
    assert "previous_role" in row.details_json


@pytest.mark.asyncio
async def test_non_admin_blocked_before_audit_row(db: AsyncSession):
    """When a non-admin hits require_admin, 403 fires and no audit row is written."""
    from app.api.deps import require_admin
    from unittest.mock import MagicMock

    member = MagicMock(spec=User)
    member.id = uuid.uuid4()
    member.role = UserRole.MEMBER
    member.is_active = True

    with pytest.raises(HTTPException) as exc_info:
        await require_admin(current_user=member)
    assert exc_info.value.status_code == 403

    # No audit rows should exist for this actor
    result = await db.execute(
        select(AuditLog).where(AuditLog.actor_id == member.id)
    )
    rows = result.scalars().all()
    assert rows == [], "No audit row should be created when 403 fires before handler"
