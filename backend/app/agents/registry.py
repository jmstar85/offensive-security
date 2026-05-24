"""Agent registry — maps tool slugs to adapter classes plus tier/domain metadata.

Plan v3.2.1 §2.3: replaces the bare slug→class map with a ToolEntry dataclass
carrying tier, capabilities, applicable_domain_tags, and risk classification.
Domain-agent palettes are derived via ``palette_for_domain`` (no DB tables).

Existing ``get_adapter`` / ``list_agent_types`` API kept for backward compatibility
with the legacy orchestrator + tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.agents.backends.docker import get_docker_backend
from app.agents.backends.kali import get_kali_backend
from app.core.config import settings
from app.agents.base import AgentAdapter, RiskLevel
from app.agents.cloudenum import CloudEnumAdapter
from app.agents.dnsx import DnsxAdapter
from app.agents.httpx_tool import HttpxAdapter
from app.agents.kali_exec import (
    KaliGobusterAdapter,
    KaliNiktoAdapter,
    KaliSqlmapAdapter,
)
from app.agents.metasploit import MetasploitAdapter
from app.agents.nmap import NmapAdapter
from app.agents.nuclei import NucleiAdapter
from app.agents.passive_recon import PassiveReconAdapter
from app.agents.pyrit import PyRITAdapter
from app.agents.subfinder import SubfinderAdapter
from app.agents.wappalyzer import WappalyzerAdapter

Tier = Literal[
    "passive_no_target_contact",
    "passive_low_touch",
    "active_recon",
    "active_exploit",
]


class KaliBackendDisabledError(RuntimeError):
    """Raised when get_adapter() is asked for a kali_* slug while the feature
    flag ``OSA_KALI_BACKEND_ENABLED`` is False (default).

    PR-9 enforces this at both ``get_adapter`` (call-time) and
    ``palette_for_domain`` (plan-time) so the planner never even surfaces
    a kali_* option when the flag is off.
    """


@dataclass(frozen=True)
class ToolEntry:
    slug: str
    adapter_cls: type[AgentAdapter]
    docker_image: str
    tier: Tier
    capabilities: tuple[str, ...]
    applicable_domain_tags: frozenset[str]
    default_risk_band: RiskLevel
    is_destructive_capable: bool


# Domain tag vocabulary (kept aligned with backend/app/agents/domains/__init__.py).
DOMAIN_TAGS = frozenset({
    "web", "network", "cloud_aws", "cloud_azure", "cloud_gcp",
    "mobile", "api", "osint", "email", "ai",
})


_REGISTRY: dict[str, ToolEntry] = {
    # ── Legacy active tools (existing adapters) ──────────────────────────
    "nmap": ToolEntry(
        slug="nmap",
        adapter_cls=NmapAdapter,
        docker_image="osa-agent-nmap:latest",
        tier="active_recon",
        capabilities=("port_scan", "service_detection", "os_detection"),
        applicable_domain_tags=frozenset({"network", "web"}),
        default_risk_band=RiskLevel.MEDIUM,
        is_destructive_capable=False,
    ),
    "nuclei": ToolEntry(
        slug="nuclei",
        adapter_cls=NucleiAdapter,
        docker_image="osa-agent-nuclei:latest",
        tier="active_recon",
        capabilities=("vuln_template_scan",),
        applicable_domain_tags=frozenset({"web", "api", "network"}),
        default_risk_band=RiskLevel.MEDIUM,
        is_destructive_capable=False,
    ),
    "metasploit": ToolEntry(
        slug="metasploit",
        adapter_cls=MetasploitAdapter,
        docker_image="osa-agent-metasploit:latest",
        tier="active_exploit",
        capabilities=("auxiliary_scanner", "post_module", "handler"),
        applicable_domain_tags=frozenset({"network", "web"}),
        default_risk_band=RiskLevel.HIGH,
        is_destructive_capable=True,
    ),
    "pyrit": ToolEntry(
        slug="pyrit",
        adapter_cls=PyRITAdapter,
        docker_image="osa-agent-pyrit:latest",
        tier="active_exploit",
        capabilities=("ai_red_team",),
        applicable_domain_tags=frozenset({"ai"}),
        default_risk_band=RiskLevel.HIGH,
        is_destructive_capable=True,
    ),
    # ── Passive recon shared image (plan v3.2.1 §2.2) ────────────────────
    "passive_recon": ToolEntry(
        slug="passive_recon",
        adapter_cls=PassiveReconAdapter,
        docker_image="osa-passive-recon:latest",
        tier="passive_no_target_contact",
        capabilities=(
            "secret_scan",
            "dns_resolver",
            "cert_transparency",
            "mx_spf_dmarc",
            "robots_sitemap",
            "well_known",
            "securitytxt",
            "cert_chain",
        ),
        applicable_domain_tags=frozenset({
            "osint", "web", "network", "email",
            "cloud_aws", "cloud_azure", "cloud_gcp",
        }),
        default_risk_band=RiskLevel.LOW,
        is_destructive_capable=False,
    ),
    # ── New active-recon Docker tools ────────────────────────────────────
    "subfinder": ToolEntry(
        slug="subfinder",
        adapter_cls=SubfinderAdapter,
        docker_image="osa-agent-subfinder:latest",
        tier="active_recon",
        capabilities=("subdomain_enumeration", "passive_dns"),
        applicable_domain_tags=frozenset({"web", "osint", "network"}),
        default_risk_band=RiskLevel.MEDIUM,
        is_destructive_capable=False,
    ),
    "dnsx": ToolEntry(
        slug="dnsx",
        adapter_cls=DnsxAdapter,
        docker_image="osa-agent-dnsx:latest",
        tier="active_recon",
        capabilities=("dns_brute", "dns_resolve", "axfr"),
        applicable_domain_tags=frozenset({"network", "osint"}),
        default_risk_band=RiskLevel.MEDIUM,
        is_destructive_capable=False,
    ),
    "httpx": ToolEntry(
        slug="httpx",
        adapter_cls=HttpxAdapter,
        docker_image="osa-agent-httpx:latest",
        tier="passive_low_touch",
        capabilities=("http_status", "title", "tech_detect", "tls_grab"),
        applicable_domain_tags=frozenset({"web", "api", "cloud_aws", "cloud_azure", "cloud_gcp"}),
        default_risk_band=RiskLevel.LOW,
        is_destructive_capable=False,
    ),
    "cloudenum": ToolEntry(
        slug="cloudenum",
        adapter_cls=CloudEnumAdapter,
        docker_image="osa-agent-cloudenum:latest",
        tier="active_recon",
        capabilities=("s3_buckets", "gcs_buckets", "azure_containers"),
        applicable_domain_tags=frozenset({"cloud_aws", "cloud_azure", "cloud_gcp"}),
        default_risk_band=RiskLevel.MEDIUM,
        is_destructive_capable=False,
    ),
    "wappalyzer": ToolEntry(
        slug="wappalyzer",
        adapter_cls=WappalyzerAdapter,
        docker_image="osa-agent-wappalyzer:latest",
        tier="passive_low_touch",
        capabilities=("tech_fingerprint", "framework_detect"),
        applicable_domain_tags=frozenset({"web", "api"}),
        default_risk_band=RiskLevel.LOW,
        is_destructive_capable=False,
    ),
    # ── Kali coexistence (PR-5; digest pin lands in PR-6 via env) ────────
    "kali_gobuster": ToolEntry(
        slug="kali_gobuster",
        adapter_cls=KaliGobusterAdapter,
        docker_image="osa-kali:latest",
        tier="active_recon",
        capabilities=("dir_brute", "dns_brute", "vhost_brute"),
        applicable_domain_tags=frozenset({"web", "api"}),
        default_risk_band=RiskLevel.MEDIUM,
        is_destructive_capable=False,
    ),
    "kali_sqlmap": ToolEntry(
        slug="kali_sqlmap",
        adapter_cls=KaliSqlmapAdapter,
        docker_image="osa-kali:latest",
        tier="active_exploit",
        capabilities=("sqli_detect", "sqli_exploit"),
        applicable_domain_tags=frozenset({"web", "api"}),
        default_risk_band=RiskLevel.HIGH,
        is_destructive_capable=True,
    ),
    "kali_nikto": ToolEntry(
        slug="kali_nikto",
        adapter_cls=KaliNiktoAdapter,
        docker_image="osa-kali:latest",
        tier="active_recon",
        capabilities=("web_vuln_scan",),
        applicable_domain_tags=frozenset({"web", "api"}),
        default_risk_band=RiskLevel.MEDIUM,
        is_destructive_capable=False,
    ),
}


# ── Public API ──────────────────────────────────────────────────────────────


def get_adapter(agent_type: str) -> AgentAdapter:
    """Return an instantiated adapter for the slug.

    Kali slugs (``kali_*``) route through ``KaliBackend`` (the hardened
    sibling) and require the ``OSA_KALI_BACKEND_ENABLED`` flag; every other
    slug stays on the legacy ``DockerBackend`` to preserve Principle 5
    (coexist, do not migrate).
    """
    entry = _REGISTRY.get(agent_type)
    if not entry:
        raise ValueError(f"Unknown agent type: {agent_type}")
    if agent_type.startswith("kali_"):
        if not settings.osa_kali_backend_enabled:
            raise KaliBackendDisabledError(
                f"kali backend disabled — set OSA_KALI_BACKEND_ENABLED=true to enable "
                f"(slug={agent_type})"
            )
        return entry.adapter_cls(backend=get_kali_backend())
    return entry.adapter_cls(backend=get_docker_backend())


def list_agent_types() -> list[str]:
    """Return slugs (backward-compatible)."""
    return list(_REGISTRY.keys())


def get_tool_entry(slug: str) -> ToolEntry | None:
    return _REGISTRY.get(slug)


def list_tool_entries() -> list[ToolEntry]:
    return list(_REGISTRY.values())


def palette_for_domain(domain_tags: frozenset[str]) -> list[ToolEntry]:
    """Return tools whose ``applicable_domain_tags`` intersect ``domain_tags``.

    kali_* tools are filtered out when ``OSA_KALI_BACKEND_ENABLED`` is False
    (double enforcement with ``get_adapter`` — the planner never even sees
    them as options when the flag is off).
    """
    kali_enabled = settings.osa_kali_backend_enabled
    return [
        t for t in _REGISTRY.values()
        if t.applicable_domain_tags & domain_tags
        and (kali_enabled or not t.slug.startswith("kali_"))
    ]


def register_tool_entry(entry: ToolEntry) -> None:
    """Register a new tool (used by P1 active-recon adapters and tests)."""
    if entry.slug in _REGISTRY:
        raise ValueError(f"Tool already registered: {entry.slug}")
    _REGISTRY[entry.slug] = entry


def unregister_tool_entry(slug: str) -> None:
    """Remove a tool slug (test cleanup helper)."""
    _REGISTRY.pop(slug, None)


def get_tier(slug: str) -> Tier | None:
    entry = _REGISTRY.get(slug)
    return entry.tier if entry else None
