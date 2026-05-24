"""MemoryEntry model round-trip tests (v4.0 P1).

Uses the conftest SQLite engine with Vector → JSON remap. Verifies the model
class is structurally correct and can persist a 384-dim vector through the
unit-test SQLite path; the real pgvector hnsw search is exercised in P2a
integration tests.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.memory_entry import MemoryEntry


@pytest.mark.asyncio
async def test_memory_entry_round_trip(db):
    """Insert + read a MemoryEntry with a fixture 384-dim vector."""
    vector = [0.1] * 384  # deterministic fixture vector
    entry = MemoryEntry(
        domain_tag="web",
        source_yaml_path="backend/app/knowledge/web/sqli_intent.yaml",
        name="sqli_intent",
        description="SQL injection probe targeting login forms",
        embedding=vector,
        metadata_json={"severity": "high", "owasp": "A03"},
    )
    db.add(entry)
    await db.flush()

    fetched = (
        await db.execute(select(MemoryEntry).where(MemoryEntry.id == entry.id))
    ).scalar_one()
    assert fetched.domain_tag == "web"
    assert fetched.name == "sqli_intent"
    assert fetched.description.startswith("SQL injection")
    # Vector serialized as JSON in SQLite test engine — length preserved.
    assert len(fetched.embedding) == 384
    assert fetched.metadata_json["owasp"] == "A03"


@pytest.mark.asyncio
async def test_memory_entry_metadata_json_optional(db):
    """metadata_json is nullable; entries without metadata are allowed."""
    entry = MemoryEntry(
        domain_tag="network",
        source_yaml_path="backend/app/knowledge/network/nmap_intent.yaml",
        name="nmap_intent",
        description="TCP SYN scan against host range",
        embedding=[0.0] * 384,
    )
    db.add(entry)
    await db.flush()

    fetched = (
        await db.execute(select(MemoryEntry).where(MemoryEntry.id == entry.id))
    ).scalar_one()
    assert fetched.metadata_json is None


def test_memory_entry_vector_dim_matches_settings():
    """Ensure the embedding column dimension matches `settings.embedding_vector_dim`."""
    from app.core.config import settings

    assert settings.embedding_vector_dim == 384
