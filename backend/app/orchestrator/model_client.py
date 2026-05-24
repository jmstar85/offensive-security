"""Anthropic SDK wrapper with retries.

Plan v3.2.1 §1.2 — split out from former ModelRouter god-class.

Only concerns:
- send messages
- retry 3× with exponential backoff on 5xx / connection errors
- raise ModelUnreachable on persistent failure so callers can transition state
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import anthropic

from app.core.config import settings

logger = logging.getLogger(__name__)


class ModelUnreachable(Exception):
    """Raised when the Anthropic API is persistently unavailable."""


@dataclass
class Response:
    text: str
    tokens_in: int
    tokens_out: int
    raw: Any


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, anthropic.APIStatusError):
        return 500 <= exc.status_code < 600
    return isinstance(
        exc,
        (anthropic.APIConnectionError, anthropic.APITimeoutError, TimeoutError),
    )


class ModelClient:
    """Anthropic wrapper. No business logic, no RBAC, no pricing."""

    def __init__(self, api_key: str | None = None) -> None:
        self._client = anthropic.Anthropic(api_key=api_key or settings.anthropic_api_key)
        self._max_attempts = settings.anthropic_retry_max_attempts
        self._backoff = settings.anthropic_retry_backoff_seconds

    async def send(
        self,
        model_id: str,
        messages: list[dict],
        system: str,
        max_tokens: int = 2048,
    ) -> Response:
        """Send messages; retry on 5xx / connection errors; raise ModelUnreachable on exhaustion."""
        last_exc: BaseException | None = None
        for attempt in range(self._max_attempts):
            try:
                msg = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._client.messages.create(
                        model=model_id,
                        max_tokens=max_tokens,
                        system=system,
                        messages=messages,
                    ),
                )
                text = msg.content[0].text if msg.content else ""
                usage = getattr(msg, "usage", None)
                tokens_in = getattr(usage, "input_tokens", 0) if usage else 0
                tokens_out = getattr(usage, "output_tokens", 0) if usage else 0
                return Response(
                    text=text,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    raw=msg,
                )
            except BaseException as exc:  # noqa: BLE001 — re-raise non-retryable below
                if not _is_retryable(exc):
                    raise
                last_exc = exc
                logger.warning(
                    "anthropic_retry attempt=%d/%d error=%r",
                    attempt + 1,
                    self._max_attempts,
                    exc,
                )
                if attempt + 1 < self._max_attempts:
                    delay = (
                        self._backoff[attempt]
                        if attempt < len(self._backoff)
                        else self._backoff[-1]
                    )
                    await asyncio.sleep(delay)

        raise ModelUnreachable(
            f"Anthropic API unreachable after {self._max_attempts} attempts: {last_exc!r}"
        )
