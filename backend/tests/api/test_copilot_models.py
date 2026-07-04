"""GET /config/copilot/models — live Copilot model list + curated fallback."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1.copilot_models import CURATED_COPILOT_MODELS, get_copilot_models

_RESOLVE = "app.orchestrator.llm.credential_resolver.resolve_provider_credential"
_LIST = "app.orchestrator.llm.copilot_provider.CopilotProvider.list_models"


def _user():
    u = MagicMock()
    u.id = uuid.uuid4()
    return u


@pytest.mark.asyncio
async def test_no_credential_returns_curated_fallback():
    from app.orchestrator.llm.credential_resolver import CredentialNotFound

    with patch(_RESOLVE, AsyncMock(side_effect=CredentialNotFound("none"))):
        result = await get_copilot_models(db=MagicMock(), current_user=_user())
    assert result["reachable"] is False
    assert result["models"] == CURATED_COPILOT_MODELS


@pytest.mark.asyncio
async def test_live_list_is_namespaced_and_reachable():
    with patch(_RESOLVE, AsyncMock(return_value="ghtok")), patch(
        _LIST, AsyncMock(return_value=["gpt-4.1", "claude-sonnet-4.5", "o4-mini"])
    ):
        result = await get_copilot_models(db=MagicMock(), current_user=_user())
    assert result["reachable"] is True
    assert result["models"] == [
        "copilot/gpt-4.1",
        "copilot/claude-sonnet-4.5",
        "copilot/o4-mini",
    ]


@pytest.mark.asyncio
async def test_list_error_falls_back_soft():
    from app.orchestrator.llm.base import ModelUnreachable

    with patch(_RESOLVE, AsyncMock(return_value="ghtok")), patch(
        _LIST, AsyncMock(side_effect=ModelUnreachable("copilot down"))
    ):
        result = await get_copilot_models(db=MagicMock(), current_user=_user())
    assert result["reachable"] is False
    assert result["models"] == CURATED_COPILOT_MODELS


@pytest.mark.asyncio
async def test_empty_live_list_falls_back():
    with patch(_RESOLVE, AsyncMock(return_value="ghtok")), patch(
        _LIST, AsyncMock(return_value=[])
    ):
        result = await get_copilot_models(db=MagicMock(), current_user=_user())
    assert result["reachable"] is False
    assert result["models"] == CURATED_COPILOT_MODELS
