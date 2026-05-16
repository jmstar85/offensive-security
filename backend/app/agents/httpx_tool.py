"""httpx adapter — HTTP fingerprinting at tier=passive_low_touch.

Only safe GET-only flag set is allowed. The adapter actively rejects any
config requesting raw fuzzing or POST payloads.
"""
from __future__ import annotations

import json as _json

from app.agents.base import AgentAdapter, AgentResult, RiskLevel

_DISALLOWED_FLAGS = {"-fuzz", "-x", "-method"}


class HttpxAdapter(AgentAdapter):
    agent_type = "httpx"
    docker_image = "osa-agent-httpx:latest"
    risk_level = RiskLevel.LOW

    def get_capabilities(self) -> list[str]:
        return ["http_status", "title", "tech_detect", "tls_grab"]

    def build_command(self, target: dict, config: dict) -> list[str]:
        cmd = ["-silent", "-json", "-status-code", "-title", "-tech-detect", "-tls-grab"]
        for flag in config.get("extra_flags", []):
            if flag.lower() in _DISALLOWED_FLAGS:
                raise ValueError(f"httpx: disallowed flag {flag!r} for tier=passive_low_touch")
            cmd.append(flag)
        targets = target.get("domains", []) or []
        if not targets:
            raise ValueError("httpx: no domains supplied in target")
        for d in targets:
            cmd.extend(["-u", d])
        return cmd

    def parse_output(self, raw_output: str) -> AgentResult:
        findings: list[dict] = []
        for line in raw_output.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                findings.append(_json.loads(line))
            except _json.JSONDecodeError:
                findings.append({"line": line})
        return AgentResult(
            agent_type=self.agent_type,
            success=True,
            findings=findings,
            raw_output=raw_output,
        )
