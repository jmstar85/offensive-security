"""interactsh server callback log parser — emits ``oob_callback`` findings."""
from __future__ import annotations

import json

from app.agents.base import AgentResult


def parse(raw_output: str, agent_type: str = "interactsh") -> AgentResult:
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
            "type": "oob_callback",
            "protocol": obj.get("protocol", ""),
            "correlation_id": obj.get("correlation_id", ""),
            "src_ip": obj.get("src_ip", ""),
            "timestamp": obj.get("timestamp", ""),
        })
    return AgentResult(
        agent_type=agent_type,
        success=True,
        findings=findings,
        raw_output=raw_output,
    )
