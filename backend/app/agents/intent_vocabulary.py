"""INTENT_VOCABULARY — closed enum of step intents the workflow editor allows.

Plan v3.2.1 §4.3 (resolved post-P0 with user confirmation 2026-05-14):
The set is intentionally broad enough (~20 items) to cover the 8 domain agents
(Web/Network/Cloud×3/Mobile/API/OSINT/AI) without leaving room for free-form
hallucination. Anything outside this set is rejected by the workflow validator.

Each intent maps to:
- ``tier``        — default risk tier (overridable per-step by the planner)
- ``description`` — operator-facing label
- ``applicable_domain_tags`` — which DomainAgents may emit this intent

NOTE: This is the **planner-facing vocabulary**. Actual tools chosen to fulfil
an intent come from the tool registry's tier+domain palette.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.agents.registry import Tier


@dataclass(frozen=True)
class IntentSpec:
    slug: str
    description: str
    default_tier: Tier
    applicable_domain_tags: frozenset[str]


INTENT_VOCABULARY: dict[str, IntentSpec] = {
    # ── Passive — no target contact ─────────────────────────────────────
    "passive_dns_recon": IntentSpec(
        slug="passive_dns_recon",
        description="Resolve and enumerate DNS records via public APIs (no direct probe).",
        default_tier="passive_no_target_contact",
        applicable_domain_tags=frozenset({"osint", "web", "network"}),
    ),
    "certificate_transparency_lookup": IntentSpec(
        slug="certificate_transparency_lookup",
        description="Enumerate subdomains via CT logs (crt.sh).",
        default_tier="passive_no_target_contact",
        applicable_domain_tags=frozenset({"osint", "web"}),
    ),
    "email_security_audit": IntentSpec(
        slug="email_security_audit",
        description="Parse SPF/DMARC/DKIM/BIMI from public DNS.",
        default_tier="passive_no_target_contact",
        applicable_domain_tags=frozenset({"osint", "email"}),
    ),
    "breach_intel_lookup": IntentSpec(
        slug="breach_intel_lookup",
        description="Query public breach feeds (HaveIBeenPwned, HudsonRock).",
        default_tier="passive_no_target_contact",
        applicable_domain_tags=frozenset({"osint"}),
    ),
    # ── Passive — low touch ─────────────────────────────────────────────
    "web_fingerprint": IntentSpec(
        slug="web_fingerprint",
        description="HTTP GET / banner grab / .well-known / robots / sitemap.",
        default_tier="passive_low_touch",
        applicable_domain_tags=frozenset({"web", "osint", "api"}),
    ),
    "tech_stack_inventory": IntentSpec(
        slug="tech_stack_inventory",
        description="Wappalyzer-style passive technology detection.",
        default_tier="passive_low_touch",
        applicable_domain_tags=frozenset({"web", "api"}),
    ),
    "secret_scan_public_repos": IntentSpec(
        slug="secret_scan_public_repos",
        description="Regex-scan cloned public repos / pastes for credentials.",
        default_tier="passive_low_touch",
        applicable_domain_tags=frozenset({"osint", "cloud_aws", "cloud_azure", "cloud_gcp"}),
    ),
    "mobile_static_analysis": IntentSpec(
        slug="mobile_static_analysis",
        description="Static analysis of public APK/IPA artifacts (no device contact).",
        default_tier="passive_low_touch",
        applicable_domain_tags=frozenset({"mobile"}),
    ),
    # ── Active — recon ──────────────────────────────────────────────────
    "port_scan": IntentSpec(
        slug="port_scan",
        description="TCP/UDP port discovery with service detection.",
        default_tier="active_recon",
        applicable_domain_tags=frozenset({"network", "web"}),
    ),
    "subdomain_bruteforce": IntentSpec(
        slug="subdomain_bruteforce",
        description="DNS brute-force using subfinder/dnsx wordlists.",
        default_tier="active_recon",
        applicable_domain_tags=frozenset({"web", "osint", "network"}),
    ),
    "vulnerability_template_scan": IntentSpec(
        slug="vulnerability_template_scan",
        description="Nuclei template-based vulnerability probing.",
        default_tier="active_recon",
        applicable_domain_tags=frozenset({"web", "api", "network"}),
    ),
    "cloud_bucket_enumeration": IntentSpec(
        slug="cloud_bucket_enumeration",
        description="S3/GCS/Azure container discovery (cloudenum).",
        default_tier="active_recon",
        applicable_domain_tags=frozenset({"cloud_aws", "cloud_azure", "cloud_gcp"}),
    ),
    "api_endpoint_discovery": IntentSpec(
        slug="api_endpoint_discovery",
        description="Swagger/OpenAPI/GraphQL introspection.",
        default_tier="active_recon",
        applicable_domain_tags=frozenset({"api", "web"}),
    ),
    "kubernetes_surface_check": IntentSpec(
        slug="kubernetes_surface_check",
        description="Detect exposed kubelet/etcd/dashboard ports.",
        default_tier="active_recon",
        applicable_domain_tags=frozenset({"cloud_aws", "cloud_azure", "cloud_gcp", "network"}),
    ),
    "sso_tenant_fingerprint": IntentSpec(
        slug="sso_tenant_fingerprint",
        description="Microsoft Entra/Okta/ADFS tenant detection.",
        default_tier="active_recon",
        applicable_domain_tags=frozenset({"cloud_azure", "web"}),
    ),
    # ── Active — exploit ────────────────────────────────────────────────
    "credential_validation": IntentSpec(
        slug="credential_validation",
        description="Read-only validator (e.g. AWS GetCallerIdentity, Slack auth.test).",
        default_tier="active_exploit",
        applicable_domain_tags=frozenset({"cloud_aws", "cloud_azure", "cloud_gcp", "osint"}),
    ),
    "vulnerability_exploitation": IntentSpec(
        slug="vulnerability_exploitation",
        description="Metasploit auxiliary/post module against confirmed targets.",
        default_tier="active_exploit",
        applicable_domain_tags=frozenset({"network", "web"}),
    ),
    "authentication_brute_force": IntentSpec(
        slug="authentication_brute_force",
        description="Login attempts with throttled candidate sets (allowlisted).",
        default_tier="active_exploit",
        applicable_domain_tags=frozenset({"web", "api", "network"}),
    ),
    "ai_red_team_probe": IntentSpec(
        slug="ai_red_team_probe",
        description="PyRIT-driven jailbreak / prompt-injection probing.",
        default_tier="active_exploit",
        applicable_domain_tags=frozenset({"ai"}),
    ),
    "mobile_dynamic_analysis": IntentSpec(
        slug="mobile_dynamic_analysis",
        description="Runtime analysis on emulator (Frida/Objection).",
        default_tier="active_exploit",
        applicable_domain_tags=frozenset({"mobile"}),
    ),
}


def is_valid_intent(slug: str) -> bool:
    return slug in INTENT_VOCABULARY


def intent_default_tier(slug: str) -> Tier:
    spec = INTENT_VOCABULARY.get(slug)
    if spec is None:
        raise ValueError(f"Unknown intent: {slug}")
    return spec.default_tier


def intents_for_domain(domain_tags: frozenset[str]) -> list[IntentSpec]:
    return [
        spec for spec in INTENT_VOCABULARY.values()
        if spec.applicable_domain_tags & domain_tags
    ]


IntentSlug = Literal[
    "passive_dns_recon",
    "certificate_transparency_lookup",
    "email_security_audit",
    "breach_intel_lookup",
    "web_fingerprint",
    "tech_stack_inventory",
    "secret_scan_public_repos",
    "mobile_static_analysis",
    "port_scan",
    "subdomain_bruteforce",
    "vulnerability_template_scan",
    "cloud_bucket_enumeration",
    "api_endpoint_discovery",
    "kubernetes_surface_check",
    "sso_tenant_fingerprint",
    "credential_validation",
    "vulnerability_exploitation",
    "authentication_brute_force",
    "ai_red_team_probe",
    "mobile_dynamic_analysis",
]
