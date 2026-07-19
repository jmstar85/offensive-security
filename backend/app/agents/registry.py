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
from app.agents.headless_browser import HeadlessBrowserAdapter
from app.agents.interactsh import InteractshAdapter
from app.agents.mitmproxy import MitmProxyAdapter
from app.agents.subfinder import SubfinderAdapter
from app.agents.wappalyzer import WappalyzerAdapter

Tier = Literal[
    "passive_no_target_contact",
    "passive_low_touch",
    "active_recon",
    "mid_active",
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
    # One-line operator-facing summary. Surfaced through /agents/catalog so
    # the AgentCatalog cards stop rendering an empty description block.
    # New entries SHOULD set this; the registration tests fail if left blank.
    description: str = ""


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
        description="Port scanner with service / OS fingerprinting.",
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
        description="YAML-template driven vulnerability scanner.",
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
        description="Approved auxiliary / post / handler module runner.",
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
        description="AI red-team / LLM jailbreak probe harness.",
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
        description="DNS / cert / robots-txt / secret OSINT — no target contact.",
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
        description="Passive subdomain enumeration via public sources.",
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
        description="DNS resolve / brute-force / AXFR probe.",
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
        description="HTTP probe — status / title / tech / TLS metadata.",
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
        description="Public S3 / GCS / Azure container enumeration.",
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
        description="Web technology fingerprinting from HTTP responses.",
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
        description="Gobuster: directory / DNS / vhost brute-force (Kali).",
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
        description="sqlmap: SQL injection detection and exploitation (Kali).",
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
        description="Nikto: web-server misconfiguration scanner (Kali).",
    ),
    # ── W3 mid_active / new adapters ─────────────────────────────────────
    "mitm_proxy": ToolEntry(
        slug="mitm_proxy",
        adapter_cls=MitmProxyAdapter,
        docker_image="osa-mitmproxy:latest",
        tier="mid_active",
        capabilities=("intercept_http", "intercept_https", "addon_inject"),
        applicable_domain_tags=frozenset({"web", "api"}),
        default_risk_band=RiskLevel.MEDIUM,
        is_destructive_capable=False,
        description="MITM HTTP/HTTPS interception sidecar.",
    ),
    "headless_browser": ToolEntry(
        slug="headless_browser",
        adapter_cls=HeadlessBrowserAdapter,
        docker_image="osa-headless-browser:latest",
        tier="mid_active",
        capabilities=("dom_render", "js_eval", "csrf_replay"),
        applicable_domain_tags=frozenset({"web"}),
        default_risk_band=RiskLevel.MEDIUM,
        is_destructive_capable=False,
        description="Playwright-based DOM/JS probe runner.",
    ),
    "session_manager": ToolEntry(
        slug="session_manager",
        adapter_cls=HeadlessBrowserAdapter,  # piggybacks on headless for cookie/session work
        docker_image="osa-headless-browser:latest",
        tier="mid_active",
        capabilities=("session_replay", "cookie_juggle"),
        applicable_domain_tags=frozenset({"web"}),
        default_risk_band=RiskLevel.MEDIUM,
        is_destructive_capable=False,
        description="Cookie + session replay coordinator (uses headless sidecar).",
    ),
    "interactsh_collaborator": ToolEntry(
        slug="interactsh_collaborator",
        adapter_cls=InteractshAdapter,
        docker_image="osa-interactsh:latest",
        tier="passive_low_touch",
        capabilities=("oob_dns", "oob_http"),
        applicable_domain_tags=frozenset({"web", "api", "network"}),
        default_risk_band=RiskLevel.LOW,
        is_destructive_capable=False,
        description="Out-of-band collaborator for OOB-XSS/SSRF correlation.",
    ),
    # ── W3 Kali slugs (xsstrike/dalfox/ffuf/commix) ──────────────────────
    "kali_xsstrike": ToolEntry(
        slug="kali_xsstrike",
        adapter_cls=(__import__("app.agents.kali_exec", fromlist=["KaliGobusterAdapter"]).KaliGobusterAdapter),
        docker_image="osa-kali:latest",
        tier="active_exploit",
        capabilities=("dom_xss", "reflected_xss"),
        applicable_domain_tags=frozenset({"web"}),
        default_risk_band=RiskLevel.HIGH,
        is_destructive_capable=True,
        description="xsstrike — XSS probe (Kali).",
    ),
    "kali_dalfox": ToolEntry(
        slug="kali_dalfox",
        adapter_cls=(__import__("app.agents.kali_exec", fromlist=["KaliGobusterAdapter"]).KaliGobusterAdapter),
        docker_image="osa-kali:latest",
        tier="active_exploit",
        capabilities=("dom_xss",),
        applicable_domain_tags=frozenset({"web"}),
        default_risk_band=RiskLevel.HIGH,
        is_destructive_capable=True,
        description="dalfox — XSS scanner (Kali).",
    ),
    "kali_ffuf": ToolEntry(
        slug="kali_ffuf",
        adapter_cls=(__import__("app.agents.kali_exec", fromlist=["KaliGobusterAdapter"]).KaliGobusterAdapter),
        docker_image="osa-kali:latest",
        tier="active_recon",
        capabilities=("dir_fuzz", "param_fuzz"),
        applicable_domain_tags=frozenset({"web", "api"}),
        default_risk_band=RiskLevel.MEDIUM,
        is_destructive_capable=False,
        description="ffuf — fuzzer (Kali).",
    ),
    "kali_commix": ToolEntry(
        slug="kali_commix",
        adapter_cls=(__import__("app.agents.kali_exec", fromlist=["KaliGobusterAdapter"]).KaliGobusterAdapter),
        docker_image="osa-kali:latest",
        tier="active_exploit",
        capabilities=("command_injection",),
        applicable_domain_tags=frozenset({"web", "api"}),
        default_risk_band=RiskLevel.HIGH,
        is_destructive_capable=True,
        description="commix — command-injection (Kali).",
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


def palette_lines(kali_enabled: bool) -> list[str]:
    """Return one compact palette line per VISIBLE tool entry.

    Mirrors the ``_is_visible_tool`` filter in ``app/api/v1/agents.py``:
    ``kali_*`` slugs are hidden when ``kali_enabled`` is False. Callers pass
    ``settings.osa_kali_backend_enabled``. Registry-only (does NOT import the
    API layer) so the Generator can ground its draft plan in the real tool
    palette without pulling in the FastAPI stack.

    Each line has the shape::

        - {slug}  (tier: {tier})  actions: {a, b, c}  — {description}

    where ``actions`` are the tool's real ``capabilities`` (the only valid
    ``action`` values) — so the LLM cannot invent agent/action names.
    """
    lines: list[str] = []
    for entry in _REGISTRY.values():
        if entry.slug.startswith("kali_") and not kali_enabled:
            continue
        actions = ", ".join(entry.capabilities)
        lines.append(
            f"- {entry.slug}  (tier: {entry.tier})  actions: {actions}"
            f"  — {entry.description}"
        )
    return lines


def palette_text(kali_enabled: bool) -> str:
    """Newline-joined :func:`palette_lines` — convenience for prompt injection."""
    return "\n".join(palette_lines(kali_enabled))


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
