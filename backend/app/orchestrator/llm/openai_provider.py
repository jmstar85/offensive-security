"""OpenAI provider implementation for LLMClient (PR1.1).

openai package is imported lazily so missing it does not break import-time.
Install with: pip install openai
"""
from __future__ import annotations

from app.orchestrator.model_client import Response
from app.orchestrator.llm.base import LLMClient, ModelUnreachable, ToolCall


class OpenAIProvider(LLMClient):
    def __init__(self, api_key: str) -> None:
        try:
            import openai  # noqa: PLC0415
            self._openai = openai
            self._client = openai.AsyncOpenAI(api_key=api_key)
        except ImportError as exc:
            raise ImportError(
                "openai package is required for OpenAIProvider. "
                "Install it with: pip install openai"
            ) from exc

    async def send(
        self,
        model_id: str,
        messages: list[dict],
        system: str | None = None,
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
    ) -> Response:
        # OpenAI requires system as a prepended message; Anthropic uses top-level kwarg.
        openai_messages: list[dict] = []
        if system is not None:
            openai_messages.append({"role": "system", "content": system})
        openai_messages.extend(messages)

        kwargs: dict = dict(
            model=model_id,
            max_tokens=max_tokens,
            messages=openai_messages,
        )
        if tools:
            # Convert Anthropic-shape tools to OpenAI function-call shape if needed.
            kwargs["tools"] = tools

        try:
            resp = await self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            openai = self._openai
            if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)):  # type: ignore[attr-defined]
                raise ModelUnreachable(f"OpenAI unreachable: {exc!r}") from exc
            if hasattr(openai, "APIStatusError") and isinstance(exc, openai.APIStatusError):  # type: ignore[attr-defined]
                if 500 <= exc.status_code < 600:
                    raise ModelUnreachable(f"OpenAI 5xx: {exc!r}") from exc
            raise

        choice = resp.choices[0] if resp.choices else None
        text = choice.message.content or "" if choice else ""

        tool_calls: list[ToolCall] = []
        if choice and choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                import json  # noqa: PLC0415
                args = tc.function.arguments
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                tool_calls.append(
                    ToolCall(name=tc.function.name, arguments=args, id=tc.id)
                )

        usage = resp.usage
        tokens_in = usage.prompt_tokens if usage else 0
        tokens_out = usage.completion_tokens if usage else 0
        model_used = resp.model

        result = Response(text=text, tokens_in=tokens_in, tokens_out=tokens_out, raw=resp)
        result.tool_calls = tool_calls  # type: ignore[attr-defined]
        return result
