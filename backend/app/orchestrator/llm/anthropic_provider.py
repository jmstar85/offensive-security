"""Anthropic provider implementation for LLMClient (PR1.1)."""
from __future__ import annotations

import anthropic

from app.orchestrator.model_client import Response
from app.orchestrator.llm.base import LLMClient, ModelUnreachable, ToolCall


class AnthropicProvider(LLMClient):
    def __init__(self, api_key: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def send(
        self,
        model_id: str,
        messages: list[dict],
        system: str | None = None,
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
    ) -> Response:
        kwargs: dict = dict(
            model=model_id,
            max_tokens=max_tokens,
            messages=messages,
        )
        if system is not None:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools

        try:
            msg = await self._client.messages.create(**kwargs)
        except (anthropic.APIConnectionError, anthropic.APITimeoutError) as exc:
            raise ModelUnreachable(f"Anthropic unreachable: {exc!r}") from exc
        except anthropic.APIStatusError as exc:
            if 500 <= exc.status_code < 600:
                raise ModelUnreachable(f"Anthropic 5xx: {exc!r}") from exc
            raise

        text = ""
        tool_calls: list[ToolCall] = []
        for block in msg.content:
            if getattr(block, "type", None) == "text":
                text = block.text
            elif getattr(block, "type", None) == "tool_use":
                tool_calls.append(
                    ToolCall(
                        name=block.name,
                        arguments=block.input if isinstance(block.input, dict) else {},
                        id=getattr(block, "id", None),
                    )
                )

        usage = getattr(msg, "usage", None)
        tokens_in = getattr(usage, "input_tokens", 0) if usage else 0
        tokens_out = getattr(usage, "output_tokens", 0) if usage else 0

        resp = Response(text=text, tokens_in=tokens_in, tokens_out=tokens_out, raw=msg)
        resp.tool_calls = tool_calls  # type: ignore[attr-defined]
        return resp
