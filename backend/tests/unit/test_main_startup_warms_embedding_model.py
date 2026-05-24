"""FastAPI startup warm-up test (v4.0 P1, Open Issue #2 resolution).

Verifies that `app.main._warm_embedding_model()` calls
`memorist_embedding.get_or_load_model()` during the lifespan startup phase, so
the first user-facing Memorist call does not pay the 2-4s SentenceTransformer
cold-start cost.

The actual model load is mocked out to avoid downloading ~80MB during unit
tests.
"""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest

from app.main import _warm_embedding_model


@pytest.mark.asyncio
async def test_warm_embedding_model_calls_loader():
    """Startup hook delegates to `memorist_embedding.get_or_load_model()`."""
    with patch(
        "app.orchestrator.roles.memorist_embedding.get_or_load_model",
        new_callable=AsyncMock,
    ) as mock_loader:
        mock_loader.return_value = object()  # fake non-None model
        await _warm_embedding_model()
        mock_loader.assert_awaited_once()


@pytest.mark.asyncio
async def test_warm_embedding_model_does_not_crash_on_loader_failure(caplog):
    """A failure in `get_or_load_model` must NOT block app startup —
    it logs a warning and continues so the first request can fall back to
    cold-load."""
    caplog.set_level(logging.WARNING)

    with patch(
        "app.orchestrator.roles.memorist_embedding.get_or_load_model",
        new_callable=AsyncMock,
    ) as mock_loader:
        mock_loader.side_effect = RuntimeError("simulated model download failure")
        # Must not raise.
        await _warm_embedding_model()

    # The warning should mention the failure.
    assert any("Embedding warm-up failed" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_warm_embedding_model_logs_success(caplog):
    """On successful load, the startup hook logs the model name + dim so
    operators can confirm warm-up landed."""
    caplog.set_level(logging.INFO)
    with patch(
        "app.orchestrator.roles.memorist_embedding.get_or_load_model",
        new_callable=AsyncMock,
    ) as mock_loader:
        mock_loader.return_value = object()
        await _warm_embedding_model()
    assert any("Embedding model warmed" in record.message for record in caplog.records)
