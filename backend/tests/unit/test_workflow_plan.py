"""Workflow plan normalization and ordering tests."""
from __future__ import annotations

import pytest

from app.orchestrator.workflow_plan import (
    WorkflowPlanError,
    normalize_workflow_plan,
    topologically_sorted_steps,
)


def test_normalize_accepts_legacy_agent_type_and_persists_agent():
    plan = normalize_workflow_plan({
        "steps": [
            {"id": "scan", "agent_type": "nmap", "config": {"flags": "-sV"}},
        ],
        "edges": [],
    })

    assert plan["kind"] == "workflow"
    assert plan["steps"][0]["agent"] == "nmap"
    assert "agent_type" not in plan["steps"][0]


def test_topological_sort_respects_dependencies_and_saved_order():
    plan = normalize_workflow_plan({
        "steps": [
            {"id": "nuclei", "agent": "nuclei", "config": {}},
            {"id": "nmap", "agent": "nmap", "config": {}},
            {"id": "pyrit", "agent": "pyrit", "config": {}},
        ],
        "edges": [
            {"source": "nmap", "target": "nuclei"},
        ],
    })

    assert [step["id"] for step in topologically_sorted_steps(plan)] == [
        "nmap",
        "nuclei",
        "pyrit",
    ]


def test_topological_sort_handles_diamond_graph():
    plan = normalize_workflow_plan({
        "steps": [
            {"id": "a", "agent": "nmap", "config": {}},
            {"id": "b", "agent": "nuclei", "config": {}},
            {"id": "c", "agent": "pyrit", "config": {}},
            {"id": "d", "agent": "nmap", "config": {}},
        ],
        "edges": [
            {"source": "a", "target": "b"},
            {"source": "a", "target": "c"},
            {"source": "b", "target": "d"},
            {"source": "c", "target": "d"},
        ],
    })

    assert [step["id"] for step in topologically_sorted_steps(plan)] == ["a", "b", "c", "d"]


def test_normalize_rejects_cycles():
    with pytest.raises(WorkflowPlanError, match="cycle"):
        normalize_workflow_plan({
            "steps": [
                {"id": "a", "agent": "nmap", "config": {}},
                {"id": "b", "agent": "nuclei", "config": {}},
            ],
            "edges": [
                {"source": "a", "target": "b"},
                {"source": "b", "target": "a"},
            ],
        })


def test_normalize_rejects_non_executable_domain_agent():
    with pytest.raises(WorkflowPlanError, match="not executable"):
        normalize_workflow_plan({
            "steps": [
                {"id": "web", "agent_type": "web", "config": {}},
            ],
            "edges": [],
        })
