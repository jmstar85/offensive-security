"""Plan v3.2.1 §2.2 — knowledge loader SHA verification + safety rejections."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
import yaml

from app.agents.knowledge_loader import (
    KnowledgePackError,
    compute_manifest_for_dir,
    load_knowledge,
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


@pytest.fixture
def kb(tmp_path: Path) -> Path:
    """Build a tiny knowledge tree with a valid manifest."""
    web = tmp_path / "web" / "SKILL.md"
    web.parent.mkdir(parents=True)
    web.write_text("# Web pack\nSafe markdown only.\n", encoding="utf-8")

    network = tmp_path / "network" / "SKILL.md"
    network.parent.mkdir()
    network.write_text("# Network pack\nMore safe text.\n", encoding="utf-8")

    dorks = tmp_path / "dorks" / "github.yaml"
    dorks.parent.mkdir()
    dorks.write_text("templates:\n  q1:\n    query: 'site:x'\n", encoding="utf-8")

    manifest = {
        "packs": {
            "web": {"path": "web/SKILL.md", "sha256": _sha256(web)},
            "network": {"path": "network/SKILL.md", "sha256": _sha256(network)},
        },
        "dorks": {
            "github": {"path": "dorks/github.yaml", "sha256": _sha256(dorks)},
        },
    }
    (tmp_path / "MANIFEST.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    return tmp_path


def test_loader_happy_path(kb):
    idx = load_knowledge(str(kb), str(kb / "MANIFEST.yaml"))
    assert set(idx.packs.keys()) == {"web", "network"}
    assert "github" in idx.dorks
    assert idx.packs["web"].content.startswith("# Web pack")


def test_loader_emits_knowledge_loaded_audit(kb):
    events = []
    load_knowledge(
        str(kb), str(kb / "MANIFEST.yaml"),
        audit_callback=lambda a, d: events.append((a, d)),
    )
    actions = [a for a, _ in events]
    assert "knowledge_loaded" in actions


def test_loader_hard_fails_on_sha_mismatch(kb):
    # mutate one file but keep manifest SHA → must fail
    target = kb / "web" / "SKILL.md"
    target.write_text("# tampered\n", encoding="utf-8")

    events = []
    with pytest.raises(KnowledgePackError) as ei:
        load_knowledge(
            str(kb), str(kb / "MANIFEST.yaml"),
            audit_callback=lambda a, d: events.append((a, d)),
        )
    assert "SHA mismatch" in str(ei.value)
    assert any(a == "knowledge_pack_sha_mismatch" for a, _ in events)


def test_loader_hard_fails_on_missing_file(kb):
    os.remove(kb / "network" / "SKILL.md")
    with pytest.raises(KnowledgePackError) as ei:
        load_knowledge(str(kb), str(kb / "MANIFEST.yaml"))
    assert "missing" in str(ei.value).lower()


def test_loader_rejects_executable_hashbang(kb):
    target = kb / "web" / "SKILL.md"
    target.write_text("#!/bin/bash\necho pwned\n", encoding="utf-8")
    # Recompute manifest so SHA matches but content is unsafe.
    new_manifest = {
        "packs": {
            "web": {"path": "web/SKILL.md", "sha256": _sha256(target)},
            "network": {
                "path": "network/SKILL.md",
                "sha256": _sha256(kb / "network" / "SKILL.md"),
            },
        },
        "dorks": {
            "github": {
                "path": "dorks/github.yaml",
                "sha256": _sha256(kb / "dorks" / "github.yaml"),
            },
        },
    }
    (kb / "MANIFEST.yaml").write_text(yaml.safe_dump(new_manifest), encoding="utf-8")
    with pytest.raises(KnowledgePackError) as ei:
        load_knowledge(str(kb), str(kb / "MANIFEST.yaml"))
    assert "executable" in str(ei.value).lower()


def test_loader_rejects_html_script_marker(kb):
    target = kb / "web" / "SKILL.md"
    target.write_text("<script>alert(1)</script>\n", encoding="utf-8")
    new_manifest = {
        "packs": {
            "web": {"path": "web/SKILL.md", "sha256": _sha256(target)},
            "network": {
                "path": "network/SKILL.md",
                "sha256": _sha256(kb / "network" / "SKILL.md"),
            },
        },
        "dorks": {
            "github": {
                "path": "dorks/github.yaml",
                "sha256": _sha256(kb / "dorks" / "github.yaml"),
            },
        },
    }
    (kb / "MANIFEST.yaml").write_text(yaml.safe_dump(new_manifest), encoding="utf-8")
    with pytest.raises(KnowledgePackError) as ei:
        load_knowledge(str(kb), str(kb / "MANIFEST.yaml"))
    assert "forbidden" in str(ei.value).lower()


def test_compute_manifest_for_dir_round_trips(kb):
    m = compute_manifest_for_dir(kb)
    assert set(m["packs"].keys()) == {"web", "network"}
    assert m["packs"]["web"]["sha256"] == _sha256(kb / "web" / "SKILL.md")


def test_loader_verifies_real_project_manifest():
    """Project-bundled knowledge files must verify against their own MANIFEST."""
    root = Path(__file__).resolve().parents[2] / "app" / "knowledge"
    manifest = root / "MANIFEST.yaml"
    assert manifest.is_file(), manifest
    idx = load_knowledge(str(root), str(manifest))
    # 9 SKILL.md packs (methodology, web, network, cloud_aws, cloud_azure,
    # cloud_gcp, mobile, api, osint)
    assert len(idx.packs) == 9
    # 3 dorks bundles
    assert {"github", "google", "shodan"} == set(idx.dorks.keys())
