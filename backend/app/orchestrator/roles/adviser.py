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
from app.orchestrator.roles.llm_provider import (
    resolve_role_client,
    resolve_role_llm_model,
    resolve_role_send_model,
)
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
        """Emit a single guidance message based on the trigger reason in `context`.

        Live path (PR4b): when an LLM client is resolved, ask it for a concise
        corrective instruction grounded in the calling chain's recent activity.
        Fallback: a static guidance message (smoke / offline / Ollama unreachable).
        """
        reason = context.get("trigger_reason", "loop_detected")
        static_message = (
            "Adviser intervention: detected "
            f"{reason}. Stop calling the same tool and either reframe the "
            "goal, switch to a different tool from your palette, or call "
            "`ask` to escalate to the operator."
        )

        client = resolve_role_client(context.get("model_client"))
        if client is None:
            return RoleResult(
                role_name=self.name,
                messages=[{"role": "assistant", "content": static_message}],
                finished=True,
                tool_calls=0,
            )

        from app.orchestrator.model_client import ModelUnreachable

        recent = str(context.get("pentester_output", ""))[:1000]
        tin = tout = 0
        try:
            resp = await client.send(
                model_id=resolve_role_send_model(context.get("anthropic_model_id")),
                messages=[{
                    "role": "user",
                    "content": (
                        f"The calling role is looping ({reason}). Recent activity:\n"
                        f"{recent}\nGive ONE concise corrective instruction (<200 tokens)."
                    ),
                }],
                system=self.system_prompt,
            )
            message = (resp.text or "").strip() or static_message
            tin, tout = resp.tokens_in, resp.tokens_out
        except ModelUnreachable:
            message = static_message  # graceful fallback — the Adviser is advisory

        return RoleResult(
            role_name=self.name,
            messages=[{"role": "assistant", "content": message}],
            finished=True,
            tool_calls=0,
            usage_input_tokens=tin,
            usage_output_tokens=tout,
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
