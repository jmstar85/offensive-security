"""xsstrike output parser — emits ``dom_xss_probe`` findings."""
from __future__ import annotations

import json

from app.agents.base import AgentResult


def parse(raw_output: str, agent_type: str = "xsstrike") -> AgentResult:
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
            "payload": obj.get("payload", ""),
            "context": obj.get("context", ""),
        })
    return AgentResult(
        agent_type=agent_type,
        success=True,
        findings=findings,
        raw_output=raw_output,
    )
