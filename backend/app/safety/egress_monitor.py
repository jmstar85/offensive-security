"""Runtime egress monitor — validates outbound connections during execution.

Tails Docker container logs for connection patterns and cross-references
against the project whitelist. On violation → auto-triggers kill switch.
"""
from __future__ import annotations

import ipaddress
import re
import uuid

CONNECTION_PATTERN = re.compile(
    r"(?:Connecting to|Connected to|CONNECT|SYN)\s+(\d{1,3}(?:\.\d{1,3}){3})"
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

    def _is_allowed(self, ip: str) -> bool:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return True  # non-IP strings are not actionable
        # Allow loopback / private ranges used internally
        if addr.is_loopback or addr.is_link_local:
            return True
        return any(addr in net for net in self._allowed_networks)

    async def monitor_log_line(self, line: str, actor_id: str) -> bool:
        """Returns True if line is safe, False if violation detected (kill triggered)."""
        for match in CONNECTION_PATTERN.finditer(line):
            ip = match.group(1)
            if not self._is_allowed(ip):
                await self._trigger_kill(ip, line, actor_id)
                return False
        return True

    async def _trigger_kill(self, ip: str, line: str, actor_id: str) -> None:
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
            "message": f"Egress violation: connection to out-of-scope IP {ip}",
            "line": line,
        })
