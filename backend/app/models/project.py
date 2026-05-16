import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Project(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    client_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    created_by_user: Mapped["User"] = relationship(back_populates="projects")
    targets: Mapped[list["Target"]] = relationship(back_populates="project", cascade="all, delete")
    sessions: Mapped[list["PentestSession"]] = relationship(
        back_populates="project", cascade="all, delete"
    )
    workflows: Mapped[list["Workflow"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class Target(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "targets"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    ip_ranges: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    domains: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    cloud_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    whitelist_rules: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    project: Mapped[Project] = relationship(back_populates="targets")
