"""MitmProxyAdapter — mitmproxy/mitmdump execution adapter.

Validates args via mitm_exec_allowlist before dispatch.
Subprocess plumbing is stubbed; PR3.6/PR3.7 wire the real backend.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from app.agents.base import AgentAdapter, AgentEvent, AgentResult, RiskLevel
from app.safety.kali_allowlist import SafetyViolation
from app.safety.mitm_allowlist import ALLOWED_TOOLS, mitm_exec_allowlist


class MitmProxyAdapter(AgentAdapter):
    agent_type = "mitm_proxy"
    docker_image = "osa-mitm:latest"
    risk_level = RiskLevel.MEDIUM
    tool_slug = "mitm_proxy"

    def get_capabilities(self) -> list[str]:
        return ["proxy_intercept", "tls_inspect", "addon_run"]

    def build_command(self, target: dict, config: dict) -> list[str]:
        slug = config.get("tool_slug", self.tool_slug)
        args = list(config.get("args", []))
        allowed, reason = mitm_exec_allowlist(f"mitm_{slug}", slug, args)
        if not allowed:
            raise SafetyViolation(reason)
        binary = ALLOWED_TOOLS[slug]["binary"]
        return [binary, *args]

    def parse_output(self, raw_output: str) -> AgentResult:
        from app.agents.parsers.mitmproxy import parse
        return parse(raw_output, self.agent_type)

    async def execute(
        self,
        target: dict,
        config: dict,
        execution_id_out: list[str] | None = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        return self._execute_gen(target, config, execution_id_out)

    async def _execute_gen(
        self,
        target: dict,
        config: dict,
        execution_id_out: list[str] | None,
    ) -> AsyncGenerator[AgentEvent, None]:
        slug = config.get("tool_slug", self.tool_slug)
        args = list(config.get("args", []))

        # Safety gate fires on first event.
        allowed, reason = mitm_exec_allowlist(f"mitm_{slug}", slug, args)
        if not allowed:
            raise SafetyViolation(reason)

        exec_id = config.get("execution_id", "mitm-stub-exec")
        if execution_id_out is not None:
            execution_id_out.append(exec_id)

        yield AgentEvent("status", self.agent_type, exec_id, {"status": "running"})

        # Stub: real subprocess dispatch wired in PR3.6/PR3.7.
        raw_lines: list[str] = []
        async for line in self.backend.stream_logs(exec_id):
            raw_lines.append(line)
            yield AgentEvent("log", self.agent_type, exec_id, {"line": line})

        result = self.parse_output("\n".join(raw_lines))
        yield AgentEvent(
            "status",
            self.agent_type,
            exec_id,
            {"status": "completed" if result.success else "failed", "result": vars(result)},
        )
