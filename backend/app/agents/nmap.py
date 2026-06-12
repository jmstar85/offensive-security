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
        targets = target.get("ip_ranges", []) + target.get("domains", [])
        if not targets:
            targets = ["127.0.0.1"]
        flags = config.get("flags", "-sV -sC -O --open -T4")
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
