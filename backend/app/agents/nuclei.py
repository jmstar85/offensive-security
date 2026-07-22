"""Nuclei agent adapter — template-based vulnerability scanner."""
from __future__ import annotations

import json

from app.agents.base import (
    AgentAdapter,
    AgentResult,
    RiskLevel,
    filter_resolvable_targets,
)

# Severity mapping to numeric risk score (CVSS-ish)
_SEVERITY_SCORE = {"critical": 9.0, "high": 7.0, "medium": 5.0, "low": 3.0, "info": 1.0}


class NucleiAdapter(AgentAdapter):
    agent_type = "nuclei"
    docker_image = "osa-agent-nuclei:latest"
    risk_level = RiskLevel.MEDIUM

    def get_capabilities(self) -> list[str]:
        return ["cve_scan", "web_vulnerability_scan", "misconfiguration_detection", "exposures"]

    def build_command(self, target: dict, config: dict) -> list[str]:
        # Drop bogus single-label domains (e.g. "jarvis") when a resolvable
        # target co-exists, mirroring NmapAdapter — otherwise nuclei wastes the
        # run resolving a placeholder that can never answer.
        raw = (target.get("domains", []) or []) + (target.get("ip_ranges", []) or [])
        targets = filter_resolvable_targets(raw)
        target_str = ",".join(targets)
        severity = config.get("severity", "low,medium,high,critical")
        # `-jsonl` streams each finding as a JSON line to STDOUT, which is what
        # parse_output() consumes. The prior `-json-export <file>` wrote results to
        # a file INSIDE the container that was never read back, and `-silent`
        # suppressed stdout, so nuclei reported 0 findings even when it matched
        # (session 9a7d4563). `-timeout`/`-retries`/`-rate-limit` bound the runtime
        # so a filtered/slow host can't stretch the ~7k-template scan into hours
        # (the per-step execution timeout is the hard backstop).
        # The image ENTRYPOINT is `nuclei`, so emit ARGS ONLY (no leading "nuclei").
        return [
            "-u", target_str,
            "-jsonl",
            "-silent",
            "-severity", severity,
            "-exclude-tags", "dos,fuzz",
            "-timeout", str(config.get("http_timeout", 5)),
            "-retries", str(config.get("retries", 1)),
            "-rate-limit", str(config.get("rate_limit", 150)),
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
