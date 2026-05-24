import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.core.database import get_db
from app.models.audit import AuditLog
from app.models.user import User, UserRole

router = APIRouter()


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    is_active: bool
    team_id: uuid.UUID


class RoleUpdate(BaseModel):
    role: UserRole


@router.get("/", response_model=list[UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return [
        UserResponse(
            id=u.id, email=u.email, full_name=u.full_name,
            role=u.role, is_active=u.is_active, team_id=u.team_id,
        )
        for u in result.scalars().all()
    ]


@router.patch("/{user_id}/role", response_model=UserResponse)
async def update_user_role(
    user_id: uuid.UUID,
    body: RoleUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    old_role = target.role

    # Prevent demoting the last admin
    if target.role == UserRole.ADMIN and body.role != UserRole.ADMIN:
        count = await db.execute(
            select(func.count()).select_from(User).where(
                User.role == UserRole.ADMIN, User.is_active.is_(True)
            )
        )
        if count.scalar_one() <= 1:
            raise HTTPException(
                status_code=409, detail="Cannot demote the last active admin"
            )

    target.role = body.role

    # Audit log
    db.add(AuditLog(
        actor_id=admin.id,
        action="user_role_changed",
        target_entity="user",
        target_id=str(user_id),
        details_json={"old_role": old_role, "new_role": body.role.value},
    ))

    return UserResponse(
        id=target.id, email=target.email, full_name=target.full_name,
        role=target.role, is_active=target.is_active, team_id=target.team_id,
    )


@router.delete("/{user_id}", status_code=204)
async def deactivate_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    # Prevent self-deactivation
    if user_id == admin.id:
        raise HTTPException(status_code=409, detail="Cannot deactivate yourself")

    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    # Prevent deactivating the last admin
    if target.role == UserRole.ADMIN:
        count = await db.execute(
            select(func.count()).select_from(User).where(
                User.role == UserRole.ADMIN, User.is_active.is_(True)
            )
        )
        if count.scalar_one() <= 1:
            raise HTTPException(
                status_code=409, detail="Cannot deactivate the last active admin"
            )

    target.is_active = False

    # Audit log
    db.add(AuditLog(
        actor_id=admin.id,
        action="user_deactivated",
        target_entity="user",
        target_id=str(user_id),
        details_json={"email": target.email},
    ))
