import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.core.database import get_db
from app.core.security import hash_password
from app.models.audit import AuditLog
from app.models.user import Team, User, UserRole

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


class TeamResponse(BaseModel):
    id: uuid.UUID
    name: str


class CreateUserRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    role: UserRole = UserRole.MEMBER
    # Team assignment, in precedence order: an existing team_id, else a new
    # team named team_name, else the creating admin's own team.
    team_id: uuid.UUID | None = None
    team_name: str | None = Field(default=None, max_length=255)


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


@router.get("/teams", response_model=list[TeamResponse])
async def list_teams(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Teams available for assignment when creating a user (admin only)."""
    result = await db.execute(select(Team).order_by(Team.name))
    return [TeamResponse(id=t.id, name=t.name) for t in result.scalars().all()]


@router.post("/", response_model=UserResponse, status_code=201)
async def create_user(
    body: CreateUserRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Admin-driven account creation.

    Distinct from /auth/register (public self-signup, which always spins up a
    fresh team): here an admin provisions an account and assigns it to an
    existing team, a brand-new team, or — by default — their own team.
    """
    # Normalize so case-variants (Alice@ vs alice@) cannot create two accounts
    # that the (case-sensitive) unique index and login lookups treat as distinct.
    email = body.email.strip().lower()
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    # Resolve the target team. team_id (existing) wins; then team_name (new);
    # otherwise the new user joins the creating admin's team.
    if body.team_id is not None:
        team = (
            await db.execute(select(Team).where(Team.id == body.team_id))
        ).scalar_one_or_none()
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")
        team_id = team.id
    elif body.team_name and body.team_name.strip():
        team = Team(name=body.team_name.strip())
        db.add(team)
        await db.flush()
        team_id = team.id
    else:
        team_id = admin.team_id

    user = User(
        email=email,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        role=body.role.value,
        team_id=team_id,
    )
    db.add(user)
    try:
        # The pre-check above is not atomic; a concurrent insert (or a race with
        # /auth/register) can still collide on the unique email index. Translate
        # that to the same 400 rather than letting it surface as a 500.
        await db.flush()
    except IntegrityError:
        raise HTTPException(
            status_code=400, detail="Email already registered"
        ) from None

    db.add(AuditLog(
        actor_id=admin.id,
        action="user.created",
        target_entity="user",
        target_id=str(user.id),
        details_json={
            "email": user.email,
            "role": body.role.value,
            "team_id": str(team_id),
        },
    ))

    return UserResponse(
        id=user.id, email=user.email, full_name=user.full_name,
        role=user.role, is_active=user.is_active, team_id=user.team_id,
    )


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
        action="user.role_granted",
        target_entity="user",
        target_id=str(user_id),
        details_json={"new_role": body.role.value, "previous_role": old_role},
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
