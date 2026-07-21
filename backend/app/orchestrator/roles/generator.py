"""Generator role (v4.0 P2a).

Decomposes a user pentest prompt into a SubTask list with ambiguity scoring.
This is the entry-point role of the Performer engine — it emits the same
envelope shape that `workflow_service.py` already uses for the ambiguity
loop, so the v3.2.1 chat flow can be re-routed through `Generator.run()`
without changing the JSON contract.

P2a ships:
- the role class + system prompt + tool palette
- a smoke `run()` returning a fixture envelope (no Anthropic call yet)

P4 wires `Generator.run()` into `AmbiguityLoop` and replaces the smoke envelope
with a real Anthropic call via `app.orchestrator.model_client`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.orchestrator.llm.credential_resolver import CredentialNotFound
from app.orchestrator.roles.base import Role, RoleResult
from app.orchestrator.roles.llm_provider import (
    context_is_bound_live,
    resolve_role_client,
    resolve_role_llm_model,
    resolve_role_send_model,
)
from app.orchestrator.roles.registry import register_role


# System prompt for the Generator. Mirrors the v3.2.1 `CHAT_SYSTEM_PROMPT` in
# workflow_service.py so the legacy `WorkflowService.send_message` and the new
# Performer-driven path return the same envelope. Update both in lockstep.
GENERATOR_SYSTEM_PROMPT = """\
You are the Generator role of the OSA platform's autonomous penetration testing engine.
Given a user's natural-language pentest prompt and the locked target scope, produce a
JSON envelope with these fields:
- ambiguity: float in [0.0, 1.0] — how unclear the request still is.
- blockers: array of strings — concrete reasons the request can't proceed yet.
- reasoning: string — your one-paragraph rationale for the proposed plan or for asking.
- draft_plan: object with `steps: [{order, agent, action, description, config, tier}]`
  enumerating the SubTasks to run if the prompt is clear enough. Empty list if not.
  Keep this a CONCISE INTERVIEW SKELETON — a downstream planner expands it into the
  full run, so do NOT enumerate every port/host/template here. Emit AT MOST 8
  high-level steps (collapse repetitive per-port / per-host / per-source work into
  ONE step) and keep each `description` to a single short line (≤ ~12 words). This
  keeps the envelope inside the response budget so it is never truncated. ALWAYS
  include each step's `config` (target / host / ip_ranges / domains) — the scope
  preview validates against it; trim only the verbose prose, never the config.
  You are given an AVAILABLE TOOLS list (prepended to the user message). Every
  step MUST be grounded in that list — this is what makes the plan executable:
    * `agent` MUST be EXACTLY one of the available tool slugs (copy it verbatim).
    * `action` MUST be EXACTLY one of THAT tool's listed actions.
    * `tier` MUST be THAT tool's listed tier.
  NEVER invent agent or action names (e.g. "recon", "scanner", "reporter",
  "banner_grab"): if a slug/action is not in the AVAILABLE TOOLS list, it does
  not exist and the step cannot run.
  Each step's `tier` is therefore EXACTLY one of these tier values:
    "passive_no_target_contact", "passive_low_touch", "active_recon",
    "mid_active", "active_exploit".
  Do NOT invent other tier names (e.g. "info_gather", "report", "scanning"). When
  unsure which tier applies, default to the most passive one that fits
  ("passive_no_target_contact").

Safety constraints:
- Use only tools listed in your `tools_allowed`.
- Respect the locked target scope (no IPs/domains outside it).
- Never propose `active_exploit` tier work without an explicit operator-supplied flag.
- If the request is ambiguous (`ambiguity > 0.35`), set `draft_plan.steps = []` and ask
  via the `ask` tool.
