"""Runtime egress monitor — validates outbound connections during execution.

Tails Docker container logs for connection patterns and cross-references
against the project whitelist. On violation → auto-triggers kill switch.
"""
from __future__ import annotations

import ipaddress
import re
import uuid
from dataclasses import dataclass

from app.core.config import settings


@dataclass
class EgressVerdict:
    """Per-call result of an egress check. The action is SINGLE-SOURCED here (not
    read from a shared mutable field) so it is race-free across steps on the
    one-per-session monitor. ``action``: "none" (safe) | "stop_step" (kill only
    this step's container, continue the run) | "kill_session" (stop everything)."""

    safe: bool
    dest: str | None = None
    action: str = "none"

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
        # Session-scoped running total of violations — the circuit-breaker cap
        # reads this so a tool that re-trips every step cannot manufacture N
        # separate out-of-scope connections before the run is hard-killed.
        self._violation_count = 0

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

    async def monitor_log_line(
        self, line: str, actor_id: str, tier: str | None = None
    ) -> EgressVerdict:
        """Check one tool-container log line for an out-of-scope CONNECTION.

        Returns an :class:`EgressVerdict`. On a violation the effective blast
        radius is decided HERE (single-sourced): "session" scope, an
        ``active_exploit``-tier step, or reaching the violation cap all escalate
        to a full session kill; otherwise only this step's container is stopped
        (by the caller) and the run continues.
        """
        dest = None
        for match in CONNECTION_PATTERN.finditer(line):
            ip = next((g for g in match.groups() if g), "")
            if ip and not self._is_allowed(ip):
                dest = ip
                break
        if dest is None:
            for match in HOST_PATTERN.finditer(line):
                host = match.group(1)
                if not self._is_host_allowed(host):
                    dest = host
                    break
        if dest is None:
            return EgressVerdict(safe=True)

        self._violation_count += 1
        scope = getattr(settings, "osa_egress_violation_scope", "session")
        cap = getattr(settings, "osa_egress_violation_cap", 3)
        # Fail-closed escalation: legacy session mode, an exploit-tier tool going
        # off-scope (pivot-to-unauthorized-system), or too many violations → kill
        # the whole session. Otherwise contain to just this step.
        escalate = (
            scope != "step"
            or tier == "active_exploit"
            or self._violation_count >= cap
        )
        await self._trigger_kill(dest, line, actor_id, tier=tier, escalate=escalate)
        return EgressVerdict(
            safe=False,
            dest=dest,
            action="kill_session" if escalate else "stop_step",
        )

    async def _trigger_kill(
        self,
        dest: str,
        line: str,
        actor_id: str,
        *,
        tier: str | None = None,
        escalate: bool = True,
    ) -> None:
        """Record the violation durably (audit row + metric) in BOTH scopes, then
        stop the whole session ONLY when ``escalate`` is True. Always awaited (the
        session-kill-vs-not branch lives inside), and always emits the alert."""
        from app.core.database import async_session
        from app.core.events import event_bus
        from app.observability.metrics import metrics
        from app.safety.audit import AuditLogger
        from app.safety.kill_switch import KillSwitch

        scope = getattr(settings, "osa_egress_violation_scope", "session")
        async with async_session() as db:
            # Durable audit row so a violation is queryable/SIEM-visible even on
            # the step path (which does NOT stop_session and its own audit row).
            try:
                await AuditLogger(db).log(
                    action="egress_violation",
                    actor_id=actor_id,
                    target_entity="pentest_session",
                    target_id=str(self._session_id),
                    details={
                        "dest": dest,
                        "line": line[:500],
                        "scope": scope,
                        "tier": tier,
                        "violation_count": self._violation_count,
                        "escalated": escalate,
                    },
                )
            except Exception:  # noqa: BLE001 — audit must never crash the brake
                pass
            if escalate:
                await KillSwitch(db).stop_session(self._session_id, actor_id)
            await db.commit()

        try:
            metrics.egress_violation_total.inc(
                scope=scope, escalated=str(escalate).lower()
            )
        except Exception:  # noqa: BLE001
            pass

        suffix = "" if escalate else " — step halted; run continuing"
        await event_bus.publish(str(self._session_id), {
            "type": "safety_alert",
            "level": "critical",
            "message": f"Egress violation: connection to out-of-scope destination {dest}{suffix}",
            "line": line,
        })
