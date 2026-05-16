import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.project import Project, Target
from app.models.user import User
from app.api.deps import require_admin

router = APIRouter()


class TargetIn(BaseModel):
    ip_ranges: list[str] = []
    domains: list[str] = []
    cloud_provider: str | None = None


class ProjectCreate(BaseModel):
    name: str
    client_name: str
    description: str | None = None
    target: TargetIn


class ProjectResponse(BaseModel):
    id: uuid.UUID
    name: str
    client_name: str
    description: str | None
    status: str


class TargetResponse(BaseModel):
    id: uuid.UUID
    ip_ranges: list[str]
    domains: list[str]
    cloud_provider: str | None
    whitelist_rules: dict


@router.get("/", response_model=list[ProjectResponse])
async def list_projects(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Project).where(Project.created_by == current_user.id).order_by(Project.created_at.desc())
    )
    return [
        ProjectResponse(
            id=p.id, name=p.name, client_name=p.client_name,
            description=p.description, status=p.status,
        )
        for p in result.scalars().all()
    ]


@router.post("/", response_model=ProjectResponse, status_code=201)
async def create_project(
    body: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = Project(
        name=body.name,
        client_name=body.client_name,
        description=body.description,
        created_by=current_user.id,
    )
    db.add(project)
    await db.flush()

    whitelist_rules = {
        "ip_ranges": body.target.ip_ranges,
        "domains": body.target.domains,
    }
    target = Target(
        project_id=project.id,
        ip_ranges=body.target.ip_ranges,
        domains=body.target.domains,
        cloud_provider=body.target.cloud_provider,
        whitelist_rules=whitelist_rules,
    )
    db.add(target)
    return ProjectResponse(
        id=project.id, name=project.name, client_name=project.client_name,
        description=project.description, status=project.status,
    )


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project or project.created_by != current_user.id:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectResponse(
        id=project.id, name=project.name, client_name=project.client_name,
        description=project.description, status=project.status,
    )


@router.get("/{project_id}/targets", response_model=list[TargetResponse])
async def get_targets(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify project ownership
    proj_result = await db.execute(select(Project).where(Project.id == project_id))
    project = proj_result.scalar_one_or_none()
    if not project or project.created_by != current_user.id:
        raise HTTPException(status_code=404, detail="Project not found")

    result = await db.execute(select(Target).where(Target.project_id == project_id))
    return [
        TargetResponse(
            id=t.id, ip_ranges=t.ip_ranges, domains=t.domains,
            cloud_provider=t.cloud_provider, whitelist_rules=t.whitelist_rules,
        )
        for t in result.scalars().all()
    ]


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project or project.created_by != current_user.id:
        raise HTTPException(status_code=404, detail="Project not found")
    await db.delete(project)


# ── Admin: cross-team project visibility ──────────────────────────────────────


class AdminProjectResponse(BaseModel):
    id: uuid.UUID
    name: str
    client_name: str
    description: str | None
    status: str
    created_by: uuid.UUID


@router.get("/all/admin", response_model=list[AdminProjectResponse])
async def list_all_projects(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(select(Project).order_by(Project.created_at.desc()))
    return [
        AdminProjectResponse(
            id=p.id, name=p.name, client_name=p.client_name,
            description=p.description, status=p.status, created_by=p.created_by,
        )
        for p in result.scalars().all()
    ]
