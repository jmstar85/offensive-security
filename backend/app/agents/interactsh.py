"""InteractshAdapter — OOB callback correlation adapter.

No allowlist guard — interactsh has no CLI args at the adapter level;
the sidecar IS the workload.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from app.agents.base import AgentAdapter, AgentEvent, AgentResult, RiskLevel


class InteractshAdapter(AgentAdapter):
    agent_type = "interactsh"
    docker_image = "osa-interactsh:latest"
    risk_level = RiskLevel.LOW
    tool_slug = "interactsh"

    def get_capabilities(self) -> list[str]:
        return ["oob_callback", "dns_callback", "http_callback"]

    def build_command(self, target: dict, config: dict) -> list[str]:
        return []

    def parse_output(self, raw_output: str) -> AgentResult:
        from app.agents.parsers.interactsh import parse
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
        exec_id = config.get("execution_id", "interactsh-stub-exec")
        if execution_id_out is not None:
            execution_id_out.append(exec_id)

        yield AgentEvent("status", self.agent_type, exec_id, {"status": "running"})

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
