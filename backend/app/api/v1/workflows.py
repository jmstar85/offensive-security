"""Workflow CRUD API."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.models.workflow import Workflow
from app.models.project import Project

router = APIRouter(tags=["workflows"])

_VALID_AGENTS = {
    "nmap", "nuclei", "metasploit", "pyrit",
    "application", "web", "cloud_azure", "source_code"
}


class WorkflowCreate(BaseModel):
    name: str
    description: str = ""
    dag: dict[str, Any]
    template_id: str | None = None


class WorkflowUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    dag: dict[str, Any] | None = None


def _validate_dag(dag: dict) -> None:
    """Validate DAG structure: unique IDs, valid agent types, no cycles."""
    steps = dag.get("steps", [])
    edges = dag.get("edges", [])

    ids = [s["id"] for s in steps]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="Duplicate step IDs in DAG")

    id_set = set(ids)
    for step in steps:
        if step.get("agent_type") not in _VALID_AGENTS:
            raise HTTPException(status_code=422, detail=f"Unknown agent_type: {step.get('agent_type')}")

    for edge in edges:
        if edge["source"] not in id_set or edge["target"] not in id_set:
            raise HTTPException(status_code=422, detail="Edge references unknown node")

    # Cycle detection via DFS
    graph: dict[str, list[str]] = {i: [] for i in id_set}
    for edge in edges:
        graph[edge["source"]].append(edge["target"])

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {i: WHITE for i in id_set}

    def dfs(node: str) -> None:
        color[node] = GRAY
        for neighbor in graph[node]:
            if color[neighbor] == GRAY:
                raise HTTPException(status_code=422, detail="DAG contains a cycle")
            if color[neighbor] == WHITE:
                dfs(neighbor)
        color[node] = BLACK

    for node in id_set:
        if color[node] == WHITE:
            dfs(node)


@router.get("/projects/{project_id}/workflows")
async def list_workflows(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    wf_result = await db.execute(select(Workflow).where(Workflow.project_id == project_id))
    workflows = wf_result.scalars().all()
    return {"workflows": [
        {"id": str(w.id), "name": w.name, "description": w.description,
         "dag": w.dag, "template_id": w.template_id,
         "created_at": w.created_at.isoformat() if w.created_at else None}
        for w in workflows
    ]}


@router.post("/projects/{project_id}/workflows", status_code=201)
async def create_workflow(
    project_id: uuid.UUID,
    body: WorkflowCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    _validate_dag(body.dag)
    wf = Workflow(
        project_id=project_id,
        name=body.name,
        description=body.description,
        dag=body.dag,
        template_id=body.template_id,
        created_by=current_user.id,
    )
    db.add(wf)
    await db.flush()
    await db.refresh(wf)
    return {"id": str(wf.id), "name": wf.name, "dag": wf.dag}


@router.get("/workflows/{workflow_id}")
async def get_workflow(
    workflow_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    wf = result.scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {"id": str(wf.id), "name": wf.name, "description": wf.description,
            "dag": wf.dag, "template_id": wf.template_id}


@router.patch("/workflows/{workflow_id}")
async def update_workflow(
    workflow_id: uuid.UUID,
    body: WorkflowUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    wf = result.scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if body.name is not None:
        wf.name = body.name
    if body.description is not None:
        wf.description = body.description
    if body.dag is not None:
        _validate_dag(body.dag)
        wf.dag = body.dag
    await db.flush()
    await db.refresh(wf)
    return {"id": str(wf.id), "name": wf.name, "dag": wf.dag}


@router.delete("/workflows/{workflow_id}", status_code=204)
async def delete_workflow(
    workflow_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    wf = result.scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    await db.delete(wf)
