import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.project import Project
from app.models.session import AgentExecution, PentestSession
from app.models.user import User
from app.orchestrator.workflow_plan import WorkflowPlanError, normalize_workflow_plan

router = APIRouter()


class SessionCreate(BaseModel):
    project_id: uuid.UUID
    prompt: str
    workflow_id: uuid.UUID | None = None


class SessionResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    prompt: str
    status: str
    plan_json: dict | None
    started_at: datetime | None
    ended_at: datetime | None


class ExecutionResponse(BaseModel):
    id: uuid.UUID
    agent_type: str
    status: str
    started_at: datetime | None
    ended_at: datetime | None


@router.post("/", response_model=SessionResponse, status_code=201)
async def create_session(
    body: SessionCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify project ownership
    proj = await db.execute(select(Project).where(Project.id == body.project_id))
    project = proj.scalar_one_or_none()
    if not project or project.created_by != current_user.id:
        raise HTTPException(status_code=404, detail="Project not found")

    plan_json: dict | None = None
    if body.workflow_id is not None:
        from app.models.workflow import Workflow

        wf_result = await db.execute(
            select(Workflow).where(
                Workflow.id == body.workflow_id,
                Workflow.project_id == body.project_id,
            )
        )
        workflow = wf_result.scalar_one_or_none()
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")
        try:
            plan_json = normalize_workflow_plan(workflow.dag)
        except WorkflowPlanError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    session = PentestSession(
        project_id=body.project_id,
        prompt=body.prompt,
        status="pending",
        plan_json=plan_json,
    )
    db.add(session)
    await db.flush()
    session_id = session.id

    # Commit BEFORE scheduling the background task. _run_orchestration opens a
    # fresh DB session; without this commit it races the request-teardown
    # commit and may read the row as None → silent no-op that leaves the
    # session stuck in 'pending' forever. expire_on_commit=False (see
    # core/database.py) keeps `session` usable for the response below.
    await db.commit()

    # Launch orchestration in background
    background_tasks.add_task(_run_orchestration, session_id, body.prompt, str(current_user.id))

    return SessionResponse(
        id=session.id,
        project_id=session.project_id,
        prompt=session.prompt,
        status=session.status,
        plan_json=session.plan_json,
        started_at=session.started_at,
        ended_at=session.ended_at,
    )


async def _run_orchestration(session_id: uuid.UUID, prompt: str, user_id: str):
    """Background task: runs the AI orchestrator for a session."""
    from app.core.database import async_session
    from app.orchestrator.service import OrchestratorService

    async with async_session() as db:
        try:
            svc = OrchestratorService(db)
            await svc.run(session_id, prompt, uuid.UUID(user_id))
        except Exception:
            from sqlalchemy import update
            await db.execute(
                update(PentestSession)
                .where(PentestSession.id == session_id)
                .values(status="failed")
            )
            await db.commit()
            raise


@router.get("/", response_model=list[SessionResponse])
async def list_sessions(
    project_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(PentestSession)
    if project_id:
        query = query.where(PentestSession.project_id == project_id)
    result = await db.execute(query.order_by(PentestSession.created_at.desc()))
    sessions = result.scalars().all()
    return [
        SessionResponse(
            id=s.id, project_id=s.project_id, prompt=s.prompt,
            status=s.status, plan_json=s.plan_json,
            started_at=s.started_at, ended_at=s.ended_at,
        )
        for s in sessions
    ]


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(PentestSession).where(PentestSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionResponse(
        id=session.id, project_id=session.project_id, prompt=session.prompt,
        status=session.status, plan_json=session.plan_json,
        started_at=session.started_at, ended_at=session.ended_at,
    )


@router.post("/{session_id}/kill", status_code=200)
async def kill_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.safety.kill_switch import KillSwitch
    ks = KillSwitch(db)
    stopped = await ks.stop_session(session_id, str(current_user.id))
    return {"stopped": stopped, "session_id": str(session_id)}


@router.get("/{session_id}/executions", response_model=list[ExecutionResponse])
async def get_executions(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(AgentExecution).where(AgentExecution.session_id == session_id)
    )
    return [
        ExecutionResponse(
            id=e.id, agent_type=e.agent_type, status=e.status,
            started_at=e.started_at, ended_at=e.ended_at,
        )
        for e in result.scalars().all()
    ]
