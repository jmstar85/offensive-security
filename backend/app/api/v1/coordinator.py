"""Coordinator API endpoints — understanding, plan-of-work, agent families, enrichment.

SF-CRITIC-9 access-control surface: raw_conversation topic is guarded by
`verify_raw_conversation_access`; regular /understanding and /plan-of-work
require any authenticated user with project access.
"""
from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.audit import AuditLog
from app.models.agent_family import AgentFamilyInstance
from app.models.session import PentestSession
from app.models.user import User, UserRole

router = APIRouter(prefix="/pentest-sessions", tags=["coordinator"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class UnderstandingResponse(BaseModel):
    session_id: uuid.UUID
    understanding_json: dict | None
    coordinator_revision_no: int


class PlanOfWorkResponse(BaseModel):
    session_id: uuid.UUID
    plan_of_work_json: dict | None


class AgentFamilyResponse(BaseModel):
    id: uuid.UUID
    family_kind: str
    status: str
    depth: int
    max_depth: int
    context_json: dict | None


class EnrichUnderstandingRequest(BaseModel):
    manual_signals: dict[str, Any]


class EnrichUnderstandingResponse(BaseModel):
    session_id: uuid.UUID
    coordinator_revision_no: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_admin_or_team_admin(user: User) -> None:
    if user.role not in (UserRole.ADMIN, UserRole.TEAM_ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin or team_admin access required",
        )


def verify_raw_conversation_access(user: User, accept_raw: bool) -> tuple[bool, int | None]:
    """Return (allowed, close_code). close_code is None when allowed."""
    if user.role not in (UserRole.ADMIN, UserRole.TEAM_ADMIN):
        return False, 4003
    if not accept_raw:
        return False, 4003
    return True, None


_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f]")


def sanitize_signal(value: Any) -> Any:
    """Strip control characters from string values; block dunder keys in dicts."""
    if isinstance(value, str):
        return _CONTROL_CHAR_RE.sub("", value)
    if isinstance(value, dict):
        return {
            k: sanitize_signal(v)
            for k, v in value.items()
            if not str(k).startswith("__")
        }
    if isinstance(value, list):
        return [sanitize_signal(i) for i in value]
    return value


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/{session_id}/understanding", response_model=UnderstandingResponse)
async def get_understanding(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(PentestSession).where(PentestSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="PentestSession not found")
    if session.understanding_json is None:
        raise HTTPException(status_code=404, detail="understanding_json not available")
    return UnderstandingResponse(
        session_id=session.id,
        understanding_json=session.understanding_json,
        coordinator_revision_no=session.coordinator_revision_no,
    )


@router.get("/{session_id}/plan-of-work", response_model=PlanOfWorkResponse)
async def get_plan_of_work(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(PentestSession).where(PentestSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="PentestSession not found")
    if session.plan_of_work_json is None:
        raise HTTPException(status_code=404, detail="plan_of_work_json not available")
    return PlanOfWorkResponse(
        session_id=session.id,
        plan_of_work_json=session.plan_of_work_json,
    )


@router.get("/{session_id}/agent-families", response_model=list[AgentFamilyResponse])
async def get_agent_families(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(PentestSession).where(PentestSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="PentestSession not found")
    families_result = await db.execute(
        select(AgentFamilyInstance).where(
            AgentFamilyInstance.pentest_session_id == session_id
        )
    )
    families = families_result.scalars().all()
    return [
        AgentFamilyResponse(
            id=f.id,
            family_kind=f.family_kind,
            status=f.status,
            depth=f.depth,
            max_depth=f.max_depth,
            context_json=f.context_json,
        )
        for f in families
    ]


@router.post("/{session_id}/enrich-understanding", response_model=EnrichUnderstandingResponse)
async def enrich_understanding(
    session_id: uuid.UUID,
    body: EnrichUnderstandingRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin_or_team_admin(current_user)

    result = await db.execute(
        select(PentestSession).where(PentestSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="PentestSession not found")

    understanding = session.understanding_json or {}
    raw_signals = understanding.get("raw_signals", {})
    raw_signals.update(body.manual_signals)
    understanding["raw_signals"] = raw_signals
    session.understanding_json = understanding
    session.coordinator_revision_no = (session.coordinator_revision_no or 0) + 1

    db.add(AuditLog(
        actor_id=current_user.id,
        action="coordinator.understanding_enriched",
        target_entity="pentest_sessions",
        target_id=str(session_id),
        details_json={
            "manual_signals_keys": list(body.manual_signals.keys()),
            "coordinator_revision_no": session.coordinator_revision_no,
        },
    ))
    await db.flush()

    return EnrichUnderstandingResponse(
        session_id=session.id,
        coordinator_revision_no=session.coordinator_revision_no,
    )
