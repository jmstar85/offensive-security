"""AI planner — uses Claude API to convert a natural-language prompt into an attack plan."""
from __future__ import annotations

import json

import anthropic

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


class AttackPlanner:
    def __init__(self) -> None:
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def create_plan(self, prompt: str, target: dict) -> dict:
        """Synchronous call to Claude API. Returns parsed attack plan dict."""
        user_message = (
            f"Target environment: {json.dumps(target, indent=2)}\n\n"
            f"Operator instructions: {prompt}\n\n"
            "Generate the attack plan JSON."
        )
        message = self._client.messages.create(
            model=settings.anthropic_model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        raw = message.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
