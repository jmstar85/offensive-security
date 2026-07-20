"""Fix 3 + Fix 4 (session 0f9c5646 root cause): the interview/Generator send must
use a response budget above the provider default so a multi-step draft_plan JSON
is not truncated, and the Generator prompt must cap the interview draft to a
concise skeleton (while KEEPING per-step config for the scope preview).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.orchestrator.roles.generator import GENERATOR_SYSTEM_PROMPT, Generator


def test_interview_max_tokens_exceeds_provider_default():
    # Provider send defaults are 4096 (2048 for legacy ModelClient); the interview
    # budget must exceed them so the draft_plan JSON does not truncate.
    assert settings.interview_max_tokens > 4096


@pytest.mark.asyncio
async def test_generator_send_passes_interview_max_tokens():
    resp = SimpleNamespace(
        text='{"ambiguity":0.1,"blockers":[],"reasoning":"","draft_plan":{"steps":[]}}',
        tokens_in=1,
        tokens_out=1,
    )
    client = SimpleNamespace(send=AsyncMock(return_value=resp))

    async def factory(_role_name):
        return client

    await Generator().run(
        performer=None,
        context={"user_content": "scan 10.0.0.0/24", "history": [], "send_model_id": "copilot/x"},
        client_factory=factory,
    )
    client.send.assert_awaited_once()
    assert client.send.await_args.kwargs["max_tokens"] == settings.interview_max_tokens


def test_generator_prompt_caps_skeleton_and_keeps_config():
    # Fix 4: the interview draft must be a concise skeleton (bounded step count),
    # but per-step config must still be requested (the scope preview reads it).
    assert "AT MOST 8" in GENERATOR_SYSTEM_PROMPT
    assert "config" in GENERATOR_SYSTEM_PROMPT
