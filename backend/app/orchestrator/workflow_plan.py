"""Workflow plan normalization and deterministic ordering utilities."""
from __future__ import annotations

from collections import deque
from typing import Any


class WorkflowPlanError(ValueError):
    """Raised when a workflow definition is not executable."""


def executable_agent_types() -> set[str]:
    """The set of agent slugs the executor can actually run.

    Execution truth is the adapter registry (``PlanExecutor`` resolves each step's
    adapter via ``get_adapter``), NOT a hardcoded list. A stale 4-slug literal
    ({nmap,nuclei,metasploit,pyrit}) previously rejected httpx/kali_*/subfinder/
    dnsx/passive_recon — all real, runnable slugs — which made ``approve()`` drop
    the operator's reviewed interview plan (session 09484046) and blocked
    saved/template replay of those agents.
    """
    from app.agents.registry import list_agent_types  # local import: avoid cycle

    return set(list_agent_types())


def chat_draft_to_workflow_plan(draft: dict[str, Any]) -> dict[str, Any]:
    """Adapt a chat-shaped interview draft into an executable workflow plan.

    The interview Generator emits steps shaped ``{order, agent(tool-slug), action,
    description, config, tier}`` with no ``id``/``edges`` — display metadata, not a
    runnable DAG. This turns the operator's REVIEWED + tier-approved steps into the
    exact steps that run on the deterministic ``PlanExecutor`` lane instead of
    being discarded for an LLM-regenerated plan.

    Step ids are keyed off the LOOP INDEX (not the LLM-supplied ``order``, which
    may duplicate or be omitted → id collision → normalize failure → silent
    autonomous fallback). ``tier`` is intentionally dropped: ``normalize`` strips
    it and the orchestrator re-derives the authoritative registry tier and
    re-applies the approval-flag gate, so the LLM's label can never loosen
    authorization. Raises ``WorkflowPlanError`` (via ``normalize``) when any agent
    is not an executable registry slug, so the caller can fall back to the
    autonomous lane.
    """
    raw_steps = draft.get("steps") or []
    steps: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_steps, start=1):
        if not isinstance(raw, dict):
            raise WorkflowPlanError("Each draft step must be an object")
        steps.append({
            "id": f"s{index}",
            "order": raw.get("order") or index,
            "agent": raw.get("agent") or raw.get("agent_type"),
            "action": raw.get("action") or "",
            "description": raw.get("description") or "",
            "config": raw.get("config") or {},
        })
    edges = [
        {"source": steps[i]["id"], "target": steps[i + 1]["id"]}
        for i in range(len(steps) - 1)
    ]
    return normalize_workflow_plan(
        {"version": 1, "kind": "workflow", "steps": steps, "edges": edges}
    )


def normalize_workflow_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Normalize a workflow DAG into the executable plan schema.

    Catalog metadata uses ``agent_type`` while the existing executor, risk
    filter, allowlist, and LLM planner all consume ``agent``. This function is
    the boundary that converts UI/catalog payloads into runtime payloads.
    """
    if not isinstance(plan, dict):
        raise WorkflowPlanError("Workflow plan must be an object")

    raw_steps = plan.get("steps", [])
    raw_edges = plan.get("edges", [])
    if not isinstance(raw_steps, list):
        raise WorkflowPlanError("Workflow steps must be a list")
    if not isinstance(raw_edges, list):
        raise WorkflowPlanError("Workflow edges must be a list")

    allowed_agents = executable_agent_types()
    normalized_steps: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for index, raw_step in enumerate(raw_steps, start=1):
        if not isinstance(raw_step, dict):
            raise WorkflowPlanError("Each workflow step must be an object")

        step_id = str(raw_step.get("id") or "").strip()
        if not step_id:
            raise WorkflowPlanError("Each workflow step must include an id")
        if step_id in seen_ids:
            raise WorkflowPlanError(f"Duplicate step id: {step_id}")
        seen_ids.add(step_id)

        agent = raw_step.get("agent") or raw_step.get("agent_type")
        if not isinstance(agent, str) or not agent:
            raise WorkflowPlanError(f"Step {step_id} must include an agent")
        if agent not in allowed_agents:
            raise WorkflowPlanError(
                f"Agent '{agent}' is not executable yet. "
                f"Executable agents: {', '.join(sorted(allowed_agents))}"
            )

        config = raw_step.get("config") or {}
        if not isinstance(config, dict):
            raise WorkflowPlanError(f"Step {step_id} config must be an object")

        normalized_steps.append({
            "id": step_id,
            "order": raw_step.get("order") or index,
            "agent": agent,
            "action": raw_step.get("action") or f"{agent}_execute",
            "description": raw_step.get("description") or "",
            "config": config,
            "requires_approval": bool(raw_step.get("requires_approval", False)),
        })

    normalized_edges: list[dict[str, Any]] = []
    for raw_edge in raw_edges:
        if not isinstance(raw_edge, dict):
            raise WorkflowPlanError("Each workflow edge must be an object")
        source = str(raw_edge.get("source") or "").strip()
        target = str(raw_edge.get("target") or "").strip()
        if source not in seen_ids or target not in seen_ids:
            raise WorkflowPlanError("Edge references unknown node")
        normalized_edges.append({
            "source": source,
            "target": target,
            "condition": raw_edge.get("condition") or "success",
        })

    normalized = {
        "version": int(plan.get("version") or 1),
        "kind": plan.get("kind") or "workflow",
        "steps": normalized_steps,
        "edges": normalized_edges,
    }
    if isinstance(plan.get("ui"), dict):
        normalized["ui"] = plan["ui"]

    topologically_sorted_steps(normalized)
    return normalized


def topologically_sorted_steps(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Return deterministic serial execution order for a workflow plan."""
    steps = plan.get("steps", [])
    edges = plan.get("edges", [])
    if not isinstance(steps, list):
        raise WorkflowPlanError("Workflow steps must be a list")
    if not isinstance(edges, list):
        raise WorkflowPlanError("Workflow edges must be a list")

    step_by_id: dict[str, dict[str, Any]] = {}
    original_order: dict[str, int] = {}
    for index, step in enumerate(steps):
        step_id = str(step.get("id") or "").strip()
        if not step_id:
            raise WorkflowPlanError("Each workflow step must include an id")
        if step_id in step_by_id:
            raise WorkflowPlanError(f"Duplicate step id: {step_id}")
        step_by_id[step_id] = step
        original_order[step_id] = index

    adjacency: dict[str, list[str]] = {step_id: [] for step_id in step_by_id}
    indegree: dict[str, int] = {step_id: 0 for step_id in step_by_id}

    for edge in edges:
        source = str(edge.get("source") or "").strip()
        target = str(edge.get("target") or "").strip()
        if source not in step_by_id or target not in step_by_id:
            raise WorkflowPlanError("Edge references unknown node")
        adjacency[source].append(target)
        indegree[target] += 1

    ready = deque(sorted(
        [step_id for step_id, degree in indegree.items() if degree == 0],
        key=lambda step_id: original_order[step_id],
    ))
    ordered_ids: list[str] = []

    while ready:
        node = ready.popleft()
        ordered_ids.append(node)
        for neighbor in sorted(adjacency[node], key=lambda step_id: original_order[step_id]):
            indegree[neighbor] -= 1
            if indegree[neighbor] == 0:
                ready.append(neighbor)
        ready = deque(sorted(ready, key=lambda step_id: original_order[step_id]))

    if len(ordered_ids) != len(step_by_id):
        raise WorkflowPlanError("DAG contains a cycle")

    return [step_by_id[step_id] for step_id in ordered_ids]
