"""Workflow plan normalization and deterministic ordering utilities."""
from __future__ import annotations

from collections import deque
from typing import Any


class WorkflowPlanError(ValueError):
    """Raised when a workflow definition is not executable."""


_EXECUTABLE_AGENT_TYPES = {"nmap", "nuclei", "metasploit", "pyrit"}


def executable_agent_types() -> set[str]:
    return set(_EXECUTABLE_AGENT_TYPES)


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
