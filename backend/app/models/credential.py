import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class UserLLMCredential(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "user_llm_credentials"

    __table_args__ = (
        UniqueConstraint("user_id", "provider", "label", name="uq_user_provider_label"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # 'anthropic' | 'openai' | 'google'
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    # 'api_key' | 'oauth_token'
    credential_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # Fernet ciphertext — never store plaintext
    encrypted_value: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(foreign_keys=[user_id])  # type: ignore[name-defined]
