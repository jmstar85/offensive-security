"""wappalyzer adapter — passive technology fingerprinting (tier=passive_low_touch)."""
from __future__ import annotations

import json as _json

from app.agents.base import AgentAdapter, AgentResult, RiskLevel


class WappalyzerAdapter(AgentAdapter):
    agent_type = "wappalyzer"
    docker_image = "osa-agent-wappalyzer:latest"
    risk_level = RiskLevel.LOW

    def get_capabilities(self) -> list[str]:
        return ["tech_fingerprint", "framework_detect"]

    def build_command(self, target: dict, config: dict) -> list[str]:
        url = config.get("url") or "https://" + (target.get("domains", []) or ["example.com"])[0]
        return [url, "--user-agent", "OSA-passive-recon/1.0"]

    def parse_output(self, raw_output: str) -> AgentResult:
        findings: list[dict] = []
        try:
            data = _json.loads(raw_output)
            for tech in data.get("technologies", []):
                findings.append({"type": "technology", **tech})
        except _json.JSONDecodeError:
            for line in raw_output.splitlines():
                if ":" in line:
                    findings.append({"line": line.strip()})
        return AgentResult(
            agent_type=self.agent_type,
            success=True,
            findings=findings,
            raw_output=raw_output,
        )
