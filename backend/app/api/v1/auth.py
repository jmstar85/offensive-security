import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.audit import AuditLog
from app.models.user import Team, User

router = APIRouter()


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)
    # Optional for public self-signup; defaults to a personal team when omitted.
    team_name: str | None = Field(default=None, max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class MessageResponse(BaseModel):
    detail: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    team_id: uuid.UUID


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Public self-signup.

    Email is lowercased so case-variants cannot create duplicate accounts. The
    role comes from settings.default_signup_role ("admin" for now, so every new
    account has full access). team_name is optional — a personal team is created
    when it is omitted.
    """
    email = body.email.strip().lower()
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    # Derive a personal team name when none is given. Bound the slice so the
    # result stays within Team.name (String(255)) even for a max-length name,
    # and fall back to a generic label when full_name is blank after stripping.
    derived = body.full_name.strip()[:240]
    team_name = (body.team_name or "").strip() or (
        f"{derived}'s Team" if derived else "Personal Team"
    )
    team = Team(name=team_name)
    db.add(team)
    await db.flush()

    user = User(
        email=email,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        role=settings.default_signup_role,
        team_id=team.id,
    )
    db.add(user)
    await db.flush()
    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        team_id=user.team_id,
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    email = body.email.strip().lower()
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token(str(user.id))
    return TokenResponse(access_token=token)


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Self-service password reset reachable from the login page.

    No email/SMTP infrastructure exists, so the flow proves ownership by
    requiring the *current* password instead of an emailed reset token.
    Failures return a single generic 401 so the endpoint cannot be used to
    enumerate which emails are registered.
    """
    email = body.email.strip().lower()
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if (
        not user
        or not user.is_active
        or not verify_password(body.current_password, user.password_hash)
    ):
        raise HTTPException(status_code=401, detail="Invalid email or current password")

    if verify_password(body.new_password, user.password_hash):
        raise HTTPException(
            status_code=400,
            detail="New password must be different from the current password",
        )

    user.password_hash = hash_password(body.new_password)
    db.add(AuditLog(
        actor_id=user.id,
        action="user.password_reset",
        target_entity="user",
        target_id=str(user.id),
        details_json={"email": user.email, "method": "self_service"},
    ))
    await db.flush()
    return MessageResponse(detail="Password updated successfully")


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role,
        team_id=current_user.team_id,
    )
