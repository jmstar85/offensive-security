"""Domain-agent registry (plan v3.2.1 §3 — in-code, no DB tables).

Each DomainAgent is a planner-side persona that owns:
- a curated tool palette (derived from registry via applicable_domain_tags)
- a knowledge-pack reference (the matching SKILL.md)
- a default risk tier

The orchestrator chooses one DomainAgent per session at draft-creation time.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.agents.registry import Tier


@dataclass(frozen=True)
class DomainAgent:
    slug: str
    display_name: str
    tool_tags: frozenset[str]
    knowledge_pack_slug: str
    default_risk_tier: Tier
    admin_only: bool = False
    persona_prompt: str = ""
    intent_slugs: tuple[str, ...] = field(default_factory=tuple)


DOMAIN_AGENTS: dict[str, DomainAgent] = {
    "web-app-agent": DomainAgent(
        slug="web-app-agent",
        display_name="Web Application",
        tool_tags=frozenset({"web", "api"}),
        knowledge_pack_slug="web",
        default_risk_tier="active_recon",
        persona_prompt=(
            "You are a senior web application penetration tester. Draft a plan "
            "that prioritizes authentication, authorization, injection, SSRF, "
            "and business-logic vulnerabilities. Never include destructive "
            "payloads. Stay inside the operator's whitelist."
        ),
        intent_slugs=(
            "web_fingerprint",
            "tech_stack_inventory",
            "subdomain_bruteforce",
            "vulnerability_template_scan",
            "api_endpoint_discovery",
            "authentication_brute_force",
        ),
    ),
    "network-agent": DomainAgent(
        slug="network-agent",
        display_name="Network Penetration",
        tool_tags=frozenset({"network", "web"}),
        knowledge_pack_slug="network",
        default_risk_tier="active_recon",
        persona_prompt=(
            "You are a senior internal and external network pentest engineer. "
            "Plan service discovery, banner enumeration, and approved auxiliary "
            "modules. Never run DoS, ARP spoofing, or wireless attacks."
        ),
        intent_slugs=(
            "port_scan",
            "vulnerability_template_scan",
            "vulnerability_exploitation",
        ),
    ),
    "cloud-aws-agent": DomainAgent(
        slug="cloud-aws-agent",
        display_name="Cloud — AWS",
        tool_tags=frozenset({"cloud_aws", "osint"}),
        knowledge_pack_slug="cloud_aws",
        default_risk_tier="passive_low_touch",
        admin_only=False,
        persona_prompt=(
            "You are a senior AWS security tester. Plan external account "
            "fingerprinting and read-only credential validation. Never call any "
            "AWS API that mutates state."
        ),
        intent_slugs=(
            "passive_dns_recon",
            "certificate_transparency_lookup",
            "cloud_bucket_enumeration",
            "secret_scan_public_repos",
            "credential_validation",
        ),
    ),
    "cloud-azure-agent": DomainAgent(
        slug="cloud-azure-agent",
        display_name="Cloud — Azure",
        tool_tags=frozenset({"cloud_azure", "osint"}),
        knowledge_pack_slug="cloud_azure",
        default_risk_tier="passive_low_touch",
        persona_prompt=(
            "You are a senior Azure / Entra ID security tester. Plan tenant "
            "fingerprinting, M365 service enumeration, and Azure Storage "
            "discovery. Never trigger MFA prompts or password resets."
        ),
        intent_slugs=(
            "sso_tenant_fingerprint",
            "passive_dns_recon",
            "cloud_bucket_enumeration",
            "credential_validation",
        ),
    ),
    "cloud-gcp-agent": DomainAgent(
        slug="cloud-gcp-agent",
        display_name="Cloud — GCP",
        tool_tags=frozenset({"cloud_gcp", "osint"}),
        knowledge_pack_slug="cloud_gcp",
        default_risk_tier="passive_low_touch",
        persona_prompt=(
            "You are a senior GCP security tester. Plan external surface "
            "enumeration, public bucket discovery, and read-only IAM probing."
        ),
        intent_slugs=(
            "cloud_bucket_enumeration",
            "passive_dns_recon",
            "credential_validation",
        ),
    ),
    "mobile-agent": DomainAgent(
        slug="mobile-agent",
        display_name="Mobile Application",
        tool_tags=frozenset({"mobile"}),
        knowledge_pack_slug="mobile",
        default_risk_tier="passive_low_touch",
        admin_only=True,  # dynamic-analysis steps require admin gating
        persona_prompt=(
            "You are a senior mobile application security tester. Plan static "
            "analysis on operator-supplied APK/IPA artifacts; never test "
            "production app-store builds. Dynamic analysis is emulator-only."
        ),
        intent_slugs=(
            "mobile_static_analysis",
            "mobile_dynamic_analysis",
            "secret_scan_public_repos",
        ),
    ),
    "api-security-agent": DomainAgent(
        slug="api-security-agent",
        display_name="API Security",
        tool_tags=frozenset({"api", "web"}),
        knowledge_pack_slug="api",
        default_risk_tier="active_recon",
        persona_prompt=(
            "You are a senior API security tester. Plan OpenAPI/GraphQL/gRPC "
            "discovery and OWASP API Top-10 probing. Never run credential "
            "stuffing against production tokens."
        ),
        intent_slugs=(
            "api_endpoint_discovery",
            "vulnerability_template_scan",
            "authentication_brute_force",
        ),
    ),
    "osint-agent": DomainAgent(
        slug="osint-agent",
        display_name="OSINT / Recon",
        tool_tags=frozenset({"osint", "email"}),
        knowledge_pack_slug="osint",
        default_risk_tier="passive_no_target_contact",
        persona_prompt=(
            "You are a senior OSINT analyst. Plan asset-graph mapping, "
            "certificate-transparency enumeration, breach-intel correlation, "
            "and identity-fabric mapping. No traffic to the target."
        ),
        intent_slugs=(
            "passive_dns_recon",
            "certificate_transparency_lookup",
            "email_security_audit",
            "breach_intel_lookup",
            "secret_scan_public_repos",
        ),
    ),
}


def list_domain_agents() -> list[DomainAgent]:
    return list(DOMAIN_AGENTS.values())


def get_domain_agent(slug: str) -> DomainAgent | None:
    return DOMAIN_AGENTS.get(slug)
