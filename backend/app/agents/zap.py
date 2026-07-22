"""OWASP ZAP adapter — the canonical OWASP DAST scanner (baseline scan).

The baseline scan spiders the target and runs ZAP's PASSIVE rule set (no active
attack payloads), so it is tiered active_recon (it contacts the target but does
not exploit). The bounded `-m` spider minutes + the per-step execution timeout
keep it from running unbounded. Findings are parsed from the zap-baseline.py
console summary (`WARN-NEW`/`FAIL-NEW` rule lines).
"""
from __future__ import annotations

import re

from app.agents.base import (
    AgentAdapter,
    AgentResult,
    RiskLevel,
    filter_resolvable_targets,
)

# zap-baseline.py summary line, e.g.
#   WARN-NEW: Content Security Policy (CSP) Header Not Set [10038] x 3
_ZAP_LINE = re.compile(r"^(WARN|FAIL)(?:-NEW|-INPROG)?:\s*(.+?)\s*(?:\[(\d+)\])?(?:\s*x\s*(\d+))?$")
_SEVERITY = {"FAIL": "high", "WARN": "medium"}


class ZapAdapter(AgentAdapter):
    agent_type = "zap"
    docker_image = "osa-agent-zap:latest"
    risk_level = RiskLevel.MEDIUM

    def get_capabilities(self) -> list[str]:
        return ["web_vulnerability_scan", "passive_scan", "spider", "misconfiguration_detection"]

    def build_command(self, target: dict, config: dict) -> list[str]:
        raw = (target.get("domains", []) or []) + (target.get("ip_ranges", []) or [])
        hosts = filter_resolvable_targets(raw)
        url = config.get("url") or (
            "https://" + hosts[0] if hosts else "https://example.com"
        )
        # zap-baseline.py args (the image ENTRYPOINT is zap-baseline.py):
        #  -t target, -m spider-minutes (bounded), -I don't fail on warnings,
        #  -d include debug off (default). Console summary → parse_output.
        return [
            "-t", url,
            "-m", str(config.get("spider_minutes", 2)),
            "-I",
        ]

    def parse_output(self, raw_output: str) -> AgentResult:
        findings: list[dict] = []
        for line in raw_output.splitlines():
            m = _ZAP_LINE.match(line.strip())
            if not m:
                continue
            level, name, rule_id, count = m.groups()
            findings.append({
                "type": "vulnerability",
                "name": name,
                "severity": _SEVERITY.get(level, "info"),
                "rule_id": rule_id or "",
                "count": int(count) if count else 1,
                "scanner": "zap",
            })
        return AgentResult(
            agent_type=self.agent_type,
            success=True,
            findings=findings,
            raw_output=raw_output,
        )
