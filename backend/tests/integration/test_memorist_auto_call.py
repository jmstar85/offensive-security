"""Memorist auto-call tests (v4.0 P4)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.orchestrator.memorist_auto_call import auto_inject


@pytest.mark.asyncio
async def test_auto_inject_empty_description_returns_empty_list(db):
    """Empty SubTask description short-circuits to an empty list."""
    assert await auto_inject(db, "") == []


@pytest.mark.asyncio
async def test_auto_inject_returns_dicts_not_orm_objects(db, monkeypatch):
    """Successful path: returns plain dicts with name/description/domain_tag."""
    fake_entries = [
        type("E", (), {
            "name": "sqli_intent",
            "description": "SQL injection probe",
            "domain_tag": "web",
            "source_yaml_path": "knowledge/web/sqli.yaml",
        })(),
        type("E", (), {
            "name": "xss_intent",
            "description": "Reflected XSS probe",
            "domain_tag": "web",
            "source_yaml_path": "knowledge/web/xss.yaml",
        })(),
    ]

    async def _fake_search(_db, query, k, score_threshold):
        return fake_entries

    monkeypatch.setattr(
        "app.orchestrator.roles.memorist.search_in_memory",
        _fake_search,
    )

    result = await auto_inject(db, "scan /login.php for sqli")
    assert len(result) == 2
    assert result[0]["name"] == "sqli_intent"
    assert "description" in result[0]
    assert "domain_tag" in result[0]
    # ORM coupling is broken — no leak of SQLAlchemy session/relationship.
    assert "_sa_instance_state" not in result[0]


@pytest.mark.asyncio
async def test_auto_inject_swallows_pgvector_errors(db, monkeypatch):
    """When the embedding stack is unavailable, auto-call is a no-op,
    NOT an exception that blocks the SubTask."""
    async def _raise(_db, query, k, score_threshold):
        raise RuntimeError("pgvector not installed in CI")

    monkeypatch.setattr(
        "app.orchestrator.roles.memorist.search_in_memory",
        _raise,
    )
    # Must return [] without re-raising.
    result = await auto_inject(db, "any description")
    assert result == []
