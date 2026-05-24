"""cloudenum adapter — public cloud bucket / asset discovery."""
from __future__ import annotations

from app.agents.base import AgentAdapter, AgentResult, RiskLevel


class CloudEnumAdapter(AgentAdapter):
    agent_type = "cloudenum"
    docker_image = "osa-agent-cloudenum:latest"
    risk_level = RiskLevel.MEDIUM

    def get_capabilities(self) -> list[str]:
        return ["s3_buckets", "gcs_buckets", "azure_containers", "azure_websites"]

    def build_command(self, target: dict, config: dict) -> list[str]:
        keyword = config.get("keyword") or (target.get("domains", []) or ["example"])[0].split(".")[0]
        return ["-k", keyword]

    def parse_output(self, raw_output: str) -> AgentResult:
        findings: list[dict] = []
        for line in raw_output.splitlines():
            line = line.strip()
            if not line:
                continue
            if any(token in line.upper() for token in ("OPEN", "PROTECTED", "FOUND")):
                findings.append({"line": line})
        return AgentResult(
            agent_type=self.agent_type,
            success=True,
            findings=findings,
            raw_output=raw_output,
        )
