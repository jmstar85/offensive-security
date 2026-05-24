"""On-disk knowledge-pack loader with SHA256 verification at boot.

Plan v3.2.1 §2.2:
- 9 SKILL.md files + dork/regex yaml live under ``backend/app/knowledge/``.
- ``MANIFEST.yaml`` lists each file's SHA256.
- Boot loader hard-fails if any file is missing or any SHA mismatches.
- YAML/MD with executable hooks is refused (yaml.safe_load enforced;
  MD scanned for ``<script``, ``<?`` and shell hashbang prefixes).
- No DB writes — everything stays in memory.
"""
from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.core.config import settings

logger = logging.getLogger(__name__)


class KnowledgePackError(RuntimeError):
    """Boot-time verification failure."""


_FORBIDDEN_MD_PREFIXES = ("#!/",)
_FORBIDDEN_MD_SUBSTRINGS = ("<script", "<?php", "<?=", "<?xml-stylesheet")


@dataclass(frozen=True)
class KnowledgePack:
    slug: str
    path: Path
    sha256: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DorkBundle:
    slug: str
    path: Path
    sha256: str
    entries: dict[str, Any]


@dataclass(frozen=True)
class KnowledgeIndex:
    packs: dict[str, KnowledgePack]
    dorks: dict[str, DorkBundle]
    manifest_path: Path


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _reject_executable_md(text: str, path: Path) -> None:
    head = text.lstrip()[:256]
    for prefix in _FORBIDDEN_MD_PREFIXES:
        if head.startswith(prefix):
            raise KnowledgePackError(
                f"Knowledge file rejected (executable hashbang): {path}"
            )
    lower = text.lower()
    for marker in _FORBIDDEN_MD_SUBSTRINGS:
        if marker in lower:
            raise KnowledgePackError(
                f"Knowledge file rejected (forbidden substring {marker!r}): {path}"
            )


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.is_file():
        raise KnowledgePackError(f"Knowledge MANIFEST missing: {manifest_path}")
    with manifest_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise KnowledgePackError(
            f"Knowledge MANIFEST must be a YAML mapping: {manifest_path}"
        )
    return data


def load_knowledge(
    knowledge_dir: str | None = None,
    manifest_path: str | None = None,
    audit_callback=None,
) -> KnowledgeIndex:
    """Load and verify all knowledge files described in ``MANIFEST.yaml``.

    On any mismatch / missing file / forbidden content, raises
    ``KnowledgePackError``. When supplied, ``audit_callback(action, details)``
    is invoked with ``action="knowledge_loaded"`` or
    ``"knowledge_pack_sha_mismatch"``.
    """
    root = Path(knowledge_dir or settings.knowledge_dir)
    manifest = Path(manifest_path or settings.knowledge_required_sha256_path)
    if not manifest.is_absolute():
        manifest = root / manifest

    data = _load_manifest(manifest)
    packs_meta = data.get("packs") or {}
    dorks_meta = data.get("dorks") or {}

    packs: dict[str, KnowledgePack] = {}
    for slug, entry in packs_meta.items():
        rel = entry.get("path")
        expected = entry.get("sha256")
        if not rel or not expected:
            raise KnowledgePackError(
                f"Manifest entry for pack '{slug}' missing path or sha256"
            )
        path = (root / rel).resolve()
        if not path.is_file():
            if audit_callback:
                audit_callback(
                    "knowledge_pack_sha_mismatch",
                    {"slug": slug, "reason": "missing_file", "path": str(path)},
                )
            raise KnowledgePackError(f"Knowledge file missing for '{slug}': {path}")
        actual = _sha256_of(path)
        if actual != expected:
            if audit_callback:
                audit_callback(
                    "knowledge_pack_sha_mismatch",
                    {
                        "slug": slug,
                        "path": str(path),
                        "expected": expected,
                        "actual": actual,
                    },
                )
            raise KnowledgePackError(
                f"SHA mismatch for '{slug}' ({path}): expected={expected} actual={actual}"
            )
        text = path.read_text(encoding="utf-8")
        _reject_executable_md(text, path)
        packs[slug] = KnowledgePack(
            slug=slug,
            path=path,
            sha256=actual,
            content=text,
            metadata=entry.get("metadata") or {},
        )

    dorks: dict[str, DorkBundle] = {}
    for slug, entry in dorks_meta.items():
        rel = entry.get("path")
        expected = entry.get("sha256")
        if not rel or not expected:
            raise KnowledgePackError(
                f"Manifest entry for dorks '{slug}' missing path or sha256"
            )
        path = (root / rel).resolve()
        if not path.is_file():
            raise KnowledgePackError(f"Dorks file missing for '{slug}': {path}")
        actual = _sha256_of(path)
        if actual != expected:
            raise KnowledgePackError(
                f"SHA mismatch for dorks '{slug}' ({path}): expected={expected} actual={actual}"
            )
        with path.open("r", encoding="utf-8") as f:
            parsed = yaml.safe_load(f)
        if not isinstance(parsed, dict):
            raise KnowledgePackError(
                f"Dorks YAML must parse to mapping: {path}"
            )
        dorks[slug] = DorkBundle(slug=slug, path=path, sha256=actual, entries=parsed)

    if audit_callback:
        audit_callback(
            "knowledge_loaded",
            {
                "pack_count": len(packs),
                "dorks_count": len(dorks),
                "manifest": str(manifest),
            },
        )

    try:
        from app.observability.metrics import metrics
        metrics.knowledge_load_total.inc(result="ok")
    except ImportError:
        pass

    logger.info(
        "knowledge_loaded packs=%d dorks=%d manifest=%s",
        len(packs),
        len(dorks),
        manifest,
    )
    return KnowledgeIndex(packs=packs, dorks=dorks, manifest_path=manifest)


def compute_manifest_for_dir(root: str | os.PathLike) -> dict[str, dict[str, dict[str, str]]]:
    """Walk ``root`` and emit a manifest dict with SHA256s (build-time helper).

    Used by ``tools/regenerate_knowledge_manifest.py`` and by tests that need
    a freshly-built manifest matching local file contents.
    """
    root_path = Path(root)
    packs: dict[str, dict[str, str]] = {}
    dorks: dict[str, dict[str, str]] = {}
    for skill in sorted(root_path.glob("*/SKILL.md")):
        slug = skill.parent.name
        rel = skill.relative_to(root_path).as_posix()
        packs[slug] = {"path": rel, "sha256": _sha256_of(skill)}
    dorks_dir = root_path / "dorks"
    if dorks_dir.is_dir():
        for f in sorted(dorks_dir.glob("*.yaml")):
            slug = f.stem
            rel = f.relative_to(root_path).as_posix()
            dorks[slug] = {"path": rel, "sha256": _sha256_of(f)}
    return {"packs": packs, "dorks": dorks}
