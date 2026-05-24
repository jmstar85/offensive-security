"""Plan v3.2.1 §2.3 — ToolEntry + palette_for_domain."""
import pytest

from app.agents.base import RiskLevel
from app.agents.registry import (
    ToolEntry,
    get_adapter,
    get_tool_entry,
    list_agent_types,
    list_tool_entries,
    palette_for_domain,
    register_tool_entry,
    unregister_tool_entry,
)
from app.agents.nmap import NmapAdapter


def test_legacy_get_adapter_still_works():
    """Backward-compat: existing slugs map to instantiated adapters."""
    a = get_adapter("nmap")
    assert a.agent_type == "nmap"


def test_list_agent_types_contains_legacy_and_new():
    slugs = set(list_agent_types())
    assert {"nmap", "nuclei", "metasploit", "pyrit"} <= slugs
    assert {"passive_recon", "subfinder", "dnsx", "httpx", "cloudenum", "wappalyzer"} <= slugs


def test_get_tool_entry_returns_metadata():
    entry = get_tool_entry("subfinder")
    assert entry is not None
    assert entry.tier == "active_recon"
    assert "web" in entry.applicable_domain_tags
    assert entry.is_destructive_capable is False


def test_palette_for_domain_filters_by_tag_intersection():
    web_palette_slugs = {e.slug for e in palette_for_domain(frozenset({"web"}))}
    # nmap, nuclei, httpx, wappalyzer, subfinder, passive_recon, metasploit
    assert {"httpx", "wappalyzer", "subfinder", "passive_recon"} <= web_palette_slugs
    # pyrit (ai-only) must be absent
    assert "pyrit" not in web_palette_slugs


def test_palette_for_ai_domain_only_returns_pyrit():
    ai_palette = {e.slug for e in palette_for_domain(frozenset({"ai"}))}
    assert ai_palette == {"pyrit"}


def test_register_and_unregister_tool_entry_roundtrip():
    fake = ToolEntry(
        slug="fake-test-tool",
        adapter_cls=NmapAdapter,
        docker_image="osa-fake:latest",
        tier="passive_low_touch",
        capabilities=("noop",),
        applicable_domain_tags=frozenset({"web"}),
        default_risk_band=RiskLevel.LOW,
        is_destructive_capable=False,
    )
    register_tool_entry(fake)
    try:
        assert get_tool_entry("fake-test-tool") is fake
        with pytest.raises(ValueError):
            register_tool_entry(fake)  # duplicate
    finally:
        unregister_tool_entry("fake-test-tool")
    assert get_tool_entry("fake-test-tool") is None


def test_every_tool_entry_has_complete_metadata():
    for entry in list_tool_entries():
        assert entry.slug, "slug must be non-empty"
        assert entry.docker_image.endswith(":latest") or ":" in entry.docker_image
        assert entry.tier
        assert entry.capabilities
        assert entry.applicable_domain_tags
        assert isinstance(entry.is_destructive_capable, bool)
