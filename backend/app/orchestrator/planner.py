"""AI planner — uses Claude API to convert a natural-language prompt into an attack plan.

Plan v3.2.1 §1.2: AttackPlanner now consumes a ModelClient + ModelId via dependency
injection instead of constructing ``anthropic.Anthropic`` itself. BudgetGuard is
consulted by the workflow service before each call (P3), not embedded here.
"""
from __future__ import annotations

import json

from app.core.config import settings
from app.orchestrator.model_client import ModelClient
from app.orchestrator.model_selector import ModelId

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


class AttackPlanner:
    """Drafts attack plans via Claude. State limited to the injected client + model id."""

    def __init__(
        self,
        model_client: ModelClient | None = None,
        model_id: ModelId | None = None,
    ) -> None:
        self._client = model_client or ModelClient()
        self._model_id = model_id  # None falls back to settings.anthropic_default_model_anthropic_id

    async def create_plan(self, prompt: str, target: dict) -> dict:
        """Generate an attack plan dict from a natural-language operator prompt."""
        user_message = (
            f"Target environment: {json.dumps(target, indent=2)}\n\n"
            f"Operator instructions: {prompt}\n\n"
            "Generate the attack plan JSON."
        )
        model_anthropic_id = (
            self._model_id.anthropic_id
            if self._model_id is not None
            else settings.anthropic_default_model_anthropic_id
        )
        response = await self._client.send(
            model_id=model_anthropic_id,
            messages=[{"role": "user", "content": user_message}],
            system=SYSTEM_PROMPT,
        )
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
