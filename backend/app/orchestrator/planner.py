"""AI planner — uses LLM API to convert a natural-language prompt into an attack plan.

Supports three providers:
  - "copilot":   Copilot Enterprise API (free with org subscription, uses gh CLI token)
  - "anthropic": Direct Anthropic API (requires ANTHROPIC_API_KEY)
  - "github":    GitHub Models API (requires GITHUB_TOKEN — Copilot Individual/Pro)
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod

from app.core.config import settings

SYSTEM_PROMPT = """You are an AI security orchestrator for authorized penetration testing.
Given a target environment description, produce a JSON attack plan with sequential steps.

Rules:
- Only include steps that are authorized and within scope
- Prefer low-risk reconnaissance before high-risk exploitation
- Never include DoS, data destruction, or ransomware steps
- Each step must specify: agent, action, config (target-specific params)

Available agents: nmap, nuclei, metasploit, pyrit

Respond ONLY with valid JSON in this exact format:
{
  "target_summary": "brief description of what was understood",
  "risk_level": "low|medium|high",
  "steps": [
    {
      "order": 1,
      "agent": "nmap",
      "action": "port_scan",
      "description": "Scan for open ports and services",
      "config": {"flags": "-sV -sC -T4 --open"}
    }
  ]
}"""


def _parse_llm_json(raw: str) -> dict:
    """Strip markdown fences and parse JSON from LLM output."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


class _LLMBackend(ABC):
    """Thin abstraction over different LLM providers."""

    @abstractmethod
    def chat(self, system: str, user_message: str) -> str:
        """Send a chat completion and return the assistant text."""


class _AnthropicBackend(_LLMBackend):
    def __init__(self) -> None:
        import anthropic
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def chat(self, system: str, user_message: str) -> str:
        message = self._client.messages.create(
            model=settings.anthropic_model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user_message}],
        )
        return message.content[0].text


class _CopilotEnterpriseBackend(_LLMBackend):
    """Uses the Copilot Enterprise API with gh CLI OAuth token (zero-cost)."""

    def __init__(self) -> None:
        import httpx
        self._token = self._resolve_token()
        self._endpoint = settings.copilot_endpoint
        self._model = settings.copilot_model
        self._client = httpx.Client(timeout=60.0)

    @staticmethod
    def _resolve_token() -> str:
        """Get token: explicit config > gh CLI auto-detection."""
        if settings.copilot_token:
            return settings.copilot_token
        import subprocess
        try:
            result = subprocess.run(
                ["gh", "auth", "token"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        raise ValueError(
            "Copilot token not found. Either set COPILOT_TOKEN or "
            "run 'gh auth login' then 'gh auth refresh --scopes copilot'."
        )

    def chat(self, system: str, user_message: str) -> str:
        response = self._client.post(
            self._endpoint,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "Copilot-Integration-Id": "vscode-chat",
            },
            json={
                "model": self._model,
                "max_tokens": 2048,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_message},
                ],
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


class _GitHubModelsBackend(_LLMBackend):
    """Uses the OpenAI-compatible GitHub Models inference endpoint."""

    def __init__(self) -> None:
        from openai import OpenAI
        self._client = OpenAI(
            base_url=settings.github_models_endpoint,
            api_key=settings.github_token,
        )

    def chat(self, system: str, user_message: str) -> str:
        response = self._client.chat.completions.create(
            model=settings.github_model,
            max_tokens=2048,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_message},
            ],
        )
        return response.choices[0].message.content


def _create_backend() -> _LLMBackend:
    provider = settings.llm_provider.lower()
    if provider == "copilot":
        return _CopilotEnterpriseBackend()
    if provider == "github":
        if not settings.github_token:
            raise ValueError("GITHUB_TOKEN is required when llm_provider=github")
        return _GitHubModelsBackend()
    if provider == "anthropic":
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required when llm_provider=anthropic")
        return _AnthropicBackend()
    raise ValueError(f"Unknown llm_provider: {provider!r}. Use 'copilot', 'anthropic', or 'github'.")


class AttackPlanner:
    def __init__(self) -> None:
        self._backend = _create_backend()

    def create_plan(self, prompt: str, target: dict) -> dict:
        """Synchronous call to LLM API. Returns parsed attack plan dict."""
        user_message = (
            f"Target environment: {json.dumps(target, indent=2)}\n\n"
            f"Operator instructions: {prompt}\n\n"
            "Generate the attack plan JSON."
        )
        raw = self._backend.chat(SYSTEM_PROMPT, user_message)
        return _parse_llm_json(raw)
