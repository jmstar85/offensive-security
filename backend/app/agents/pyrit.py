"""PyRIT agent adapter — AI Red Teaming (Microsoft PyRIT)."""
from __future__ import annotations

import json

from app.agents.base import AgentAdapter, AgentResult, RiskLevel


class PyRITAdapter(AgentAdapter):
    agent_type = "pyrit"
    docker_image = "osa-agent-pyrit:latest"
    risk_level = RiskLevel.MEDIUM
    OPTIONS_SCHEMA: dict = {
        "type": "object",
        "properties": {
            "attack_type": {
                "type": "string",
                "enum": ["llm_prompt_injection", "llm_jailbreak", "llm_data_extraction", "api_fuzzing"],
                "description": "Type of AI/LLM attack"
            },
            "endpoint": {"type": "string", "description": "Target LLM API endpoint URL"},
            "iterations": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 50},
            "strategy": {
                "type": "string",
                "enum": ["crescendo", "tree_of_attacks", "flip", "pair"],
                "default": "crescendo"
            },
        }
    }

    def get_capabilities(self) -> list[str]:
        return ["ai_red_teaming", "prompt_injection_test", "jailbreak_detection", "llm_safety"]

    def build_command(self, target: dict, config: dict) -> list[str]:
        endpoint = config.get("endpoint", target.get("domains", ["localhost"])[0])
        attack_type = config.get("attack_type", "prompt_injection")
        return [
            "python", "-m", "pyrit.orchestrator.red_teaming_orchestrator",
            "--target-endpoint", endpoint,
            "--attack-type", attack_type,
            "--output-format", "json",
            "--output-file", "/tmp/pyrit_results.json",
        ]

    def parse_output(self, raw_output: str) -> AgentResult:
        findings: list[dict] = []
        for line in raw_output.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                if item.get("jailbroken") or item.get("success"):
                    findings.append({
                        "type": "ai_vulnerability",
                        "attack_type": item.get("attack_type", "unknown"),
                        "prompt": item.get("prompt", ""),
                        "response": item.get("response", ""),
                        "severity": "high" if item.get("jailbroken") else "medium",
                        "cvss_score": 7.5 if item.get("jailbroken") else 5.0,
                    })
            except (json.JSONDecodeError, KeyError):
                continue

        return AgentResult(
            agent_type=self.agent_type,
            success=True,
            findings=findings,
            raw_output=raw_output,
        )
