"""Fix #E — every ToolEntry has a non-empty description, and /agents/catalog
surfaces it.

Two layers covered:
  - registry-level invariant: every registered slug ships a description so
    the AgentCatalog cards never render an empty CardDescription.
  - API-level shape: _tool_meta emits a `description` field that prefers
    the explicit value and falls back to a capabilities-derived summary
    for entries that forget to set it.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.agents.base import AgentAdapter, RiskLevel
from app.agents.nmap import NmapAdapter
from app.agents.registry import ToolEntry, list_tool_entries
from app.api.v1.agents import _tool_meta


def test_every_registered_tool_has_a_description():
    blanks = [e.slug for e in list_tool_entries() if not e.description.strip()]
    assert blanks == [], f"entries with empty description: {blanks}"


def test_tool_meta_includes_description_field():
    for entry in list_tool_entries():
        meta = _tool_meta(entry)
        assert "description" in meta
        assert isinstance(meta["description"], str)
        assert meta["description"].strip(), f"blank description on {entry.slug}"


def test_kali_descriptions_mention_kali():
    metas = {e.slug: _tool_meta(e) for e in list_tool_entries()
             if e.slug.startswith("kali_")}
    assert set(metas) == {
        "kali_gobuster", "kali_sqlmap", "kali_nikto",
        "kali_xsstrike", "kali_dalfox", "kali_ffuf", "kali_commix",
    }
    for slug, meta in metas.items():
        assert "Kali" in meta["description"], f"{slug} description: {meta['description']}"


def test_description_fallback_when_field_omitted():
    """ToolEntry without an explicit description still produces a non-empty
    summary in the API response (defence-in-depth for late additions)."""
    entry = ToolEntry(
        slug="fake-tool",
        adapter_cls=NmapAdapter,
        docker_image="osa-fake:latest",
        tier="passive_low_touch",
        capabilities=("alpha_capability", "beta_capability"),
        applicable_domain_tags=frozenset({"web"}),
        default_risk_band=RiskLevel.LOW,
        is_destructive_capable=False,
        # description intentionally omitted
    )
    meta = _tool_meta(entry)
    assert meta["description"]
    assert "alpha capability" in meta["description"].lower()


def test_known_legacy_descriptions_are_concrete():
    by_slug = {e.slug: e.description for e in list_tool_entries()}
    assert "Port scanner" in by_slug["nmap"]
    assert "vulnerability scanner" in by_slug["nuclei"].lower()
    assert "auxiliary" in by_slug["metasploit"].lower()
    assert "ai red-team" in by_slug["pyrit"].lower()
