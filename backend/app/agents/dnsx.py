"""dnsx adapter — fast DNS resolution / record enumeration."""
from __future__ import annotations

import json as _json

from app.agents.base import AgentAdapter, AgentResult, RiskLevel


class DnsxAdapter(AgentAdapter):
    agent_type = "dnsx"
    docker_image = "osa-agent-dnsx:latest"
    risk_level = RiskLevel.MEDIUM

    def get_capabilities(self) -> list[str]:
        return ["dns_brute", "dns_resolve", "axfr"]

    def build_command(self, target: dict, config: dict) -> list[str]:
        domain = config.get("domain") or (target.get("domains", []) or ["example.com"])[0]
        record_types = config.get("record_types", "a,aaaa,cname,ns,mx,txt")
        return ["-d", domain, "-resp", "-a", "-cname", "-r", record_types, "-j"]

    def parse_output(self, raw_output: str) -> AgentResult:
        findings: list[dict] = []
        for line in raw_output.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                findings.append(_json.loads(line))
            except _json.JSONDecodeError:
                findings.append({"line": line})
        return AgentResult(
            agent_type=self.agent_type,
            success=True,
            findings=findings,
            raw_output=raw_output,
        )
