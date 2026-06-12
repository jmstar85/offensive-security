"""Adviser role (v4.0 P2a).

Triggered by the Performer when the Execution Monitor detects:
- Same tool called ≥ `settings.adviser_trigger_same_tool` times in one chain
  (default 5), OR
- Total tool calls in one chain ≥ `settings.adviser_trigger_total_tool`
  (default 10).

The Adviser is a one-shot role that injects a loop-break message into the
calling chain (typically Pentester's). It does not iterate; it returns a
single `RoleResult` with a guidance message and lets the calling role
absorb that into its own context.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.orchestrator.roles.base import Role, RoleResult
from app.orchestrator.roles.llm_provider import resolve_role_llm_model
from app.orchestrator.roles.registry import register_role


ADVISER_SYSTEM_PROMPT = """\
You are the Adviser role of the OSA platform. You are invoked when another
role (typically Pentester) has called the same tool repeatedly or made too
many tool calls in one chain. Your job: produce a single concise message
that tells the caller (a) why it is looping and (b) what to try instead.
Keep the message under 200 tokens. You do not call other tools.
"""


@dataclass
class Adviser(Role):
    slug: str = "adviser"

    def __init__(self, llm_model: str | None = None) -> None:
        super().__init__(
            name="adviser",
            system_prompt=ADVISER_SYSTEM_PROMPT,
            llm_model=llm_model or resolve_role_llm_model(),
            tools_allowed=[],  # Adviser does not invoke tools
            max_tool_calls=0,
        )

    async def run(self, performer: Any, context: dict[str, Any]) -> RoleResult:
        """Emit a single guidance message based on the trigger reason in
        `context`. Smoke v1: returns a static message; P4 replaces with a
        real LLM call that inspects the calling chain's recent messages.
        """
        reason = context.get("trigger_reason", "loop_detected")
        message = (
            "Adviser intervention: detected "
            f"{reason}. Stop calling the same tool and either reframe the "
            "goal, switch to a different tool from your palette, or call "
            "`ask` to escalate to the operator."
        )
        return RoleResult(
            role_name=self.name,
            messages=[{"role": "assistant", "content": message}],
            finished=True,
            tool_calls=0,
        )


def should_trigger(
    same_tool_max: int,
    total_tool_calls: int,
) -> tuple[bool, str | None]:
    """Pure predicate: should the Adviser fire?

    Returns `(True, reason)` if any threshold is exceeded, else `(False, None)`.
    Used by `Performer._dispatch_tool` after each successful adapter call.
    """
    if same_tool_max >= settings.adviser_trigger_same_tool:
        return True, f"same_tool_called_{same_tool_max}_times"
    if total_tool_calls >= settings.adviser_trigger_total_tool:
        return True, f"total_tool_calls_{total_tool_calls}"
    return False, None


register_role(Adviser)
