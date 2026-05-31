"""headless_browser probe_runner.js output parser — emits ``dom_xss_probe`` findings."""
from __future__ import annotations

import json

from app.agents.base import AgentResult


def parse(raw_output: str, agent_type: str = "headless_browser") -> AgentResult:
    findings: list[dict] = []
    for line in raw_output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        findings.append({
            "type": "dom_xss_probe",
            "url": obj.get("url", ""),
            "detected": bool(obj.get("detected", False)),
        })
    return AgentResult(
        agent_type=agent_type,
        success=True,
        findings=findings,
        raw_output=raw_output,
    )
