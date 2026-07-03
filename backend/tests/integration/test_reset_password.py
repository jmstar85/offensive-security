"""Integration: POST /api/v1/auth/reset-password self-service password reset.

Verifies:
  - Correct email + current password → hash updated, audit row written.
  - Wrong current password → 401 (generic), hash unchanged.
  - Unknown email → 401 (generic, no user enumeration).
  - Inactive user → 401 even with correct current password.
  - New password identical to current → 400.
  - Too-short new password rejected by the request schema.

The password hashing primitives are patched with deterministic stand-ins so the
endpoint's *branching logic* is exercised quickly and independently of bcrypt.
Real bcrypt round-trips are covered by tests/unit/test_security_password.py.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import ResetPasswordRequest, reset_password
from app.models.audit import AuditLog
from app.models.user import Team, User, UserRole


def _fake_hash(password: str) -> str:
    return f"hashed::{password}"


def _fake_verify(plain: str, hashed: str) -> bool:
    return hashed == f"hashed::{plain}"


async def _seed_user(db: AsyncSession, *, password: str, is_active: bool = True) -> User:
    team = Team(name="Reset Test Team")
    db.add(team)
    await db.flush()
    user = User(
        email="admin@kt.com",
        password_hash=_fake_hash(password),
        full_name="System Admin",
        role=UserRole.ADMIN,
        is_active=is_active,
        team_id=team.id,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.fixture(autouse=True)
def _patch_hashing():
    with (
        patch("app.api.v1.auth.hash_password", side_effect=_fake_hash),
        patch("app.api.v1.auth.verify_password", side_effect=_fake_verify),
    ):
        yield


@pytest.mark.asyncio
async def test_reset_password_happy_path(db: AsyncSession):
    user = await _seed_user(db, password="OldPass123")

    body = ResetPasswordRequest(
        email="admin@kt.com",
        current_password="OldPass123",
        new_password="BrandNewPass456",
    )
    resp = await reset_password(body=body, db=db)
    assert resp.detail == "Password updated successfully"

    refreshed = (
        await db.execute(select(User).where(User.id == user.id))
    ).scalar_one()
    assert refreshed.password_hash == _fake_hash("BrandNewPass456")

    audit = (
        await db.execute(
            select(AuditLog).where(AuditLog.action == "user.password_reset")
        )
    ).scalar_one()
    assert audit.actor_id == user.id
    assert audit.target_id == str(user.id)


@pytest.mark.asyncio
async def test_reset_password_wrong_current_password(db: AsyncSession):
    user = await _seed_user(db, password="OldPass123")

    body = ResetPasswordRequest(
        email="admin@kt.com",
        current_password="WrongPass000",
        new_password="BrandNewPass456",
    )
    with pytest.raises(HTTPException) as exc:
        await reset_password(body=body, db=db)
    assert exc.value.status_code == 401
    assert exc.value.detail == "Invalid email or current password"

    refreshed = (
        await db.execute(select(User).where(User.id == user.id))
    ).scalar_one()
    assert refreshed.password_hash == _fake_hash("OldPass123")


@pytest.mark.asyncio
async def test_reset_password_unknown_email_generic_401(db: AsyncSession):
    await _seed_user(db, password="OldPass123")

    body = ResetPasswordRequest(
        email="nobody@kt.com",
        current_password="OldPass123",
        new_password="BrandNewPass456",
    )
    with pytest.raises(HTTPException) as exc:
        await reset_password(body=body, db=db)
    assert exc.value.status_code == 401
    assert exc.value.detail == "Invalid email or current password"


@pytest.mark.asyncio
async def test_reset_password_inactive_user_rejected(db: AsyncSession):
    await _seed_user(db, password="OldPass123", is_active=False)

    body = ResetPasswordRequest(
        email="admin@kt.com",
        current_password="OldPass123",
        new_password="BrandNewPass456",
    )
    with pytest.raises(HTTPException) as exc:
        await reset_password(body=body, db=db)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_reset_password_same_as_current_rejected(db: AsyncSession):
    await _seed_user(db, password="SamePass123")

    body = ResetPasswordRequest(
        email="admin@kt.com",
        current_password="SamePass123",
        new_password="SamePass123",
    )
    with pytest.raises(HTTPException) as exc:
        await reset_password(body=body, db=db)
    assert exc.value.status_code == 400


def test_reset_password_short_new_password_rejected_by_schema():
    with pytest.raises(ValidationError):
        ResetPasswordRequest(
            email="admin@kt.com",
            current_password="OldPass123",
            new_password="short",
        )
