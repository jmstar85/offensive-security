"""Runtime egress monitor — validates outbound connections during execution.

Tails Docker container logs for connection patterns and cross-references
against the project whitelist. On violation → auto-triggers kill switch.
"""
from __future__ import annotations

import ipaddress
import re
import uuid

_IPV4 = r"\d{1,3}(?:\.\d{1,3}){3}"
_IPV6 = r"[0-9a-fA-F:]*:[0-9a-fA-F:]+"
# PR9: widened beyond the single IPv4 verb. Catches more connection verbs + IPv6 +
# `host:port` forms. Group 1 is the IP (v4 or bracketed/raw v6).
CONNECTION_PATTERN = re.compile(
    rf"(?:Connecting to|Connected to|CONNECT|SYN|connect\(\)|->|=>)\s*"
    rf"(?:to\s+)?(?:\[({_IPV6})\]|({_IPV4})|({_IPV6}))",
    re.IGNORECASE,
)
# PR9: hostnames in connection-indicating contexts (DNS resolution / TLS SNI / HTTP
# Host header / explicit connect). Anchored to those prefixes to keep noise low —
# we do NOT flag every domain mentioned in tool output, only ones being connected to.
_FQDN = (
    r"([a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+)"
)
HOST_PATTERN = re.compile(
    r"(?:Host:\s*|SNI[:=]\s*|server_name[:=]\s*|resolving\s+|"
    r"DNS (?:query|lookup) for\s+|Connecting to\s+)" + _FQDN,
    re.IGNORECASE,
)


class EgressMonitor:
    def __init__(
        self,
        session_id: uuid.UUID,
        whitelist_rules: dict,
    ) -> None:
        self._session_id = session_id
        self._allowed_networks = [
            ipaddress.ip_network(cidr, strict=False)
            for cidr in whitelist_rules.get("ip_ranges", [])
        ]
        self._allowed_domains = [
            str(d).lower().lstrip("*.") for d in whitelist_rules.get("domains", [])
        ]

    def _is_allowed(self, ip: str) -> bool:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return True  # non-IP strings are not actionable
        # Allow loopback / link-local used internally. Private ranges are NOT
        # blanket-allowed — an off-scope private IP (internal SSRF) is still checked
        # against the whitelist.
        if addr.is_loopback or addr.is_link_local:
            return True
        return any(addr in net for net in self._allowed_networks)

    def _is_host_allowed(self, host: str) -> bool:
        """A connection-context hostname is allowed iff it matches an in-scope domain
        (or a subdomain of one). When NO domain scope is defined we cannot judge a
        hostname, so we do not flag it (avoids false-positive kills on recon noise)."""
        host = host.lower().rstrip(".")
        if not self._allowed_domains:
            return True
        if host in ("localhost",) or host.endswith(".local"):
            return True
        return any(host == d or host.endswith("." + d) for d in self._allowed_domains)

    async def monitor_log_line(self, line: str, actor_id: str) -> bool:
        """Returns True if line is safe, False if violation detected (kill triggered)."""
        for match in CONNECTION_PATTERN.finditer(line):
            ip = next((g for g in match.groups() if g), "")
            if ip and not self._is_allowed(ip):
                await self._trigger_kill(ip, line, actor_id)
                return False
        for match in HOST_PATTERN.finditer(line):
            host = match.group(1)
            if not self._is_host_allowed(host):
                await self._trigger_kill(host, line, actor_id)
                return False
        return True

    async def _trigger_kill(self, dest: str, line: str, actor_id: str) -> None:
        from app.core.database import async_session
        from app.core.events import event_bus
        from app.safety.kill_switch import KillSwitch

        async with async_session() as db:
            ks = KillSwitch(db)
            await ks.stop_session(self._session_id, actor_id)
            await db.commit()

        await event_bus.publish(str(self._session_id), {
            "type": "safety_alert",
            "level": "critical",
            "message": f"Egress violation: connection to out-of-scope destination {dest}",
            "line": line,
        })
