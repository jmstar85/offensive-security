"""Runtime tool-call delegator (v4.0 P4).

Used by Pentester (and any future v3.4 role with structured tool calls) to
dispatch one tool invocation at runtime. Two routing modes:

1. **Adapter dispatch** — the tool slug is in `list_agent_types()`. Routes
   through `Performer._dispatch_tool` which runs the v3.2.1 safety chain
   (`exploit_allowlist` + `risk_filter` after the slug + intent envelope
   validation per ADR-005). Whitelist re-validation happens at session
   start; this delegator does not re-check the target scope.

2. **Sub-role delegation** — the tool slug is a role name (e.g. `memorist`,
   `adviser`). Looks up the role class in `ROLE_REGISTRY` and runs a one-
   shot chain. Used by Pentester to call `memorist.search` mid-chain.

No per-step approval gate (v4.0 plan §4 — Full Auto). Adviser/Reflector +
tier_gating + egress_monitor + RescopeService are the brakes.
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.registry import list_agent_types
from app.orchestrator.performer import Performer
from app.orchestrator.roles.base import RoleResult
from app.orchestrator.roles.llm_provider import build_client_factory
from app.orchestrator.roles.registry import ROLE_REGISTRY, get_role

logger = logging.getLogger(__name__)

# Sub-roles that EMIT model output and therefore require a resolved LLM client.
# When one of these is launched as a sub-role, the delegator enforces that a
# client_factory could be built (Blocking 3) — via an explicit ``raise``, not an
# ``assert`` (which ``python -O`` strips), so the guarantee holds in an optimized
# production start. Non-consuming sub-roles (e.g. memorist) accept-and-ignore.
_CONSUMING_ROLE_SLUGS: frozenset[str] = frozenset({"pentester", "generator", "adviser"})


async def delegate_tool_call(
    performer: Performer,
    tool_slug: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Resolve a runtime tool call to either an adapter dispatch or a sub-role.

    Returns a dict with `{kind: "adapter"|"role", result: ...}` so the
    calling chain can persist the right MsgChain entry.
    """
    if tool_slug in list_agent_types():
        adapter_result = await performer._dispatch_tool(tool_slug, payload)
        return {"kind": "adapter", "result": adapter_result}

    if tool_slug in ROLE_REGISTRY:
        role_cls = get_role(tool_slug)
        role = role_cls()
        # PR6 (A1b / Finding 1): a sub-role invoked here shares the SAME performer
        # as the top-level chain, so it resolves per-role off the SAME session-
        # constant inputs. Build the client_factory from those inputs (never from
        # the operator-controlled ``payload``) so Adviser/Generator/Pentester route
        # correctly as sub-roles.
        role_client_inputs = performer.state.context.get("role_client_inputs")
        client_factory = (
            build_client_factory(**role_client_inputs) if role_client_inputs else None
        )
        # Blocking 3: a CONSUMING sub-role MUST have a resolvable factory. Enforce
        # with an explicit ``raise`` (NOT ``assert`` — stripped under ``python -O``)
        # so an optimized production start still fails closed instead of silently
        # reverting to the distributed-convention hole this plan eliminates.
        if tool_slug in _CONSUMING_ROLE_SLUGS and client_factory is None:
            raise RuntimeError(
                f"delegate_tool_call: consuming sub-role {tool_slug!r} requires a "
                "client_factory but performer.state.context['role_client_inputs'] is "
                "absent (Blocking 3: explicit raise, not assert)."
            )
        run_result: RoleResult = await role.run(
            performer=performer, context=payload, client_factory=client_factory
        )
        return {
            "kind": "role",
            "result": {
                "role_name": run_result.role_name,
                "finished": run_result.finished,
                "tool_calls": run_result.tool_calls,
                "error": run_result.error,
            },
        }

    return {
        "kind": "unknown",
        "result": {
            "approved": False,
            "blocked_reason": f"unknown_tool_or_role:{tool_slug}",
        },
    }