"""


@dataclass
class Generator(Role):
    slug: str = "generator"

    def __init__(self, llm_model: str | None = None, tools_allowed: list[str] | None = None) -> None:
        super().__init__(
            name="generator",
            system_prompt=GENERATOR_SYSTEM_PROMPT,
            llm_model=llm_model or resolve_role_llm_model(),
            tools_allowed=tools_allowed or ["ask", "done", "search_in_memory"],
            max_tool_calls=settings.limited_role_max_tool_calls,
        )

    async def run(
        self, performer: Any, context: dict[str, Any], client_factory: Any = None
    ) -> RoleResult:
        """Generator turn — produces the v3.2.1-compatible chat envelope.

        Live path (v4.0 P4 wiring, gap-fill 2/3):
        - When `context["model_client"]` is supplied, call Anthropic via
          `ModelClient.send` with `GENERATOR_SYSTEM_PROMPT` + history.
        - History is `context["history"]` (list of `{role, content}`); the
          new user turn is appended from `context["user_content"]`.
        - Optional `context["memory_hits"]` (Memorist auto-call output) is
          prepended to the user content as a `[Memory hits]` block so the
          LLM can ground its plan in the RAG output.

        Fallback path (smoke):
        - When `context["model_client"]` is absent (unit-test isolation),
          returns the v3.2.1-shaped fixture envelope. This keeps unit tests
          and offline test runs deterministic without a real API call.
        """
        user_content = str(context.get("user_content", ""))
        history = list(context.get("history") or [])
        memory_hits = list(context.get("memory_hits") or [])
        # PR6 (Improvement 3 / Blocking 2): the injected ``client_factory`` resolves
        # PER INVOCATION (fresh route() each call, no session cache) and propagates
        # CredentialNotFound. Absent it, keep the PR3 legacy path byte-identical:
        # injected model_client wins; else Ollama when osa_llm_provider="ollama";
        # else None → smoke fallback below.
        if client_factory is not None:
            client = await client_factory(self.name)
        else:
            client = resolve_role_client(context.get("model_client"))

        if client is None:
            # Fail-closed guard (PR6, Principle 7 / AC#10): on the BOUND LIVE lane
            # a missing client is an error, never a fabricated smoke envelope.
            if context_is_bound_live(performer):
                raise CredentialNotFound(
                    f"no LLM client resolved for role={self.name!r} on the bound "
                    "live lane (fail-closed: never smoke on a live run)"
                )
            # Smoke fallback — used by unit tests and any caller that has
            # not provisioned a ModelClient (e.g. local offline runs).
            envelope = {
                "ambiguity": 0.5,
                "blockers": [],
                "reasoning": "Generator fallback envelope (no model_client in context).",
                "draft_plan": {"steps": []},
            }
            return RoleResult(
                role_name=self.name,
                messages=[{"role": "assistant", "content": str(envelope)}],
                finished=False,
                tool_calls=0,
            )

        # Live path — build the prompt and call Anthropic.
        rag_prefix = ""
        if memory_hits:
            lines = [
                f"- {h.get('name', '?')}: {str(h.get('description', ''))[:160]}"
                for h in memory_hits
            ]
            rag_prefix = "[Memory hits]\n" + "\n".join(lines) + "\n\n"

        # Ground the draft plan in the REAL tool registry. AmbiguityLoop passes
        # ``context["tools_palette"]`` (registry.palette_text of the visible
        # tools). Prepending it — same mechanism as ``rag_prefix`` — makes the
        # slug/action/tier vocabulary authoritative so the LLM cannot invent
        # agent/action names (``recon``/``banner_grab``/…) that can't execute.
        tools_palette = str(context.get("tools_palette") or "").strip()
        palette_prefix = ""
        if tools_palette:
            palette_prefix = (
                "[AVAILABLE TOOLS — you MUST choose agent/action/tier ONLY from "
                "this list]\n" + tools_palette + "\n\n"
            )

        messages = list(history)
        if user_content:
            messages.append(
                {"role": "user", "content": palette_prefix + rag_prefix + user_content}
            )

        # Resolve the send model id. An explicit ``send_model_id`` override (the
        # interview lane threads the SESSION-provider-coherent model, e.g.
        # ``copilot/gpt-4.1`` for a Copilot session) wins; else Anthropic → an
        # explicit context override else the vendor default id (unchanged); Ollama
        # → the configured ollama model. The autonomous lane never sets
        # ``send_model_id`` → byte-identical to the prior behavior.
        _resolver = context.get("send_model_resolver")
        model_id = (
            context.get("send_model_id")
            or (_resolver(self.name) if _resolver else None)
            or resolve_role_send_model(context.get("anthropic_model_id"))
        )

        # Raise the response budget for the interview draft_plan. Generator is
        # interview-only (instantiated solely by AmbiguityLoop), so reading the
        # interview budget from settings here is correct; ``context`` keeps it
        # per-turn overridable. Without this, a multi-step draft overflows the
        # provider's 4096 default and truncates (session 0f9c5646).
        response = await client.send(
            model_id=model_id,
            messages=messages,
            system=self.system_prompt,
            max_tokens=int(
                context.get("interview_max_tokens") or settings.interview_max_tokens
            ),
        )

        return RoleResult(
            role_name=self.name,
            messages=[{"role": "assistant", "content": response.text}],
            finished=False,
            tool_calls=0,
            usage_input_tokens=response.tokens_in,
            usage_output_tokens=response.tokens_out,
        )


register_role(Generator)
