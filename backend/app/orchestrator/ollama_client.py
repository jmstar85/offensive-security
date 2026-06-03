"""Ollama chat client — local-LLM drop-in for ModelClient.

Mirrors ``app.orchestrator.model_client.ModelClient.send`` so the existing
``AttackPlanner`` can drive a locally-hosted model (e.g. qwen3-14b) instead of
the Anthropic API. Talks to Ollama's native ``/api/chat`` endpoint with
``format="json"`` so the planner's ``json.loads`` always receives valid JSON.

Reuses the ``ModelUnreachable`` + ``Response`` types from ``model_client`` so
callers (and the OrchestratorService fresh-plan error handling) need no
changes.
"""
from __future__ import annotations

import logging
import re

import httpx

from app.core.config import settings
from app.orchestrator.model_client import ModelUnreachable, Response

logger = logging.getLogger(__name__)

# Qwen3 and similar reasoning models may emit a <think>...</think> preamble.
# format="json" usually suppresses it, but strip defensively so json.loads in
# the planner never trips on a stray reasoning block.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


class OllamaClient:
    """Async client for a local Ollama server.

    Signature-compatible with ``ModelClient.send`` (model_id, messages, system,
    max_tokens) → ``Response``. ``model_id`` falls back to
    ``settings.ollama_model`` when empty.
    """

    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        self._base = (base_url or settings.ollama_base_url).rstrip("/")
        self._default_model = model or settings.ollama_model
        # Generous timeout: a cold model load + generation can take minutes.
        self._timeout = httpx.Timeout(float(getattr(settings, "ollama_timeout_seconds", 300)))

    async def send(
        self,
        model_id: str,
        messages: list[dict],
        system: str,
        max_tokens: int = 2048,
    ) -> Response:
        payload = {
            "model": model_id or self._default_model,
            "messages": (
                ([{"role": "system", "content": system}] if system else [])
                + list(messages)
            ),
            "stream": False,
            "format": "json",
            "options": {
                # Low temperature for deterministic, parseable plan JSON.
                "temperature": float(getattr(settings, "ollama_temperature", 0.2)),
                "num_predict": max_tokens,
            },
        }
        url = f"{self._base}/api/chat"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
            raise ModelUnreachable(f"Ollama unreachable at {url}: {exc!r}") from exc
        except httpx.HTTPStatusError as exc:
            # 4xx/5xx from Ollama (e.g. unknown model) — surface as unreachable so
            # the fresh-plan lane fails the session gracefully instead of 500ing.
            raise ModelUnreachable(
                f"Ollama returned {exc.response.status_code} at {url}: "
                f"{exc.response.text[:200]!r}"
            ) from exc

        text = (data.get("message") or {}).get("content", "") or ""
        text = _THINK_RE.sub("", text).strip()
        return Response(
            text=text,
            tokens_in=int(data.get("prompt_eval_count", 0) or 0),
            tokens_out=int(data.get("eval_count", 0) or 0),
            raw=data,
        )
