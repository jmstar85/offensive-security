"""LLMClient ABC and shared types for multi-provider support (PR1.1)."""
from __future__ import annotations

import abc
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from app.orchestrator.model_client import Response  # re-export

__all__ = ["Response", "ModelUnreachable", "ToolCall", "LLMClient", "retry_with_backoff"]

logger = logging.getLogger(__name__)


class ModelUnreachable(Exception):
    """Raised on persistent network/timeout failures; callers may retry at a higher level."""


@dataclass
class ToolCall:
    name: str
    arguments: dict
    id: str | None = None


class LLMClient(abc.ABC):
    @abc.abstractmethod
    async def send(
        self,
        model_id: str,
        messages: list[dict],
        system: str | None = None,
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
    ) -> Response:
        ...


async def retry_with_backoff(
    fn: Any,
    max_attempts: int = 3,
    base_delay: float = 0.5,
) -> Any:
    """Call awaitable fn(); retry up to max_attempts on ModelUnreachable with exponential backoff."""
    last_exc: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            return await fn()
        except ModelUnreachable as exc:
            last_exc = exc
            if attempt + 1 < max_attempts:
                delay = base_delay * (2 ** attempt)
                logger.warning("llm_retry attempt=%d/%d delay=%.1fs", attempt + 1, max_attempts, delay)
                await asyncio.sleep(delay)
    raise ModelUnreachable(f"Exhausted {max_attempts} attempts: {last_exc!r}") from last_exc
