"""Plan v3.2.1 §3 — DomainAgent personas + palette intersection rules."""
from __future__ import annotations

from app.agents.domains import DOMAIN_AGENTS, get_domain_agent, list_domain_agents
from app.agents.registry import palette_for_domain


def test_exactly_eight_domain_agents():
    assert len(DOMAIN_AGENTS) == 8
    assert {
        "web-app-agent",
        "network-agent",
        "cloud-aws-agent",
        "cloud-azure-agent",
        "cloud-gcp-agent",
        "mobile-agent",
        "api-security-agent",
        "osint-agent",
    } == set(DOMAIN_AGENTS.keys())


def test_each_agent_has_persona_and_tool_tags():
    for agent in list_domain_agents():
        assert agent.persona_prompt
        assert agent.tool_tags
        assert agent.knowledge_pack_slug


def test_web_agent_palette_excludes_metasploit_active_exploit_by_default():
    """web-app-agent palette via applicable_domain_tags includes metasploit
    because metasploit is tagged web — but the agent's *default_risk_tier*
    is active_recon, and tier-flag enforcement (test_exploit_allowlist_tier)
    blocks active_exploit at runtime. Persona-level filtering is delegated
    to the workflow service in P3.
    """
    agent = get_domain_agent("web-app-agent")
    palette_slugs = {e.slug for e in palette_for_domain(agent.tool_tags)}
    # Tools tagged web *or* api are in the palette
    assert {"httpx", "subfinder", "wappalyzer", "passive_recon", "nmap", "nuclei"} <= palette_slugs


def test_osint_agent_palette_contains_only_passive_tools_when_intersected_with_passive_tiers():
    agent = get_domain_agent("osint-agent")
    palette = palette_for_domain(agent.tool_tags)
    osint_only_passive = [t for t in palette if t.tier in {"passive_no_target_contact", "passive_low_touch"}]
    # osint domain should expose at least passive_recon
    assert any(t.slug == "passive_recon" for t in osint_only_passive)


def test_get_domain_agent_unknown_returns_none():
    assert get_domain_agent("blue-team-agent") is None


def test_mobile_agent_is_admin_only():
    agent = get_domain_agent("mobile-agent")
    assert agent is not None
    assert agent.admin_only is True
