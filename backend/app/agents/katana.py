"""katana adapter — web crawler / endpoint discovery (ProjectDiscovery).

Fills a real gap: nothing else in the toolkit spiders the application to
discover its URL/endpoint surface (the input the OWASP web scanners need). Runs
at tier=active_recon (crawling contacts the target). Findings stream as JSONL to
stdout so parse_output reads them directly.
"""
from __future__ import annotations

import json as _json

from app.agents.base import (
    AgentAdapter,
    AgentResult,
    RiskLevel,
    filter_resolvable_targets,
)


class KatanaAdapter(AgentAdapter):
    agent_type = "katana"
    docker_image = "osa-agent-katana:latest"
    risk_level = RiskLevel.MEDIUM

    def get_capabilities(self) -> list[str]:
        return ["crawl", "endpoint_discovery", "spider"]

    def build_command(self, target: dict, config: dict) -> list[str]:
        raw = (target.get("domains", []) or []) + (target.get("ip_ranges", []) or [])
        hosts = filter_resolvable_targets(raw)
        url = config.get("url") or (
            "https://" + hosts[0] if hosts else "https://example.com"
        )
        # -jsonl → JSON lines to stdout (parse_output reads them). Bounded so a
        # deep/slow site can't run unbounded (the per-step execution timeout is
        # the hard backstop). -d depth, -timeout per-request seconds.
        return [
            "-u", url,
            "-jsonl",
            "-silent",
            "-d", str(config.get("depth", 2)),
            "-timeout", str(config.get("timeout", 10)),
        ]

    def parse_output(self, raw_output: str) -> AgentResult:
        findings: list[dict] = []
        for line in raw_output.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = _json.loads(line)
                url = (
                    obj.get("url")
                    or (obj.get("request") or {}).get("endpoint")
                    or obj.get("endpoint")
                )
                findings.append({"type": "endpoint", "url": url or line})
            except _json.JSONDecodeError:
                if line.startswith("http"):
                    findings.append({"type": "endpoint", "url": line})
        return AgentResult(
            agent_type=self.agent_type,
            success=True,
            findings=findings,
            raw_output=raw_output,
        )
