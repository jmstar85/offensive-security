"""Nmap agent adapter — network scanning and port discovery."""
from __future__ import annotations

import re

from app.agents.base import AgentAdapter, AgentResult, RiskLevel


class NmapAdapter(AgentAdapter):
    agent_type = "nmap"
    docker_image = "osa-agent-nmap:latest"
    risk_level = RiskLevel.LOW

    def get_capabilities(self) -> list[str]:
        return ["port_scan", "service_detection", "os_detection", "network_discovery"]

    def build_command(self, target: dict, config: dict) -> list[str]:
        raw_targets = target.get("ip_ranges", []) + target.get("domains", [])
        # Domains are optional. Drop single-label placeholders (e.g. "jarvis")
        # that can't resolve when there are still IP/CIDR/FQDN targets to scan —
        # a bogus domain otherwise floods the output with "Failed to resolve".
        # An IP/CIDR contains "." or "/", an FQDN contains ".", IPv6 contains ":".
        targets = [t for t in raw_targets if ("." in t or ":" in t or "/" in t)]
        if not targets:
            targets = raw_targets or ["127.0.0.1"]
        # Default to a scan that works inside the HARDENED agent sandbox: TCP
        # connect (-sT) uses the OS stack and needs no raw sockets, so it succeeds
        # when the container drops CAP_NET_RAW; -Pn skips host discovery (many
        # hosts — e.g. Azure web servers — block ICMP). OS detection (-O) and
        # SYN/raw scans require CAP_NET_RAW that the sandbox removes, which makes
        # nmap fail with "failed to determine route" / "couldn't open a raw
        # socket". Callers can still override via config["flags"].
        flags = config.get("flags", "-sT -sV --open -T4 -Pn")
        # The image ENTRYPOINT is `nmap`, so emit ARGS ONLY (no leading "nmap").
        # Each target is its own argv element — a single space-joined string is
        # parsed by nmap as one (invalid) target expression.
        return [*flags.split(), "-oX", "/tmp/scan.xml", *targets]

    def parse_output(self, raw_output: str) -> AgentResult:
        findings: list[dict] = []

        # Extract open ports via simple regex on nmap text output
        port_pattern = re.compile(r"(\d+)/tcp\s+open\s+(\S+)\s*(.*)")
        for match in port_pattern.finditer(raw_output):
            port, service, version = match.groups()
            findings.append({
                "type": "open_port",
                "port": int(port),
                "protocol": "tcp",
                "service": service.strip(),
                "version": version.strip(),
                "severity": "info",
            })

        return AgentResult(
            agent_type=self.agent_type,
            success=True,
            findings=findings,
            raw_output=raw_output,
        )
