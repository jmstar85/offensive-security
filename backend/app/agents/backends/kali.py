"""KaliBackend — sibling to DockerBackend for the Kali coexistence path.

Per the consensus plan (ralplan-kali-coexistence-v1.md), KaliBackend is a
SIBLING of DockerBackend (NOT a subclass) so that hardening applied here
cannot accidentally inject into the legacy 9-adapter path (Principle 5).

PR-1 ships the skeleton; PR-2 implements start() with the B+ hardening
contract (seccomp default + cap_drop ALL + read-only rootfs + tmpfs +
network policy) and the stream_logs/stop/cleanup methods. PR-7 reconfigures
the docker client to route through docker-socket-proxy.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from app.agents.base import ExecutionBackend


class KaliBackend(ExecutionBackend):
    async def start(
        self,
        image: str,
        command: list[str],
        env: dict[str, str],
        network: str | None,
        resource_limits: dict,
    ) -> str:
        raise NotImplementedError("KaliBackend.start lands in PR-2")

    async def stream_logs(self, execution_id: str) -> AsyncGenerator[str, None]:
        raise NotImplementedError("KaliBackend.stream_logs lands in PR-2")
        yield  # pragma: no cover

    async def stop(self, execution_id: str) -> None:
        raise NotImplementedError("KaliBackend.stop lands in PR-2")

    async def cleanup(self, execution_id: str) -> None:
        raise NotImplementedError("KaliBackend.cleanup lands in PR-2")
