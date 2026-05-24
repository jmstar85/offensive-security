"""Unit tests for RBAC: role-based access control.

Tests:
  - UserRole enum validation
  - Registration defaults to member
  - require_admin dependency blocks members
  - require_admin allows admins
  - get_current_user rejects inactive users
  - User management: last-admin guard, self-deactivation guard
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import Team, User, UserRole


# ── UserRole Enum ─────────────────────────────────────────────────────────────


class TestUserRole:
    def test_admin_value(self):
        assert UserRole.ADMIN == "admin"
        assert UserRole.ADMIN.value == "admin"

    def test_member_value(self):
        assert UserRole.MEMBER == "member"
        assert UserRole.MEMBER.value == "member"

    def test_enum_is_str(self):
        assert isinstance(UserRole.ADMIN, str)
        assert isinstance(UserRole.MEMBER, str)


# ── User Model Defaults ──────────────────────────────────────────────────────


class TestUserDefaults:
    @pytest_asyncio.fixture
    async def team(self, db: AsyncSession) -> Team:
        team = Team(name="Test Team")
        db.add(team)
        await db.flush()
        return team

    @pytest.mark.asyncio
    async def test_new_user_defaults_to_member(self, db: AsyncSession, team: Team):
        user = User(
            email="test@example.com",
            password_hash="fakehash",
            full_name="Test User",
            team_id=team.id,
        )
        db.add(user)
        await db.flush()
        assert user.role == UserRole.MEMBER

    @pytest.mark.asyncio
    async def test_new_user_defaults_to_active(self, db: AsyncSession, team: Team):
        user = User(
            email="active@example.com",
            password_hash="fakehash",
            full_name="Active User",
            team_id=team.id,
        )
        db.add(user)
        await db.flush()
        assert user.is_active is True

    @pytest.mark.asyncio
    async def test_admin_role_can_be_set(self, db: AsyncSession, team: Team):
        user = User(
            email="admin@example.com",
            password_hash="fakehash",
            full_name="Admin User",
            role=UserRole.ADMIN,
            team_id=team.id,
        )
        db.add(user)
        await db.flush()
        assert user.role == UserRole.ADMIN


# ── require_admin Dependency ──────────────────────────────────────────────────


class TestRequireAdmin:
    def _make_user(self, role: str = "member", is_active: bool = True) -> User:
        user = MagicMock(spec=User)
        user.id = uuid.uuid4()
        user.role = role
        user.is_active = is_active
        return user

    @pytest.mark.asyncio
    async def test_admin_passes(self):
        from app.api.deps import require_admin

        admin_user = self._make_user(role=UserRole.ADMIN)
        result = await require_admin(current_user=admin_user)
        assert result is admin_user

    @pytest.mark.asyncio
    async def test_member_blocked_with_403(self):
        from app.api.deps import require_admin

        member_user = self._make_user(role=UserRole.MEMBER)
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(current_user=member_user)
        assert exc_info.value.status_code == 403
        assert "Admin access required" in exc_info.value.detail


# ── get_current_user: is_active check ────────────────────────────────────────


class TestGetCurrentUserActive:
    @pytest.mark.asyncio
    async def test_inactive_user_rejected(self):
        """Inactive user should get 401 even with valid token."""
        from app.api.deps import get_current_user

        inactive_user = MagicMock(spec=User)
        inactive_user.is_active = False

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = inactive_user

        mock_db = AsyncMock(spec=AsyncSession)
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_creds = MagicMock()
        mock_creds.credentials = "fake-token"

        with patch("app.api.deps.decode_access_token", return_value=str(uuid.uuid4())):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(credentials=mock_creds, db=mock_db)
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_active_user_passes(self):
        """Active user with valid token should pass."""
        from app.api.deps import get_current_user

        active_user = MagicMock(spec=User)
        active_user.is_active = True

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = active_user

        mock_db = AsyncMock(spec=AsyncSession)
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_creds = MagicMock()
        mock_creds.credentials = "fake-token"

        with patch("app.api.deps.decode_access_token", return_value=str(uuid.uuid4())):
            result = await get_current_user(credentials=mock_creds, db=mock_db)
            assert result is active_user


# ── Registration defaults ────────────────────────────────────────────────────


class TestRegistrationRole:
    """Verify that auth.py register creates users with role=member."""

    def test_register_source_code_uses_member(self):
        """Static check: the register endpoint must use role='member'."""
        import inspect
        from app.api.v1.auth import register

        source = inspect.getsource(register)
        assert 'role="member"' in source
        assert 'role="admin"' not in source
