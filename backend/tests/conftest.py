"""Shared pytest fixtures for all test layers."""
from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import types
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base


# ── SQLite compat: map PostgreSQL ARRAY/JSONB → JSON text ────────────────────

class _PgTypeAsJSON(types.TypeDecorator):
    """Store PostgreSQL ARRAY/JSONB columns as JSON text in SQLite."""
    impl = types.Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return json.dumps(value)
        return None

    def process_result_value(self, value, dialect):
        if value is not None:
            return json.loads(value)
        return None


# ── In-memory SQLite async engine ────────────────────────────────────────────

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def engine():
    # Replace PostgreSQL-only column types with JSON-backed text for SQLite.
    # v4.0 P1: also remap pgvector.Vector when present so MemoryEntry can
    # round-trip in the in-memory SQLite test engine.
    try:
        from pgvector.sqlalchemy import Vector
        pgvector_types: tuple[type, ...] = (Vector,)
    except ImportError:
        pgvector_types = ()

    for table in Base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, (ARRAY, JSONB)):
                col.type = _PgTypeAsJSON()
            elif pgvector_types and isinstance(col.type, pgvector_types):
                col.type = _PgTypeAsJSON()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db(engine) -> AsyncGenerator[AsyncSession, None]:
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    async with async_session() as session:
        async with session.begin():
            yield session
            await session.rollback()


# ── Mock Docker backend ───────────────────────────────────────────────────────

@pytest.fixture
def mock_docker_backend():
    backend = MagicMock()
    backend.start = AsyncMock(return_value="test-container-id")
    backend.stop = AsyncMock()
    backend.cleanup = AsyncMock()

    async def _mock_logs(exec_id: str):
        yield "Starting scan..."
        yield "Scan complete."

    backend.stream_logs = _mock_logs
    return backend


# ── Sample data ───────────────────────────────────────────────────────────────

@pytest.fixture
def sample_target():
    return {
        "ip_ranges": ["192.168.1.0/24"],
        "domains": ["example.com"],
    }


@pytest.fixture
def sample_whitelist_rules():
    return {
        "ip_ranges": ["192.168.1.0/24", "10.0.0.0/8"],
        "domains": ["example.com", "test.local"],
    }


@pytest.fixture
def sample_session_id():
    return uuid.uuid4()


@pytest.fixture
def sample_user_id():
    return str(uuid.uuid4())
