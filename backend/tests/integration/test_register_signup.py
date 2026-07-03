"""Integration: POST /api/v1/auth/register public self-signup.

Verifies:
  - A new account is created with the full-access signup role (admin, for now),
    email normalized to lowercase, and a personal team auto-created.
  - A custom team_name is honoured (and trimmed).
  - Duplicate email is rejected case-insensitively (400, no second user).
  - Short password rejected by the request schema.

hash_password is patched with a deterministic stand-in for speed/determinism;
real bcrypt round-trips are covered by tests/unit/test_security_password.py.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import RegisterRequest, register
from app.core.config import settings
from app.models.user import Team, User


def _fake_hash(password: str) -> str:
    return f"hashed::{password}"


@pytest.fixture(autouse=True)
def _patch_hashing():
    with patch("app.api.v1.auth.hash_password", side_effect=_fake_hash):
        yield


@pytest.mark.asyncio
async def test_register_creates_full_access_account(db: AsyncSession):
    body = RegisterRequest(
        email="New@KT.com", password="MemberPass123", full_name="New User"
    )
    resp = await register(body=body, db=db)

    assert resp.email == "new@kt.com"  # normalized
    # Default role gives every signup full access (no admin/user distinction).
    assert resp.role == settings.default_signup_role
    assert settings.default_signup_role == "admin"

    team = (
        await db.execute(select(Team).where(Team.id == resp.team_id))
    ).scalar_one()
    assert team.name == "New User's Team"

    created = (
        await db.execute(select(User).where(User.email == "new@kt.com"))
    ).scalar_one()
    assert created.password_hash == _fake_hash("MemberPass123")


@pytest.mark.asyncio
async def test_register_custom_team_name_trimmed(db: AsyncSession):
    body = RegisterRequest(
        email="lead@kt.com",
        password="MemberPass123",
        full_name="Lead",
        team_name="  Red Cell  ",
    )
    resp = await register(body=body, db=db)
    team = (
        await db.execute(select(Team).where(Team.id == resp.team_id))
    ).scalar_one()
    assert team.name == "Red Cell"


@pytest.mark.asyncio
async def test_register_duplicate_email_case_insensitive_400(db: AsyncSession):
    await register(
        body=RegisterRequest(
            email="dup@kt.com", password="MemberPass123", full_name="First"
        ),
        db=db,
    )
    with pytest.raises(HTTPException) as exc:
        await register(
            body=RegisterRequest(
                email="DUP@kt.com", password="MemberPass123", full_name="Second"
            ),
            db=db,
        )
    assert exc.value.status_code == 400

    count = (
        await db.execute(select(func.count()).select_from(User))
    ).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_register_long_full_name_team_name_bounded(db: AsyncSession):
    """A max-length full_name must not overflow Team.name (String(255))."""
    body = RegisterRequest(
        email="long@kt.com", password="MemberPass123", full_name="X" * 255
    )
    resp = await register(body=body, db=db)
    team = (
        await db.execute(select(Team).where(Team.id == resp.team_id))
    ).scalar_one()
    assert len(team.name) <= 255


@pytest.mark.asyncio
async def test_register_blank_full_name_falls_back_to_personal_team(db: AsyncSession):
    body = RegisterRequest(
        email="blank@kt.com", password="MemberPass123", full_name="   "
    )
    resp = await register(body=body, db=db)
    team = (
        await db.execute(select(Team).where(Team.id == resp.team_id))
    ).scalar_one()
    assert team.name == "Personal Team"


def test_register_short_password_rejected_by_schema():
    with pytest.raises(ValidationError):
        RegisterRequest(email="x@kt.com", password="short", full_name="X")
