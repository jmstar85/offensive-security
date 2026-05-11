"""Agent adapter + execution backend abstractions (plugin-extensible)."""
from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field


class RiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class AgentEvent:
    event_type: str          # "log" | "status" | "finding" | "error"
    agent_type: str
    execution_id: str
    data: dict = field(default_factory=dict)


@dataclass
class AgentResult:
    agent_type: str
    success: bool
    findings: list[dict] = field(default_factory=list)
    raw_output: str = ""
    error: str | None = None


class ExecutionBackend(ABC):
    """How to run an agent: Docker, native process, or remote API."""

    @abstractmethod
    async def start(self, image: str, command: list[str], env: dict[str, str],
                    network: str | None, resource_limits: dict) -> str:
        """Start the execution. Returns execution_id (e.g. container ID)."""

    @abstractmethod
    async def stream_logs(self, execution_id: str) -> AsyncGenerator[str, None]:
        """Stream stdout/stderr lines from the running execution."""
        # This is a generator; subclasses must use `yield`
        raise NotImplementedError
        yield  # pragma: no cover

    @abstractmethod
    async def stop(self, execution_id: str) -> None:
        """Stop the execution immediately."""

    @abstractmethod
    async def cleanup(self, execution_id: str) -> None:
        """Remove/clean up after execution completes."""


class AgentAdapter(ABC):
    """What to run: agent-specific logic decoupled from execution backend."""

    agent_type: str
    docker_image: str
    risk_level: RiskLevel = RiskLevel.MEDIUM
    OPTIONS_SCHEMA: dict = {"type": "object", "properties": {}}

    def __init__(self, backend: ExecutionBackend) -> None:
        self.backend = backend

    @abstractmethod
    def get_capabilities(self) -> list[str]:
        """Return list of capability strings (e.g. ["port_scan", "service_detection"])."""

    @abstractmethod
    def build_command(self, target: dict, config: dict) -> list[str]:
        """Build the CLI command list for this agent given target/config."""

    @abstractmethod
    def parse_output(self, raw_output: str) -> AgentResult:
        """Parse raw stdout into structured AgentResult."""

    async def execute(
        self, target: dict, config: dict, execution_id_out: list[str] | None = None
    ) -> AsyncGenerator[AgentEvent, None]:
        """Run the agent and yield AgentEvents. Sets execution_id_out[0] if provided."""
        command = self.build_command(target, config)
        resource_limits = self._resource_limits()
        exec_id = await self.backend.start(
            image=self.docker_image,
            command=command,
            env=config.get("env", {}),
            network=config.get("network"),
            resource_limits=resource_limits,
        )
        if execution_id_out is not None:
            execution_id_out.append(exec_id)

        raw_lines: list[str] = []
        yield AgentEvent("status", self.agent_type, exec_id, {"status": "running"})

        try:
            async for line in self.backend.stream_logs(exec_id):
                raw_lines.append(line)
                yield AgentEvent("log", self.agent_type, exec_id, {"line": line})
        finally:
            await self.backend.cleanup(exec_id)

        raw_output = "\n".join(raw_lines)
        result = self.parse_output(raw_output)
        yield AgentEvent(
            "status", self.agent_type, exec_id,
            {"status": "completed" if result.success else "failed", "result": vars(result)},
        )

    async def stop(self, execution_id: str) -> None:
        await self.backend.stop(execution_id)

    def _resource_limits(self) -> dict:
        from app.core.config import settings
        return {
            "mem_limit": settings.container_memory_limit,
            "cpu_quota": int(settings.container_cpu_limit * 100000),
            "pids_limit": settings.container_pids_limit,
        }
