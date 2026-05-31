"""XBOW agent-family seed module (MF5).

Imported ONLY when osa_xbow_families_enabled=True. Registers three Role
subclasses on first import via the lazy_register_if_enabled() helper.
Critical invariant: backend/app/orchestrator/roles/seed.py registers the
Minimal-6 roles at module-import time and MUST remain unchanged. This
module sits beside it and never registers automatically.
"""
from __future__ import annotations

import enum
from typing import Any

from app.orchestrator.roles.base import Role, RoleResult
from app.orchestrator.roles.registry import register_role


class AttackVector(str, enum.Enum):
    WEB_APP = "web_app"
    NETWORK = "network"
    CLOUD = "cloud"
    MOBILE = "mobile"
    UNKNOWN = "unknown"


# Each AttackVector maps to a closed palette of legacy tool slugs the family
# is permitted to dispatch. Keys must match AttackVector values; values must
# be a subset of backend/app/agents/registry.py's 13-slug catalog.
vector_to_tool_palette: dict[AttackVector, list[str]] = {
    AttackVector.WEB_APP: ["nuclei", "httpx", "wappalyzer", "kali_gobuster", "kali_sqlmap", "kali_nikto"],
    AttackVector.NETWORK: ["nmap", "passive_recon", "subfinder", "dnsx"],
    AttackVector.CLOUD: ["cloudenum"],
    AttackVector.MOBILE: [],
    AttackVector.UNKNOWN: ["nmap", "passive_recon"],
}


class SessionManagementAgent(Role):
    """Top-level family coordinator. Decides which DiscoveryAgent + AttackAgent
    families to spawn for a given AttackVector. Slug = 'session_management_agent'."""

    slug = "session_management_agent"
    name = "session_management_agent"

    async def run(self, *, performer: Any, context: dict[str, Any]) -> RoleResult:
        vector = context.get("attack_vector", AttackVector.UNKNOWN)
        return RoleResult(
            role_name=self.slug,
            messages=[{"role": "assistant", "content": f"session_management_agent: vector={vector}"}],
            finished=False,
        )


class DiscoveryAgent(Role):
    slug = "discovery_agent"
    name = "discovery_agent"

    async def run(self, *, performer: Any, context: dict[str, Any]) -> RoleResult:
        vector = context.get("attack_vector", AttackVector.UNKNOWN)
        palette = vector_to_tool_palette.get(vector, [])
        return RoleResult(
            role_name=self.slug,
            messages=[{"role": "assistant", "content": f"discovery_agent palette={palette}"}],
            finished=False,
        )


class AttackAgent(Role):
    slug = "attack_agent"
    name = "attack_agent"

    async def run(self, *, performer: Any, context: dict[str, Any]) -> RoleResult:
        from app.core.config import settings
        vector = context.get("attack_vector", AttackVector.UNKNOWN)

        # When OSA_TRAFFIC_VIA_MITM is on, AttackAgent egress goes through
        # the mitmproxy sidecar — the proxy address is published via
        # OSA_MITM_PROXY_URL (compose env). DiscoveryAgent + SessionManagement
        # are intentionally NOT routed (recon traffic stays direct so the
        # MITM addons don't drown in noise). This is gated to Attack-family
        # only.
        egress_via_mitm = bool(settings.osa_traffic_via_mitm)
        proxy_url = None
        if egress_via_mitm:
            import os
            proxy_url = os.environ.get("OSA_MITM_PROXY_URL", "http://mitmproxy:8080")
            context["_attack_agent_egress_proxy"] = proxy_url

        return RoleResult(
            role_name=self.slug,
            messages=[{
                "role": "assistant",
                "content": (
                    f"attack_agent vector={vector} "
                    f"egress_via_mitm={egress_via_mitm} "
                    f"proxy={proxy_url or 'direct'}"
                ),
            }],
            finished=False,
        )


class FamilySpawner:
    """Coordinates spawning DiscoveryAgent + AttackAgent families per session.

    Per SF-CRITIC-6, max_concurrent_per_family defaults to 4 and has a hard
    ceiling of 8 (enforced via _PerformerLease — wired by PR2b.2).
    """

    MAX_CONCURRENT_PER_FAMILY_DEFAULT = 4
    MAX_CONCURRENT_PER_FAMILY_HARD_CEILING = 8

    def __init__(self, max_concurrent_per_family: int = 4) -> None:
        if max_concurrent_per_family > self.MAX_CONCURRENT_PER_FAMILY_HARD_CEILING:
            raise ValueError(
                f"max_concurrent_per_family={max_concurrent_per_family} exceeds "
                f"hard ceiling {self.MAX_CONCURRENT_PER_FAMILY_HARD_CEILING} (SF-CRITIC-6)"
            )
        self.max_concurrent_per_family = max_concurrent_per_family

    def palette_for(self, vector: AttackVector) -> list[str]:
        return list(vector_to_tool_palette.get(vector, []))


def _register_all() -> None:
    """Idempotent registration of all three families. Called from
    lazy_register_if_enabled() — NOT at module import. This keeps
    ROLE_REGISTRY pristine when osa_xbow_families_enabled=False."""
    for role_cls in (SessionManagementAgent, DiscoveryAgent, AttackAgent):
        register_role(role_cls)
