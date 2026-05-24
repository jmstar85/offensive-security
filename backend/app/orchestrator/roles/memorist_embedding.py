"""Embedding-model singleton for the Memorist role (v4.0 P1).

This module owns the lazy SentenceTransformer instance used by:
- `app.main.lifespan` startup warm-up (P1) — pre-loads to avoid 2-4s cold start
- `app.orchestrator.roles.memorist` (P2a) — for query+chunk embedding
- `app.knowledge.seed_memory` (P1) — for one-shot seed of the knowledge corpus

The singleton lives at module scope. The first `get_or_load_model()` call loads
the model from disk (or downloads on first run); subsequent calls reuse it.
Model name and vector dimension come from `settings`.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_model: Any | None = None
_load_lock = asyncio.Lock()


async def get_or_load_model() -> Any:
    """Return the cached SentenceTransformer instance, loading it on first call.

    Async-safe via `_load_lock` so multiple concurrent startup awaits do not
    trigger duplicate downloads. The load itself runs in a thread executor
    because `SentenceTransformer.__init__` is synchronous and CPU-bound.
    """
    global _model
    if _model is not None:
        return _model

    async with _load_lock:
        if _model is not None:
            return _model
        from sentence_transformers import SentenceTransformer

        loop = asyncio.get_running_loop()
        _model = await loop.run_in_executor(
            None, SentenceTransformer, settings.embedding_model_name
        )
        logger.info(
            "SentenceTransformer loaded: %s (vector_dim=%d)",
            settings.embedding_model_name,
            settings.embedding_vector_dim,
        )
        return _model


def embed_one(text: str) -> list[float]:
    """Synchronously embed one string. Used by seed scripts (P1) and Memorist (P2a).

    Returns a 384-element list of floats (vector_dim from settings). Raises
    RuntimeError if the model has not been loaded yet — call
    `get_or_load_model()` first (or rely on the startup warm-up hook).
    """
    if _model is None:
        raise RuntimeError(
            "Embedding model not loaded. Call `await get_or_load_model()` "
            "or rely on the FastAPI startup warm-up hook before `embed_one`."
        )
    vector = _model.encode(text, normalize_embeddings=True)
    return vector.tolist()


def reset_model_for_tests() -> None:
    """Test helper — clears the cached model so a unit test can verify
    cold-start path without contaminating other tests. Not used outside
    `backend/tests/`."""
    global _model
    _model = None
