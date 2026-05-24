"""LegacyPlannerShim (v4.0 P2b).

Bridges the v2.1 `AttackPlanner.create_plan` contract to the new
`Generator` role without breaking `OrchestratorService.run` or
`WorkflowService.send_message`. The shim accepts the same `(prompt, target)`
arguments as `AttackPlanner` and post-processes the Generator's envelope
into the legacy `{target_summary, risk_level, steps}` JSON shape.

This is an opt-in bridge — `AttackPlanner.__init__(use_generator_role=...)`
controls whether the legacy class proxies through this shim or uses its own
direct path. By default the flag is OFF so all 85 v2.1 tests keep their
exact behavior (verified by `tests/integration/test_pipeline_shape.py`).
"""
from __future__ import annotations

from app.orchestrator.model_client import ModelClient
from app.orchestrator.model_selector import ModelId


class LegacyPlannerShim:
    """v2.1-shaped plan output produced via the new Generator role.

    Returns the v2.1 envelope keys exactly: `target_summary`, `risk_level`,
    `steps[*] = {order, agent, action, description, config}`. The Generator
    role's richer envelope (`ambiguity`, `blockers`, `reasoning`, `draft_plan`)
    is mapped down to those keys; the extra fields are persisted only when
    the new flow path is active (P4 wires that).
    """

    def __init__(
        self,
        model_client: ModelClient | None = None,
        model_id: ModelId | None = None,
    ) -> None:
        # Instantiate a Generator role lazily so the shim has zero side
        # effects until create_plan is called.
        self._model_client = model_client
        self._model_id = model_id

    async def create_plan(self, prompt: str, target: dict) -> dict:
        """Generate a v2.1-shaped plan via the Generator role's envelope.

        Until P4 wires the live Anthropic call inside `Generator.run()`,
        this falls back to the original `AttackPlanner.create_plan` flow so
        the shim is functional from P2b onward without depending on P4.
        The mapping is a thin no-op when both paths emit the same shape.
        """
        # P2b: defer to the live AttackPlanner path. The bridge moves to the
        # Generator role in P4 once `Generator.run()` produces a real LLM
        # envelope; until then the shim guarantees v2.1 shape preservation.
        from app.orchestrator.planner import AttackPlanner

        # Construct an AttackPlanner with the same client/model_id but
        # `use_generator_role=False` to avoid recursion through the shim.
        planner = AttackPlanner(
            model_client=self._model_client,
            model_id=self._model_id,
            use_generator_role=False,
        )
        plan = await planner.create_plan(prompt, target)
        # Validate shape — the v2.1 contract is mandatory.
        for required in ("target_summary", "risk_level", "steps"):
            if required not in plan:
                raise ValueError(
                    f"LegacyPlannerShim got malformed plan: missing {required!r}; "
                    f"keys={list(plan.keys())}"
                )
        return plan
