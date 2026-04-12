"""Triple-layer whitelist validator — rejects any out-of-scope targets."""
from __future__ import annotations

import ipaddress
import re


class WhitelistValidator:
    """Validates that all IPs/domains in a pentest target are within the project whitelist."""

    def __init__(self, whitelist_rules: dict) -> None:
        self._allowed_networks = [
            ipaddress.ip_network(cidr, strict=False)
            for cidr in whitelist_rules.get("ip_ranges", [])
        ]
        self._allowed_domains = set(whitelist_rules.get("domains", []))

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
