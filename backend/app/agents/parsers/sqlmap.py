"""sqlmap output parser — emits ``sql_injection`` findings.

Parses sqlmap's textual "Parameter / Type / Payload" report blocks emitted
to stdout. JSON-file parsing from ``--output-dir`` lands in v2 (F-V2-1).
"""
from __future__ import annotations

import re

from app.agents.base import AgentResult

_PARAM_RX = re.compile(
    r"Parameter:\s*(?P<param>\S+)\s*\((?P<location>GET|POST|COOKIE|HEADER)\)",
    re.IGNORECASE,
)
_TYPE_RX = re.compile(r"Type:\s*(?P<technique>[\w\- ]+)", re.IGNORECASE)
_PAYLOAD_RX = re.compile(r"Payload:\s*(?P<payload>.+)")


def parse(raw_output: str, agent_type: str = "kali_sqlmap") -> AgentResult:
    findings: list[dict] = []
    current: dict | None = None
    for line in raw_output.splitlines():
        line = line.strip()
        m = _PARAM_RX.search(line)
        if m:
            if current is not None and current.get("parameter"):
                findings.append(current)
            current = {
                "type": "sql_injection",
                "parameter": m.group("param"),
                "location": m.group("location").upper(),
                "technique": None,
                "payload": None,
                "severity": "high",
            }
            continue
        if current is None:
            continue
        mt = _TYPE_RX.search(line)
        if mt and current.get("technique") is None:
            current["technique"] = mt.group("technique").strip()
            continue
        mp = _PAYLOAD_RX.search(line)
        if mp and current.get("payload") is None:
            current["payload"] = mp.group("payload").strip()
    if current is not None and current.get("parameter"):
        findings.append(current)

    return AgentResult(
        agent_type=agent_type,
        success=True,
        findings=findings,
        raw_output=raw_output,
    )
