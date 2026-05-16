import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.core.database import get_db
from app.models.audit import AuditLog
from app.models.user import User

router = APIRouter()


class AuditLogResponse(BaseModel):
    id: uuid.UUID
    actor_id: uuid.UUID | None
    action: str
    target_entity: str | None
    target_id: str | None
    details_json: dict | None
    created_at: datetime


@router.get("/", response_model=list[AuditLogResponse])
async def list_audit_logs(
    session_id: uuid.UUID | None = None,
    limit: int = Query(default=100, le=500),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    query = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if session_id:
        query = query.where(AuditLog.target_id == str(session_id))
    result = await db.execute(query)
    return [
        AuditLogResponse(
            id=log.id, actor_id=log.actor_id, action=log.action,
            target_entity=log.target_entity, target_id=log.target_id,
            details_json=log.details_json, created_at=log.created_at,
        )
        for log in result.scalars().all()
    ]
