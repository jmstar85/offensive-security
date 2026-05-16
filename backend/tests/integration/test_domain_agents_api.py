"""Integration tests for GET /api/v1/domain-agents (plan v3.2.1 §3 / P2).

The endpoint does not touch the database — it serializes the in-code
DOMAIN_AGENTS dict. Tests therefore override only ``get_current_user`` and
short-circuit the DB dependency, which keeps the auth + RBAC paths exercised
without depending on user-fixture password hashing.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.user import UserRole


def _user(role: str):
    return SimpleNamespace(
        id=uuid.uuid4(),
        email=f"{role}@example.com",
        full_name=role.title(),
        role=role,
        is_active=True,
        team_id=uuid.uuid4(),
    )


def _override(user):
    from app.api.deps import get_current_user
    from app.core.database import get_db

    async def _user_dep():
        return user

    async def _db_dep():
        yield None  # endpoint does not call .execute

    app.dependency_overrides[get_current_user] = _user_dep
    app.dependency_overrides[get_db] = _db_dep


@pytest.mark.asyncio
async def test_list_excludes_admin_only_for_member():
    _override(_user(UserRole.MEMBER))
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            r = await ac.get("/api/v1/domain-agents/")
        assert r.status_code == 200
        slugs = {a["slug"] for a in r.json()}
        # 7 non-admin agents
        assert slugs == {
            "web-app-agent", "network-agent",
            "cloud-aws-agent", "cloud-azure-agent", "cloud-gcp-agent",
            "api-security-agent", "osint-agent",
        }
        assert "mobile-agent" not in slugs
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_includes_admin_only_for_admin():
    _override(_user(UserRole.ADMIN))
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            r = await ac.get("/api/v1/domain-agents/")
        assert r.status_code == 200
        slugs = {a["slug"] for a in r.json()}
        assert len(slugs) == 8
        assert "mobile-agent" in slugs
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_unknown_returns_404():
    _override(_user(UserRole.MEMBER))
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            r = await ac.get("/api/v1/domain-agents/blue-team-agent")
        assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_member_cannot_get_admin_only_agent():
    _override(_user(UserRole.MEMBER))
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            r = await ac.get("/api/v1/domain-agents/mobile-agent")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_palette_derived_from_registry():
    _override(_user(UserRole.ADMIN))
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            r = await ac.get("/api/v1/domain-agents/web-app-agent")
        assert r.status_code == 200
        body = r.json()
        slugs = {t["slug"] for t in body["tool_palette"]}
        assert {"httpx", "subfinder", "wappalyzer", "passive_recon"} <= slugs
        assert body["default_risk_tier"] in {
            "passive_no_target_contact", "passive_low_touch",
            "active_recon", "active_exploit",
        }
        assert body["admin_only"] is False
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_admin_only_agent_has_admin_only_flag():
    _override(_user(UserRole.ADMIN))
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            r = await ac.get("/api/v1/domain-agents/mobile-agent")
        assert r.status_code == 200
        assert r.json()["admin_only"] is True
    finally:
        app.dependency_overrides.clear()
