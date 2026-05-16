"""Workflow CRUD API."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.project import Project
from app.models.user import User
from app.models.workflow import Workflow
from app.orchestrator.workflow_plan import WorkflowPlanError, normalize_workflow_plan

router = APIRouter()


class WorkflowCreate(BaseModel):
    name: str
    description: str = ""
    dag: dict[str, Any]
    template_id: str | None = None


class WorkflowUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    dag: dict[str, Any] | None = None


async def _get_owned_project(
    db: AsyncSession, project_id: uuid.UUID, current_user: User
) -> Project:
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.created_by == current_user.id,
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _get_owned_workflow(
    db: AsyncSession, workflow_id: uuid.UUID, current_user: User
) -> Workflow:
    result = await db.execute(
        select(Workflow)
        .join(Project, Workflow.project_id == Project.id)
        .where(
            Workflow.id == workflow_id,
            Project.created_by == current_user.id,
        )
    )
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


def _normalize_or_422(dag: dict[str, Any]) -> dict[str, Any]:
    try:
        return normalize_workflow_plan(dag)
    except WorkflowPlanError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/projects/{project_id}/workflows")
async def list_workflows(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_project(db, project_id, current_user)
    result = await db.execute(
        select(Workflow)
        .where(Workflow.project_id == project_id)
        .order_by(Workflow.created_at.desc())
    )
    workflows = result.scalars().all()
    return {
        "workflows": [
            {
                "id": str(workflow.id),
                "name": workflow.name,
                "description": workflow.description,
                "dag": workflow.dag,
                "template_id": workflow.template_id,
                "created_at": workflow.created_at.isoformat() if workflow.created_at else None,
            }
            for workflow in workflows
        ]
    }


@router.post("/projects/{project_id}/workflows", status_code=201)
async def create_workflow(
    project_id: uuid.UUID,
    body: WorkflowCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_project(db, project_id, current_user)
    workflow = Workflow(
        project_id=project_id,
        name=body.name,
        description=body.description,
        dag=_normalize_or_422(body.dag),
        template_id=body.template_id,
        created_by=current_user.id,
    )
    db.add(workflow)
    await db.flush()
    await db.refresh(workflow)
    return {"id": str(workflow.id), "name": workflow.name, "dag": workflow.dag}


@router.get("/workflows/{workflow_id}")
async def get_workflow(
    workflow_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    workflow = await _get_owned_workflow(db, workflow_id, current_user)
    return {
        "id": str(workflow.id),
        "name": workflow.name,
        "description": workflow.description,
        "dag": workflow.dag,
        "template_id": workflow.template_id,
    }


@router.patch("/workflows/{workflow_id}")
async def update_workflow(
    workflow_id: uuid.UUID,
    body: WorkflowUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    workflow = await _get_owned_workflow(db, workflow_id, current_user)
    if body.name is not None:
        workflow.name = body.name
    if body.description is not None:
        workflow.description = body.description
    if body.dag is not None:
        workflow.dag = _normalize_or_422(body.dag)
    await db.flush()
    await db.refresh(workflow)
    return {"id": str(workflow.id), "name": workflow.name, "dag": workflow.dag}


@router.delete("/workflows/{workflow_id}", status_code=204)
async def delete_workflow(
    workflow_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    workflow = await _get_owned_workflow(db, workflow_id, current_user)
    await db.delete(workflow)
