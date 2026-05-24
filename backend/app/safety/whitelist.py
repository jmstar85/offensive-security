"""Triple-layer whitelist validator — rejects any out-of-scope targets.

Plan v3.2.1 §5.2 EXTENSION (additive — legacy ip_ranges/domains semantics
unchanged): WhitelistValidator now also reads four optional tier-specific
fields and a deny-pattern list:

    {
      "ip_ranges": [...],           # legacy — passive default
      "domains": [...],             # legacy — passive default
      "passive_allowed":   [...],
      "active_allowed":    [...],
      "exploit_allowed":   [...],
      "wildcard_block_regex": [...] # always-deny, beats every allowlist
    }

The legacy API (``validate_ip``, ``validate_domain``, ``validate_target``)
is preserved exactly. New helpers (``validate_host_by_tier``,
``classify_discovered_host``, ``is_wildcard_blocked``) are added for the
rescope state machine.
"""
from __future__ import annotations

import ipaddress
import re


_TIER_FIELD = {
    "passive_no_target_contact": "passive_allowed",
    "passive_low_touch": "passive_allowed",
    "active_recon": "active_allowed",
    "active_exploit": "exploit_allowed",
}


class WhitelistValidator:
    """Validates that all IPs/domains in a pentest target are within the project whitelist."""

    def __init__(self, whitelist_rules: dict) -> None:
        rules = whitelist_rules or {}
        self._allowed_networks = [
            ipaddress.ip_network(cidr, strict=False)
            for cidr in rules.get("ip_ranges", [])
        ]
        self._allowed_domains = set(rules.get("domains", []))
        self._tier_hosts: dict[str, set[str]] = {
            field: set(rules.get(field, []) or [])
            for field in ("passive_allowed", "active_allowed", "exploit_allowed")
        }
        self._wildcard_block_patterns = [
            re.compile(p) for p in (rules.get("wildcard_block_regex") or [])
        ]

    def validate_ip(self, ip: str) -> bool:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(addr in net for net in self._allowed_networks)

    def validate_domain(self, domain: str) -> bool:
        domain = domain.lower().strip()
        # Exact match or subdomain of an allowed domain
        if domain in self._allowed_domains:
            return True
        return any(
            domain.endswith(f".{allowed}")
            for allowed in self._allowed_domains
        )

    def validate_target(self, target: dict) -> tuple[bool, list[str]]:
        """Returns (is_valid, list_of_violations)."""
        violations: list[str] = []

        for ip in target.get("ip_ranges", []):
            # Handle CIDR notation in target
            try:
                net = ipaddress.ip_network(ip, strict=False)
                for host in ([net.network_address] if net.num_addresses == 1 else [net.network_address, net.broadcast_address]):
                    if not self.validate_ip(str(host)):
                        violations.append(f"IP out of scope: {ip}")
                        break
            except ValueError:
                violations.append(f"Invalid IP/CIDR: {ip}")

        for domain in target.get("domains", []):
            if not self.validate_domain(domain):
                violations.append(f"Domain out of scope: {domain}")

        return len(violations) == 0, violations

    # ── plan v3.2.1 §5.2 extensions (additive) ────────────────────────────

    def is_wildcard_blocked(self, host: str) -> bool:
        """Return True iff ``host`` matches any wildcard_block_regex pattern."""
        return any(p.search(host) for p in self._wildcard_block_patterns)

    def _host_matches_tier_field(self, host: str, field: str) -> bool:
        candidates = self._tier_hosts.get(field, set())
        if not candidates:
            return False
        host_lc = host.lower().strip()
        if host_lc in candidates:
            return True
        for allowed in candidates:
            if host_lc.endswith(f".{allowed.lower()}"):
                return True
        try:
            ip = ipaddress.ip_address(host)
            for cidr in candidates:
                try:
                    if ip in ipaddress.ip_network(cidr, strict=False):
                        return True
                except ValueError:
                    continue
        except ValueError:
            pass
        return False

    def validate_host_by_tier(self, host: str, tier: str) -> tuple[bool, str | None]:
        """Validate a single host against the tier-specific allowlist.

        Per plan v3.2.1 §5.2 the rule is strict: each tier requires its own
        explicit allowlist field (``passive_allowed`` for tiers 1+2,
        ``active_allowed`` for tier 3, ``exploit_allowed`` for tier 4).
        Wildcard block patterns beat every allowlist.

        Returns ``(is_valid, reason_or_None)``.
        """
        if self.is_wildcard_blocked(host):
            return False, "wildcard_block_regex match"

        field = _TIER_FIELD.get(tier)
        if field is None:
            return False, f"unknown tier: {tier}"

        if self._host_matches_tier_field(host, field):
            return True, None
        return False, f"host not in {field}"

    def classify_discovered_host(
        self,
        host: str,
        tier: str,
    ) -> tuple[bool, str | None]:
        """Alias for ``validate_host_by_tier`` — emphasises rescope intent."""
        return self.validate_host_by_tier(host, tier)
