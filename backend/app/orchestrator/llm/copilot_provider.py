"""GitHub Copilot provider implementation for LLMClient.

Copilot is reached in two hops:
1. Exchange the stored GitHub OAuth token (the per-user credential, obtained via
   the device flow in app/api/v1/credentials.py) for a short-lived Copilot token
   at ``https://api.github.com/copilot_internal/v2/token``.
2. Call the OpenAI-compatible chat endpoint
   ``https://api.githubcopilot.com/chat/completions`` with that Copilot token and
   the required editor headers.

Model ids are namespaced ``copilot/<model>`` throughout OSA so per-role routing
(``provider_of``) can disambiguate them from bare OpenAI/Anthropic ids; the
prefix is stripped before the request is sent to Copilot.
"""
from __future__ import annotations

import time

import httpx

from app.orchestrator.llm.base import LLMClient, ModelUnreachable, ToolCall
from app.orchestrator.model_client import Response

_COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
_COPILOT_CHAT_URL = "https://api.githubcopilot.com/chat/completions"
_COPILOT_MODELS_URL = "https://api.githubcopilot.com/models"

# Editor identity headers Copilot's backend expects from an integration.
_EDITOR_HEADERS = {
    "Editor-Version": "OSA/1.0",
    "Editor-Plugin-Version": "OSA/1.0",
    "User-Agent": "OSA/1.0",
    "Copilot-Integration-Id": "vscode-chat",
}


def strip_copilot_prefix(model_id: str) -> str:
    """``copilot/gpt-4o`` -> ``gpt-4o``; bare ids pass through unchanged."""
    return model_id[len("copilot/"):] if model_id.startswith("copilot/") else model_id


class CopilotProvider(LLMClient):
    def __init__(self, api_key: str) -> None:
        # api_key is the stored GitHub OAuth access token for this user.
        self._github_token = api_key
        self._copilot_token: str | None = None
        self._copilot_token_exp: float = 0.0

    async def _ensure_copilot_token(self) -> str:
        # Refresh a minute before expiry to avoid mid-request expiry.
        if self._copilot_token and time.time() < self._copilot_token_exp - 60:
            return self._copilot_token
        headers = {
            "Authorization": f"token {self._github_token}",
            "Accept": "application/json",
            **_EDITOR_HEADERS,
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(_COPILOT_TOKEN_URL, headers=headers)
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise ModelUnreachable(f"GitHub Copilot token endpoint unreachable: {exc!r}") from exc
        if resp.status_code >= 500:
            raise ModelUnreachable(f"GitHub Copilot token endpoint 5xx: {resp.status_code}")
        if resp.status_code != 200:
            # 401/403 → the GitHub token is invalid or the account has no Copilot.
            raise ModelUnreachable(
                f"GitHub Copilot token exchange failed ({resp.status_code}); "
                "the GitHub credential may be revoked or lack a Copilot subscription."
            )
        data = resp.json()
        token = data.get("token", "")
        if not token:
            raise ModelUnreachable("GitHub Copilot token exchange returned no token")
        self._copilot_token = token
        # expires_at is a unix timestamp; default to a 25-minute lifetime if absent.
        self._copilot_token_exp = float(data.get("expires_at") or (time.time() + 1500))
        return token

    async def list_models(self) -> list[str]:
        """Return the bare model ids Copilot currently offers this account.

        Hits Copilot's own ``/models`` catalog (the same list the editor model
        picker uses), so the UI always shows the latest available models rather
        than a hardcoded set that ages. Ids are bare (``gpt-4.1``); callers
        namespace them ``copilot/<id>`` for per-role routing.
        """
        copilot_token = await self._ensure_copilot_token()
        headers = {
            "Authorization": f"Bearer {copilot_token}",
            "Accept": "application/json",
            **_EDITOR_HEADERS,
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(_COPILOT_MODELS_URL, headers=headers)
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise ModelUnreachable(f"GitHub Copilot models endpoint unreachable: {exc!r}") from exc
        if resp.status_code >= 500:
            raise ModelUnreachable(f"GitHub Copilot models endpoint 5xx: {resp.status_code}")
        if resp.status_code != 200:
            raise ModelUnreachable(f"GitHub Copilot models list failed ({resp.status_code})")
        data = resp.json()
        # OpenAI-style {"data": [{"id": ...}]}; de-dupe, preserve order.
        seen: set[str] = set()
        out: list[str] = []
        for m in data.get("data") or []:
            mid = m.get("id")
            # Some entries expose model_picker_enabled / capabilities; keep chat
            # models only when the flag is present, else keep everything.
            if mid and mid not in seen and m.get("model_picker_enabled", True):
                seen.add(mid)
                out.append(mid)
        return out

    async def send(
        self,
        model_id: str,
        messages: list[dict],
        system: str | None = None,
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
    ) -> Response:
        copilot_token = await self._ensure_copilot_token()

        chat_messages: list[dict] = []
        if system is not None:
            chat_messages.append({"role": "system", "content": system})
        chat_messages.extend(messages)

        body: dict = {
            "model": strip_copilot_prefix(model_id),
            "messages": chat_messages,
            "max_tokens": max_tokens,
        }
        if tools:
            body["tools"] = tools

        headers = {
            "Authorization": f"Bearer {copilot_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            **_EDITOR_HEADERS,
        }

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(_COPILOT_CHAT_URL, headers=headers, json=body)
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise ModelUnreachable(f"GitHub Copilot chat endpoint unreachable: {exc!r}") from exc
        if resp.status_code >= 500:
            raise ModelUnreachable(f"GitHub Copilot chat endpoint 5xx: {resp.status_code}")
        if resp.status_code != 200:
            raise ModelUnreachable(
                f"GitHub Copilot chat request failed ({resp.status_code}): {resp.text[:200]}"
            )

        data = resp.json()
        choices = data.get("choices") or []
        message = choices[0].get("message", {}) if choices else {}
        text = message.get("content") or ""

        tool_calls: list[ToolCall] = []
        for tc in message.get("tool_calls") or []:
            import json  # noqa: PLC0415

            fn = tc.get("function", {})
            args = fn.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            tool_calls.append(ToolCall(name=fn.get("name", ""), arguments=args or {}, id=tc.get("id")))

        usage = data.get("usage") or {}
        result = Response(
            text=text,
            tokens_in=int(usage.get("prompt_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or 0),
            raw=data,
        )
        result.tool_calls = tool_calls  # type: ignore[attr-defined]
        return result
