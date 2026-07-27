"""Docker-based execution backend using docker-py SDK in a ThreadPoolExecutor."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from concurrent.futures import ThreadPoolExecutor

import docker
from docker.errors import NotFound

from app.agents.base import ExecutionBackend

_thread_pool = ThreadPoolExecutor(max_workers=20, thread_name_prefix="docker-agent")


def _get_loop() -> asyncio.AbstractEventLoop:
    return asyncio.get_event_loop()


class DockerBackend(ExecutionBackend):
    def __init__(self) -> None:
        self._client = docker.from_env()

    async def start(
        self, image: str, command: list[str], env: dict[str, str],
        network: str | None, resource_limits: dict,
    ) -> str:
        loop = _get_loop()

        def _create_and_start() -> str:
            # Split create + start (instead of containers.run): on a START failure
            # (e.g. an OCI/config error) run() raises WITHOUT removing the created
            # container (remove=False), leaving a "created"-state zombie. Holding
            # the handle lets us force-remove it before re-raising.
            container = self._client.containers.create(
                image=image,
                command=command,
                environment=env,
                network=network,
                mem_limit=resource_limits.get("mem_limit", "512m"),
                cpu_quota=resource_limits.get("cpu_quota", 100000),
                pids_limit=resource_limits.get("pids_limit", 100),
                network_disabled=(network is None),
            )
            try:
                container.start()
            except Exception:
                try:
                    container.remove(force=True)
                except Exception:
                    pass
                raise
            return container.id

        return await loop.run_in_executor(_thread_pool, _create_and_start)

    async def stream_logs(self, execution_id: str) -> AsyncGenerator[str, None]:
        loop = _get_loop()
        try:
            container = await loop.run_in_executor(
                _thread_pool,
                lambda: self._client.containers.get(execution_id),
            )
        except NotFound:
            return

        # Stream in chunks from the thread pool
        log_queue: asyncio.Queue[str | None] = asyncio.Queue()

        def _stream() -> None:
            try:
                for chunk in container.logs(stream=True, follow=True):
                    line = chunk.decode("utf-8", errors="replace").rstrip()
                    if line:
                        loop.call_soon_threadsafe(log_queue.put_nowait, line)
            finally:
                loop.call_soon_threadsafe(log_queue.put_nowait, None)

        loop.run_in_executor(_thread_pool, _stream)

        while True:
            line = await log_queue.get()
            if line is None:
                break
            yield line

    async def stop(self, execution_id: str) -> None:
        loop = _get_loop()
        try:
            container = await loop.run_in_executor(
                _thread_pool,
                lambda: self._client.containers.get(execution_id),
            )
            await loop.run_in_executor(_thread_pool, lambda: container.stop(timeout=5))
        except NotFound:
            pass

    async def cleanup(self, execution_id: str) -> None:
        loop = _get_loop()
        try:
            container = await loop.run_in_executor(
                _thread_pool,
                lambda: self._client.containers.get(execution_id),
            )
            await loop.run_in_executor(_thread_pool, lambda: container.remove(force=True))
        except NotFound:
            pass


# Singleton
_docker_backend: DockerBackend | None = None


def get_docker_backend() -> DockerBackend:
    global _docker_backend
    if _docker_backend is None:
        _docker_backend = DockerBackend()
    return _docker_backend
