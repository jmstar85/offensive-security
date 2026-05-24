"""nikto output parser — emits ``web_vuln`` findings from ``-Format json``.

KaliExecAdapter pins nikto to ``-Format json`` via the WhitelistShim regex
(``-Format`` validator excludes anything but the JSON formatter when this
parser is used). Raises if the output is not parseable JSON — there is no
silent text-mode fallback (Principle: mandatory parser, no slop).
"""
from __future__ import annotations

import json

from app.agents.base import AgentResult


def parse(raw_output: str, agent_type: str = "kali_nikto") -> AgentResult:
    payload = json.loads(raw_output) if raw_output.strip() else []
    scans = payload if isinstance(payload, list) else [payload]

    findings: list[dict] = []
    for scan in scans:
        if not isinstance(scan, dict):
            continue
        for v in scan.get("vulnerabilities", []) or []:
            if not isinstance(v, dict):
                continue
            findings.append({
                "type": "web_vuln",
                "id": v.get("id") or v.get("OSVDBlink"),
                "message": v.get("msg") or v.get("description"),
                "severity": "info",
            })
    return AgentResult(
        agent_type=agent_type,
        success=True,
        findings=findings,
        raw_output=raw_output,
    )
