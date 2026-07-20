"""subfinder adapter — passive subdomain enumeration via ProjectDiscovery."""
from __future__ import annotations

from app.agents.base import (
    AgentAdapter,
    AgentResult,
    RiskLevel,
    filter_resolvable_targets,
)


class SubfinderAdapter(AgentAdapter):
    agent_type = "subfinder"
    docker_image = "osa-agent-subfinder:latest"
    risk_level = RiskLevel.MEDIUM

    def get_capabilities(self) -> list[str]:
        return ["subdomain_enumeration", "passive_dns"]

    def build_command(self, target: dict, config: dict) -> list[str]:
        # Prefer a resolvable domain over a bogus single-label placeholder
        # (mirror NmapAdapter); a single-label-only list keeps its first entry.
        domain = config.get("domain") or filter_resolvable_targets(
            target.get("domains", []) or ["example.com"]
        )[0]
        return ["-d", domain, "-silent", "-oJ"]

    def parse_output(self, raw_output: str) -> AgentResult:
        findings: list[dict] = []
        import json as _json
        for line in raw_output.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = _json.loads(line)
                findings.append({"type": "subdomain", **obj})
            except _json.JSONDecodeError:
                findings.append({"type": "subdomain", "host": line})
        return AgentResult(
            agent_type=self.agent_type,
            success=True,
            findings=findings,
            raw_output=raw_output,
        )
