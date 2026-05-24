"""Generator role smoke test (v4.0 P2a)."""
from __future__ import annotations

import pytest

from app.orchestrator.roles.generator import Generator, GENERATOR_SYSTEM_PROMPT


def test_generator_has_expected_palette():
    """Generator's tools_allowed includes the barrier tools + Memorist search."""
    role = Generator()
    assert "ask" in role.tools_allowed
    assert "done" in role.tools_allowed
    assert "search_in_memory" in role.tools_allowed


def test_generator_system_prompt_mentions_envelope():
    """The system prompt must mention `ambiguity` and `draft_plan` so the
    LLM produces the expected JSON envelope (matches v3.2.1 contract)."""
    assert "ambiguity" in GENERATOR_SYSTEM_PROMPT
    assert "draft_plan" in GENERATOR_SYSTEM_PROMPT
    assert "blockers" in GENERATOR_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_generator_smoke_run_returns_envelope():
    """P2a smoke: run() returns a fixture envelope so wire-up is testable."""
    role = Generator()
    result = await role.run(performer=None, context={})
    assert result.role_name == "generator"
    assert result.finished is False  # Generator keeps the chain open
    # Smoke envelope is encoded as the assistant message body.
    assert "ambiguity" in result.messages[0]["content"]
