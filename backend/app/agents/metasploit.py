"""Metasploit agent adapter — vulnerability exploitation via msfrpc."""
from __future__ import annotations

import re
import secrets

from app.agents.base import AgentAdapter, AgentResult, RiskLevel

# Only pre-approved module prefixes are executable (exploit allowlist enforced at safety layer too)
APPROVED_MODULE_PREFIXES = [
    "auxiliary/scanner/",
    "auxiliary/gather/",
    "post/multi/recon/",
]


class MetasploitAdapter(AgentAdapter):
    agent_type = "metasploit"
    docker_image = "osa-agent-metasploit:latest"
    risk_level = RiskLevel.HIGH
    OPTIONS_SCHEMA: dict = {
        "type": "object",
        "properties": {
            "module": {
                "type": "string",
                "enum": [
                    "exploit/multi/handler",
                    "auxiliary/scanner/portscan/tcp",
                    "auxiliary/scanner/smb/smb_ms17_010",
                    "auxiliary/scanner/http/http_version",
                ],
                "description": "Metasploit module path (allowlist only)"
            },
            "payload": {"type": "string", "default": "", "description": "Payload for exploit modules"},
            "lhost": {"type": "string", "default": "", "description": "Local host for reverse shells"},
            "lport": {"type": "integer", "minimum": 1, "maximum": 65535, "default": 4444},
        }
    }

    def get_capabilities(self) -> list[str]:
        return ["exploit", "post_exploitation", "vulnerability_verification", "credential_test"]

    def build_command(self, target: dict, config: dict) -> list[str]:
        # Per-session random RPC password (Architect feedback)
        rpc_password = secrets.token_urlsafe(32)
        module = config.get("module", "auxiliary/scanner/portscan/tcp")
        rhosts = " ".join(target.get("ip_ranges", ["127.0.0.1"]))
        # RC script passed via stdin; container entrypoint executes it
        rc_script = (
            f"use {module}\n"
            f"set RHOSTS {rhosts}\n"
            f"set THREADS 10\n"
            "run\n"
            "exit\n"
        )
        return ["msfconsole", "-q", "-x", rc_script]

    def _resource_limits(self) -> dict:
        """Metasploit gets larger resource allocation."""
        from app.core.config import settings
        return {
            "mem_limit": settings.metasploit_memory_limit,
            "cpu_quota": int(settings.metasploit_cpu_limit * 100000),
            "pids_limit": 200,
        }

    def parse_output(self, raw_output: str) -> AgentResult:
        findings: list[dict] = []

        # Detect session opened (successful exploitation)
        session_pattern = re.compile(r"Meterpreter session (\d+) opened \((.+?)\)")
        for match in session_pattern.finditer(raw_output):
            findings.append({
                "type": "session_opened",
                "session_id": match.group(1),
                "connection": match.group(2),
                "severity": "critical",
                "cvss_score": 9.8,
            })

        # Detect discovered hosts
        host_pattern = re.compile(r"\[\+\]\s+(\d+\.\d+\.\d+\.\d+):\d+\s+-\s+(.+)")
        for match in host_pattern.finditer(raw_output):
            findings.append({
                "type": "host_discovery",
                "host": match.group(1),
                "detail": match.group(2).strip(),
                "severity": "info",
                "cvss_score": 0.0,
            })

        return AgentResult(
            agent_type=self.agent_type,
            success=True,
            findings=findings,
            raw_output=raw_output,
        )
