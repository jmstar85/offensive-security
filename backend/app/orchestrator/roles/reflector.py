"""Reflector role (v4.0 P2a).

Wraps every other role's `run()` invocation with try/except + retries. On a
transient error, retry up to `settings.reflector_max_retries` (default 3)
with exponential backoff `settings.reflector_retry_backoff_seconds` (default
[0.2, 1.0, 5.0]). On persistent failure, surface the error as a RoleResult
with `error` set so the Performer can transition the session to
`needs_human_review`.

This is a wrapper, not a free-standing role with its own LLM chain. Performer
calls `Reflector.wrap(role.run, ...)` for each role invocation.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.core.config import settings
from app.orchestrator.roles.base import Role, RoleResult
from app.orchestrator.roles.registry import register_role

logger = logging.getLogger(__name__)


REFLECTOR_SYSTEM_PROMPT = """\
You are the Reflector wrap of the OSA platform. You do not have an LLM
chain of your own — you instrument every other role's `run()` invocation
with try/except + retries (3 retries with exponential backoff). On
persistent failure, you produce a RoleResult with `error` set so the
Performer can transition the session to needs_human_review.
"""


async def wrap(
    callable_: Callable[..., Awaitable[RoleResult]],
    *args: Any,
    max_retries: int | None = None,
    backoff: list[float] | None = None,
    **kwargs: Any,
) -> RoleResult:
    """Run a coroutine with retry policy. Returns the final RoleResult.

    Used by Performer for each Role.run() call. If `callable_` raises an
    exception, retry up to `max_retries` times with exponential backoff;
    if still failing, return a RoleResult with `error` set rather than
    re-raising — the Performer decides how to surface the failure to the
    operator.
    """
    retries = max_retries if max_retries is not None else settings.reflector_max_retries
    delays = backoff if backoff is not None else settings.reflector_retry_backoff_seconds

    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return await callable_(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 — Reflector catches all by design
            last_exc = e
            if attempt >= retries:
                break
            delay = delays[min(attempt, len(delays) - 1)]
            logger.warning(
                "Reflector retry %d/%d after %.1fs (error=%s)",
                attempt + 1,
                retries,
                delay,
                e,
            )
            await asyncio.sleep(delay)

    # All retries exhausted.
    return RoleResult(
        role_name="reflector",
        messages=[],
        finished=True,
        tool_calls=0,
        error=f"{type(last_exc).__name__}: {last_exc}",
    )


@dataclass
class Reflector(Role):
    slug: str = "reflector"

    def __init__(self) -> None:
        super().__init__(
            name="reflector",
            system_prompt=REFLECTOR_SYSTEM_PROMPT,
            llm_model="",  # Reflector has no LLM chain of its own
            tools_allowed=[],
            max_tool_calls=0,
        )

    async def run(self, performer: Any, context: dict[str, Any]) -> RoleResult:
        """Reflector is invoked as a wrapper, not as a top-level role. Calling
        `run()` directly returns a no-op result; the real work is in `wrap()`.
        """
        return RoleResult(role_name=self.name, messages=[], finished=True, tool_calls=0)


register_role(Reflector)
