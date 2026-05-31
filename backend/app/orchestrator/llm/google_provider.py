"""Google Generative AI provider for LLMClient (PR1.1).

google-generativeai package is imported lazily so missing it does not break import-time.
Install with: pip install google-generativeai
"""
from __future__ import annotations

from app.orchestrator.model_client import Response
from app.orchestrator.llm.base import LLMClient, ModelUnreachable, ToolCall


class GoogleProvider(LLMClient):
    def __init__(self, api_key: str) -> None:
        try:
            import google.generativeai as genai  # noqa: PLC0415
            self._genai = genai
            genai.configure(api_key=api_key)
        except ImportError as exc:
            raise ImportError(
                "google-generativeai package is required for GoogleProvider. "
                "Install it with: pip install google-generativeai"
            ) from exc

    async def send(
        self,
        model_id: str,
        messages: list[dict],
        system: str | None = None,
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
    ) -> Response:
        genai = self._genai

        # Flatten messages to a single prompt string (basic Google Generative AI shape).
        parts: list[str] = []
        if system:
            parts.append(f"System: {system}")
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    c.get("text", "") if isinstance(c, dict) else str(c) for c in content
                )
            parts.append(f"{role.capitalize()}: {content}")
        prompt = "\n".join(parts)

        try:
            model = genai.GenerativeModel(model_id)
            resp = await model.generate_content_async(prompt)
        except Exception as exc:
            exc_type = type(exc).__name__
            if "Connection" in exc_type or "Timeout" in exc_type or "Transport" in exc_type:
                raise ModelUnreachable(f"Google API unreachable: {exc!r}") from exc
            if "ServiceUnavailable" in exc_type or "InternalServerError" in exc_type:
                raise ModelUnreachable(f"Google API 5xx: {exc!r}") from exc
            raise

        text = ""
        try:
            text = resp.text or ""
        except Exception:
            pass

        usage = getattr(resp, "usage_metadata", None)
        tokens_in = getattr(usage, "prompt_token_count", 0) if usage else 0
        tokens_out = getattr(usage, "candidates_token_count", 0) if usage else 0

        result = Response(text=text, tokens_in=tokens_in, tokens_out=tokens_out, raw=resp)
        result.tool_calls = []  # type: ignore[attr-defined]
        return result
