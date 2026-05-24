"""gobuster output parser — emits ``directory_found`` findings."""
from __future__ import annotations

import re

from app.agents.base import AgentResult

# Matches lines like:
#   /admin                (Status: 200) [Size: 1234]
#   /login.php            (Status: 302) [Size: 0] [--> /index.html]
_LINE_RX = re.compile(
    r"^(?P<path>\S+)\s+\(Status:\s*(?P<status>\d+)\)\s*\[Size:\s*(?P<size>\d+)\]"
)

# Matches DNS-mode lines:
#   Found: api.example.com
_DNS_RX = re.compile(r"^Found:\s+(?P<host>\S+)\s*$")


def parse(raw_output: str, agent_type: str = "kali_gobuster") -> AgentResult:
    findings: list[dict] = []
    for line in raw_output.splitlines():
        line = line.strip()
        if not line or line.startswith(("=", "[", "Gobuster")):
            continue
        m = _LINE_RX.match(line)
        if m:
            findings.append({
                "type": "directory_found",
                "path": m.group("path"),
                "status": int(m.group("status")),
                "size": int(m.group("size")),
                "severity": "info",
            })
            continue
        m2 = _DNS_RX.match(line)
        if m2:
            findings.append({
                "type": "dns_subdomain_found",
                "host": m2.group("host"),
                "severity": "info",
            })
    return AgentResult(
        agent_type=agent_type,
        success=True,
        findings=findings,
        raw_output=raw_output,
    )
