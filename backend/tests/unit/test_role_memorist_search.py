"""Memorist role + `search_in_memory` helper tests (v4.0 P2a).

The pgvector cosine-similarity query is not exercised here — the SQLite
test engine remaps Vector to JSON text and lacks pgvector operators.
Integration of the live similarity query is covered in
`backend/tests/integration/test_performer_full_cycle.py` (mocked) and in
production smoke after `python -m app.knowledge.seed_memory`.
"""
from __future__ import annotations

import pytest

from app.orchestrator.roles.memorist import (
    MEMORIST_SYSTEM_PROMPT,
    Memorist,
    search_in_memory,
)


def test_memorist_palette_is_minimal():
    """Thin v1: Memorist only knows `search_in_memory` and `done`."""
    role = Memorist()
    assert role.tools_allowed == ["search_in_memory", "done"]


def test_memorist_system_prompt_mentions_threshold():
    """The prompt must reference k=3 + threshold=0.7 so the LLM produces
    queries scoped to the v4.0 plan constants."""
    assert "search_in_memory" in MEMORIST_SYSTEM_PROMPT
    assert "k=3" in MEMORIST_SYSTEM_PROMPT
    assert "score_threshold" in MEMORIST_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_memorist_smoke_run_returns_empty_findings():
    """P2a smoke: run() returns empty findings (real lookup wired in P4)."""
    role = Memorist()
    result = await role.run(performer=None, context={})
    assert result.role_name == "memorist"
    assert result.finished is True
    assert result.messages == []


def test_search_in_memory_helper_is_callable():
    """The helper coroutine exists at the documented module path so P4 can
    call it directly from Pentester's pre-SubTask hook."""
    assert callable(search_in_memory)
