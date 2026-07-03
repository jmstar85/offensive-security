"""Memorist role (v4.0 P2a).

Thin v1 RAG: one search tool (`search_in_memory`) backed by pgvector +
`sentence-transformers/all-MiniLM-L6-v2` (384-dim, local CPU). The role
exposes `search_in_memory(query, k, score_threshold)` as a helper used by
both:
- `Generator.run()` — auto-call before producing SubTask draft_plan (P4).
- `Pentester.run()` — auto-call pre-SubTask (P4 hook).

P2a ships the role class + the `search_in_memory` helper. P4 wires the
auto-call hooks at SubTask boundaries.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.memory_entry import MemoryEntry
from app.orchestrator.roles.base import Role, RoleResult
from app.orchestrator.roles.registry import register_role
from app.orchestrator.roles import memorist_embedding


MEMORIST_SYSTEM_PROMPT = """\
You are the Memorist role of the OSA platform. Your only tool is
`search_in_memory(query, k=3, score_threshold=0.7)`. Given a query string,
return the top-K memory entries above the threshold from the pgvector store
seeded from `backend/app/knowledge/*.yaml`. Use the returned entries to
ground subsequent agent decisions. Do not invent entries the store did not
return.
"""


async def search_in_memory(
    db: AsyncSession,
    query: str,
    k: int = 3,
    score_threshold: float = 0.7,
) -> list[MemoryEntry]:
    """Embed the query and return the top-K memory entries above threshold.

    Uses pgvector's cosine distance operator `<=>`. The Memorist role calls
    this helper from `run()` (and Generator/Pentester call it directly as a
    pre-SubTask hook in P4).
    """
    await memorist_embedding.get_or_load_model()
    vector = memorist_embedding.embed_one(query)

    # Use a parameterized SQL fragment because pgvector's operators aren't
    # in SQLAlchemy's core grammar. The Vector column accepts list/numpy input.
    stmt = (
        select(
            MemoryEntry,
            (1 - MemoryEntry.embedding.cosine_distance(vector)).label("score"),
        )
        .order_by(MemoryEntry.embedding.cosine_distance(vector))
        .limit(k)
    )
    rows = (await db.execute(stmt)).all()
    return [entry for entry, score in rows if score >= score_threshold]


@dataclass
class Memorist(Role):
    slug: str = "memorist"

    def __init__(self, llm_model: str | None = None) -> None:
        super().__init__(
            name="memorist",
            system_prompt=MEMORIST_SYSTEM_PROMPT,
            llm_model=llm_model or settings.anthropic_default_model,
            tools_allowed=["search_in_memory", "done"],
            max_tool_calls=settings.limited_role_max_tool_calls,
        )

    async def run(
        self, performer: Any, context: dict[str, Any], client_factory: Any = None
    ) -> RoleResult:
        """Smoke implementation for P2a. Returns empty findings — P4 wires
        the actual pgvector lookup via the helper above.

        Non-consuming role: ``client_factory`` (PR6) is accepted-and-ignored so
        the uniform launch site can forward it to every role without a
        ``TypeError``."""
        return RoleResult(
            role_name=self.name,
            messages=[],
            finished=True,
            tool_calls=0,
        )


register_role(Memorist)
