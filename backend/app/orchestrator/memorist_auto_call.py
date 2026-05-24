"""Memorist auto-call (v4.0 P4).

Pre-SubTask hook called by Pentester (and optionally Generator) at the
start of each SubTask. Embeds the SubTask description, runs the pgvector
cosine-similarity lookup, and returns the top-K memory entries above the
score threshold. The caller merges those entries into the role's context
window.

Returns an empty list if pgvector or sentence-transformers are unavailable
(graceful no-op) so that v4.0 P1 environments without the embedding stack
still pass the v3.2.1 baseline tests.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = logging.getLogger(__name__)


async def auto_inject(
    db: AsyncSession,
    subtask_description: str,
) -> list[dict[str, Any]]:
    """Look up top-K memory entries for a SubTask description and return the
    top matches above `settings.memorist_score_threshold` as plain dicts
    (so callers can merge them into LLM context without ORM coupling).
    """
    if not subtask_description:
        return []
    try:
        from app.orchestrator.roles.memorist import search_in_memory

        entries = await search_in_memory(
            db,
            query=subtask_description,
            k=settings.memorist_k,
            score_threshold=settings.memorist_score_threshold,
        )
    except Exception as e:
        # No embeddings installed yet, or DB without pgvector — fall back
        # to no-op rather than blocking the SubTask.
        logger.info("Memorist auto-call no-op: %s", e)
        return []

    return [
        {
            "name": e.name,
            "description": e.description,
            "domain_tag": e.domain_tag,
            "source_yaml_path": e.source_yaml_path,
        }
        for e in entries
    ]
