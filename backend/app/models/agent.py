from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class AgentRegistry(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "agent_registry"

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    docker_image: Mapped[str] = mapped_column(String(500), nullable=False)
    capabilities: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(50), default="medium", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
