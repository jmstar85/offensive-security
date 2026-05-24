"""MemoryEntry model (v4.0 P1) — vector embeddings for Memorist Thin v1 RAG.

PentAGI parallel: PentAGI's `msglogs.embedding` + `subtasks.embedding` pgvector
columns. OSA adopts a separate `memory_entries` table seeded from the existing
`backend/app/knowledge/*.yaml` corpus (chunked by `description`).

Embedding model: `sentence-transformers/all-MiniLM-L6-v2` (384-dim, local CPU).
Index: hnsw with `m=16, ef_construction=64`, distance op `vector_cosine_ops`
(ADR-002). Created in migration `006_msgchains.py`.

Memorist auto-call (P4):
- Pre-SubTask hook in Pentester role runs `search_in_memory(query=subtask.description, k=3, score_threshold=0.7)`.
- Top-3 rows above threshold are merged into Pentester's context window for the SubTask.
"""
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin

try:
    from pgvector.sqlalchemy import Vector
except ImportError:  # pragma: no cover - pgvector is required at runtime
    # During the P1 install spike, pgvector may not yet be installed.
    # Defer the import error to query time rather than blocking import of
    # the models package entirely. The `006_msgchains.py` migration is what
    # introduces the column at the DB level; the SQLAlchemy column needs
    # `pgvector` only when the model is actually queried.
    Vector = None  # type: ignore


# Lazy column factory: the column type is resolved at module-import time if
# pgvector is available, otherwise raises at attribute access time. This keeps
# `from app.models import MemoryEntry` working in environments where pgvector
# isn't installed yet (CI bootstrap, plan-only validation).
def _embedding_column():
    if Vector is None:
        raise ImportError(
            "pgvector is required to use MemoryEntry. "
            "Install with `pip install pgvector` (added as v4.0 P1 dep)."
        )
    return mapped_column(Vector(384), nullable=False)


class MemoryEntry(Base, UUIDMixin):
    __tablename__ = "memory_entries"

    domain_tag: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_yaml_path: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # pgvector embedding column. Resolved lazily so the model can be imported
    # even before pgvector is installed during the P1 dep-tuple spike.
    if Vector is not None:
        embedding: Mapped[list[float]] = mapped_column(Vector(384), nullable=False)
    else:  # pragma: no cover
        # Placeholder for environments without pgvector (CI bootstrap only).
        # Production runs always have pgvector via the locked dep tuple.
        embedding = _embedding_column  # type: ignore

    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
