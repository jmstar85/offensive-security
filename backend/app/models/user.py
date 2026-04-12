import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Team(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "teams"

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    users: Mapped[list["User"]] = relationship(back_populates="team")


class User(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="member", nullable=False)
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False
    )

    team: Mapped[Team] = relationship(back_populates="users")
    projects: Mapped[list["Project"]] = relationship(back_populates="created_by_user")
