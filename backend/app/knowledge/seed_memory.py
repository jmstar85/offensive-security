"""Seed `memory_entries` from on-disk knowledge YAML corpus (v4.0 P1).

CLI entrypoint:
    python -m app.knowledge.seed_memory [--force]

Idempotency contract:
- Default run: skip if any rows exist in `memory_entries`.
- `--force`: TRUNCATE memory_entries, re-chunk, re-embed, re-insert.

Chunking strategy:
- Each YAML file under `backend/app/knowledge/{domain}/` is loaded.
- For each top-level entry with a `description` field, one MemoryEntry row is
  produced. The chunk text is `description` only; `name` and `domain_tag` are
  preserved as separate columns for filtered retrieval (Pentester domain palette).
- Files without a `description` are skipped with a warning.

Embedding model: `sentence-transformers/all-MiniLM-L6-v2` via
`app.orchestrator.roles.memorist_embedding.get_or_load_model()`.

Not run inside the app boot path. Operators run this once after `alembic
upgrade head` introduces the table.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select, text

from app.core.config import settings
from app.core.database import async_session
from app.models.memory_entry import MemoryEntry
from app.orchestrator.roles import memorist_embedding

logger = logging.getLogger(__name__)


# Hard cap on chunk text length — protects Pentester context window from a
# tampered knowledge YAML pushing oversized prompts into the role's LLM call.
# Per Security Reviewer finding Medium #5 (2026-05-17 v4.0 Phase 4 review).
DESCRIPTION_MAX_CHARS = 2000


def _sanitize_description(text: str) -> str:
    """Strip ANSI escape sequences + control chars (except `\\n` and `\\t`) and
    truncate to `DESCRIPTION_MAX_CHARS`. Defensive measure for the case where
    a knowledge YAML is supply-chain tampered to inject prompt-marker
    control sequences into the Pentester role's context.
    """
    # Drop control chars in the C0 range except newline/tab. ANSI ESC (0x1B)
    # is included in the C0 range so this catches `\\x1b[…m` color codes.
    cleaned = "".join(
        ch for ch in text if ord(ch) >= 0x20 or ch in "\n\t"
    )
    cleaned = cleaned.strip()
    if len(cleaned) > DESCRIPTION_MAX_CHARS:
        cleaned = cleaned[:DESCRIPTION_MAX_CHARS]
    return cleaned


def discover_chunks(knowledge_root: Path) -> list[dict[str, Any]]:
    """Walk knowledge_root and return a list of chunk dicts ready for embedding.

    Each chunk dict: `{domain_tag, source_yaml_path, name, description, metadata}`.
    """
    chunks: list[dict[str, Any]] = []
    if not knowledge_root.exists():
        logger.warning("Knowledge root does not exist: %s", knowledge_root)
        return chunks

    for yaml_path in sorted(knowledge_root.rglob("*.yaml")):
        # Domain tag = parent directory name (web, network, cloud_aws, etc.)
        # Skip the root MANIFEST.yaml and any non-domain files.
        domain_tag = yaml_path.parent.name
        if domain_tag == knowledge_root.name:
            # File lives at the root of knowledge/ (e.g. MANIFEST.yaml); skip.
            continue

        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            logger.warning("Skipping malformed YAML %s: %s", yaml_path, e)
            continue
        if not isinstance(data, dict):
            continue

        # Two top-level shapes are accepted: single-entity (name+description at
        # top level) or list-of-entities (entries[]).
        entities = data.get("entries") if isinstance(data.get("entries"), list) else [data]
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            description = entity.get("description")
            if not description or not isinstance(description, str):
                continue
            chunks.append(
                {
                    "domain_tag": domain_tag,
                    "source_yaml_path": str(yaml_path.relative_to(knowledge_root.parent)),
                    "name": entity.get("name") or yaml_path.stem,
                    "description": _sanitize_description(description),
                    "metadata": {
                        k: v
                        for k, v in entity.items()
                        if k not in {"name", "description"}
                    },
                }
            )
    return chunks


async def seed(force: bool = False) -> int:
    """Embed and insert chunks. Returns the row count written."""
    await memorist_embedding.get_or_load_model()
    knowledge_root = Path(settings.knowledge_dir)
    chunks = discover_chunks(knowledge_root)
    if not chunks:
        logger.warning("No chunks discovered under %s; nothing to seed", knowledge_root)
        return 0

    async with async_session() as session:
        if force:
            await session.execute(text("TRUNCATE memory_entries"))
        else:
            existing = await session.execute(select(MemoryEntry).limit(1))
            if existing.scalar_one_or_none() is not None:
                logger.info(
                    "memory_entries already populated; rerun with --force to reseed"
                )
                return 0

        for chunk in chunks:
            vector = memorist_embedding.embed_one(chunk["description"])
            entry = MemoryEntry(
                domain_tag=chunk["domain_tag"],
                source_yaml_path=chunk["source_yaml_path"],
                name=chunk["name"],
                description=chunk["description"],
                embedding=vector,
                metadata_json=chunk["metadata"] or None,
            )
            session.add(entry)

        await session.commit()
        logger.info("Seeded %d memory_entries rows", len(chunks))
        return len(chunks)


def _main() -> None:
    parser = argparse.ArgumentParser(description="Seed memory_entries from knowledge YAML")
    parser.add_argument(
        "--force",
        action="store_true",
        help="TRUNCATE memory_entries before reseeding (destructive)",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    count = asyncio.run(seed(force=args.force))
    print(f"Seeded {count} memory_entries rows")


if __name__ == "__main__":
    _main()
