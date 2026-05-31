"""Unit tests: UserRole enum has exactly {ADMIN, MEMBER, TEAM_ADMIN} values."""
from __future__ import annotations

from app.models.user import UserRole


def test_enum_has_exactly_three_members():
    assert set(UserRole) == {UserRole.ADMIN, UserRole.MEMBER, UserRole.TEAM_ADMIN}


def test_admin_string_value():
    assert UserRole.ADMIN.value == "admin"


def test_member_string_value():
    assert UserRole.MEMBER.value == "member"


def test_team_admin_string_value():
    assert UserRole.TEAM_ADMIN.value == "team_admin"


def test_all_roles_are_str_instances():
    for role in UserRole:
        assert isinstance(role, str)
