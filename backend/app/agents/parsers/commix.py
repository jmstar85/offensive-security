"""commix output parser — emits ``command_injection`` findings."""
from __future__ import annotations

import re

from app.agents.base import AgentResult

# Matches lines like: [+] Parameter 'cmd' is vulnerable. Technique: classic
_VULN_RX = re.compile(
    r"\[\+\].*[Pp]arameter\s+['\"]?(?P<param>\w+)['\"]?.*[Vv]ulnerable.*[Tt]echnique[:\s]+(?P<technique>\S+)",
)
# Fallback: [+] The 'id' parameter appears to be 'classic' injectable.
_ALT_RX = re.compile(
    r"\[\+\].*['\"](?P<param>[^'\"]+)['\"].*['\"](?P<technique>[^'\"]+)['\"].*inject",
)


def parse(raw_output: str, agent_type: str = "commix") -> AgentResult:
    findings: list[dict] = []
    url = ""
    for line in raw_output.splitlines():
        line = line.strip()
        if not line:
            continue
        # Capture target URL from commix header lines.
        url_match = re.search(r"Target URL:\s*(\S+)", line)
        if url_match:
            url = url_match.group(1)
            continue
        m = _VULN_RX.search(line) or _ALT_RX.search(line)
        if m:
            findings.append({
                "type": "command_injection",
                "url": url,
                "param": m.group("param"),
                "technique": m.group("technique").strip("."),
            })
    return AgentResult(
        agent_type=agent_type,
        success=True,
        findings=findings,
        raw_output=raw_output,
    )
