"""Nuclei agent adapter — template-based vulnerability scanner."""
from __future__ import annotations

import json
import re

from app.agents.base import AgentAdapter, AgentResult, ExecutionBackend, RiskLevel

# Severity mapping to numeric risk score (CVSS-ish)
_SEVERITY_SCORE = {"critical": 9.0, "high": 7.0, "medium": 5.0, "low": 3.0, "info": 1.0}


class NucleiAdapter(AgentAdapter):
    agent_type = "nuclei"
    docker_image = "osa-agent-nuclei:latest"
    risk_level = RiskLevel.MEDIUM

    def get_capabilities(self) -> list[str]:
        return ["cve_scan", "web_vulnerability_scan", "misconfiguration_detection", "exposures"]

    def build_command(self, target: dict, config: dict) -> list[str]:
        targets = target.get("domains", []) + target.get("ip_ranges", [])
        target_str = ",".join(targets) if targets else "127.0.0.1"
        severity = config.get("severity", "low,medium,high,critical")
        # JSON-lines output for easy parsing; exclude critical destructive templates
        return [
            "nuclei", "-u", target_str,
            "-severity", severity,
            "-exclude-tags", "dos,fuzz",
            "-json-export", "/tmp/nuclei_results.json",
            "-silent",
        ]

    def parse_output(self, raw_output: str) -> AgentResult:
        findings: list[dict] = []
        for line in raw_output.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                severity = item.get("info", {}).get("severity", "info").lower()
                findings.append({
                    "type": "vulnerability",
                    "template_id": item.get("template-id", ""),
                    "name": item.get("info", {}).get("name", ""),
                    "severity": severity,
                    "cvss_score": _SEVERITY_SCORE.get(severity, 1.0),
                    "url": item.get("matched-at", ""),
                    "description": item.get("info", {}).get("description", ""),
                    "cve": item.get("info", {}).get("classification", {}).get("cve-id", []),
                })
            except (json.JSONDecodeError, KeyError):
                continue

        return AgentResult(
            agent_type=self.agent_type,
            success=True,
            findings=findings,
            raw_output=raw_output,
        )
