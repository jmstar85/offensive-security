"""mitmproxy addon output parser — emits ``proxy_request`` findings."""
from __future__ import annotations

import json

from app.agents.base import AgentResult


def parse(raw_output: str, agent_type: str = "mitm_proxy") -> AgentResult:
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
            "type": "proxy_request",
            "method": obj.get("method", ""),
            "url": obj.get("url", ""),
            "status": obj.get("status", 0),
            "flow_id": obj.get("flow_id", ""),
        })
    return AgentResult(
        agent_type=agent_type,
        success=True,
        findings=findings,
        raw_output=raw_output,
    )
