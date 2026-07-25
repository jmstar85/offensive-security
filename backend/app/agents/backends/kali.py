"""KaliBackend — hardened sibling of DockerBackend for the Kali coexistence path.

Per the consensus plan (ralplan-kali-coexistence-v1.md), KaliBackend is a
SIBLING of DockerBackend (NOT a subclass). Hardening applied here cannot
accidentally inject into the legacy 9-adapter path (Principle 5).

Hardening contract (A1.2 of the plan, always applied per container start):
  - security_opt = ["no-new-privileges:true"]  (+ docker's implicit default seccomp)
  - cap_drop     = ["ALL"]
  - cap_add      = ⊆ KALI_ALLOWED_CAPS (frozenset() in v1 → must be [])
  - read_only    = True   (root filesystem read-only)
  - tmpfs        = {"/tmp": "size=128m,mode=1777",
                    "/work": "size=512m,mode=1777"}
  - network_disabled = (network is None)
  - mem_limit / cpu_quota / pids_limit honor resource_limits dict

PR-7 will switch self._client from docker.from_env() to
docker.DockerClient(base_url=settings.kali_docker_host, ...) so that
KaliBackend routes through docker-socket-proxy while DockerBackend keeps
its direct host-socket client.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from concurrent.futures import ThreadPoolExecutor

import docker  # type: ignore[import-untyped]
from docker.errors import NotFound  # type: ignore[import-untyped]

from app.agents.base import ExecutionBackend
from app.agents.kali_whitelist import SafetyViolation
from app.safety.kali_allowlist import KALI_ALLOWED_CAPS

# Isolated thread pool — kept separate from DockerBackend's `_thread_pool`
# so a hang on the Kali path cannot starve the legacy adapters.
_kali_thread_pool = ThreadPoolExecutor(max_workers=10, thread_name_prefix="kali-agent")

# Hardening contract constants — defined once so tests can reference them.
# NOTE: do NOT pass "seccomp=default" — docker interprets any non-"unconfined"
# seccomp value as a FILE PATH, so "default" makes the daemon try to open a file
# named "default" and the container START fails 500 ("opening seccomp profile
# (default) failed"), which broke every real hardened kali run (E2E-verified).
# Omitting the seccomp opt makes the daemon apply its built-in DEFAULT (restrictive)
# seccomp profile automatically — the intended hardening, now actually applied.
KALI_SECURITY_OPT: list[str] = ["no-new-privileges:true"]
KALI_TMPFS: dict[str, str] = {
    "/tmp": "size=128m,mode=1777",
    "/work": "size=512m,mode=1777",
}


def _get_loop() -> asyncio.AbstractEventLoop:
    return asyncio.get_event_loop()


class KaliBackend(ExecutionBackend):
    def __init__(self) -> None:
        # PR-7: KaliBackend routes through the docker-socket-proxy + image-regex
        # middleware (settings.kali_docker_host). DockerBackend keeps its
        # host-socket client unchanged (Principle 5).
        from app.core.config import settings

        # version pinned so __init__ does not perform a synchronous server
        # handshake — KaliBackend instances must be constructable in test envs
        # where the proxy isn't reachable. Real failures surface at start().
        self._client = docker.DockerClient(
            base_url=settings.kali_docker_host,
            version="1.43",
            timeout=60,
        )

    async def start(
        self,
        image: str,
        command: list[str],
        env: dict[str, str],
        network: str | None,
        resource_limits: dict,
    ) -> str:
        cap_add_req = list(resource_limits.get("cap_add", []))
        violating = set(cap_add_req) - set(KALI_ALLOWED_CAPS)
        if violating:
            raise SafetyViolation(
                f"cap_add {sorted(violating)!r} not in KALI_ALLOWED_CAPS "
                f"({set(KALI_ALLOWED_CAPS)!r}); see runbook A5.5 to extend."
            )

        loop = _get_loop()
        container = await loop.run_in_executor(
            _kali_thread_pool,
            lambda: self._client.containers.run(
                image=image,
                command=command,
                environment=env,
                network=network,
                detach=True,
                remove=False,
                mem_limit=resource_limits.get("mem_limit", "512m"),
                cpu_quota=resource_limits.get("cpu_quota", 100000),
                pids_limit=resource_limits.get("pids_limit", 100),
                network_disabled=(network is None),
                # Hardening contract — always applied.
                security_opt=list(KALI_SECURITY_OPT),
                cap_drop=["ALL"],
                cap_add=cap_add_req,
                read_only=True,
                tmpfs=dict(KALI_TMPFS),
            ),
        )
        return container.id

    async def stream_logs(self, execution_id: str) -> AsyncGenerator[str, None]:
        loop = _get_loop()
        try:
            container = await loop.run_in_executor(
                _kali_thread_pool,
                lambda: self._client.containers.get(execution_id),
            )
        except NotFound:
            return

        log_queue: asyncio.Queue[str | None] = asyncio.Queue()

        def _stream() -> None:
            try:
                for chunk in container.logs(stream=True, follow=True):
                    line = chunk.decode("utf-8", errors="replace").rstrip()
                    if line:
                        loop.call_soon_threadsafe(log_queue.put_nowait, line)
            finally:
                loop.call_soon_threadsafe(log_queue.put_nowait, None)

        loop.run_in_executor(_kali_thread_pool, _stream)

        while True:
            line = await log_queue.get()
            if line is None:
                break
            yield line

    async def stop(self, execution_id: str) -> None:
        loop = _get_loop()
        try:
            container = await loop.run_in_executor(
                _kali_thread_pool,
                lambda: self._client.containers.get(execution_id),
            )
            await loop.run_in_executor(_kali_thread_pool, lambda: container.stop(timeout=5))
        except NotFound:
            pass

    async def cleanup(self, execution_id: str) -> None:
        loop = _get_loop()
        try:
            container = await loop.run_in_executor(
                _kali_thread_pool,
                lambda: self._client.containers.get(execution_id),
            )
            await loop.run_in_executor(_kali_thread_pool, lambda: container.remove(force=True))
        except NotFound:
            pass


_kali_backend: KaliBackend | None = None


def get_kali_backend() -> KaliBackend:
    global _kali_backend
    if _kali_backend is None:
        _kali_backend = KaliBackend()
    return _kali_backend
