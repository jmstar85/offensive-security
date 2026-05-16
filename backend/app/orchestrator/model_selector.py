"""Resolves anthropic model_id from a request and enforces RBAC.

Plan v3.2.1 §1.2 — split out from former ModelRouter god-class.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException

from app.core.config import settings
from app.models.user import User, UserRole


@dataclass(frozen=True)
class ModelId:
    model_id: str
    anthropic_id: str
    is_admin_only: bool


class ModelSelector:
    """Stateless resolver."""

    def __init__(self) -> None:
        self._default = ModelId(
            model_id=settings.anthropic_default_model,
            anthropic_id=settings.anthropic_default_model_anthropic_id,
            is_admin_only=False,
        )
        self._admin = ModelId(
            model_id=settings.anthropic_admin_model,
            anthropic_id=settings.anthropic_admin_model_anthropic_id,
            is_admin_only=True,
        )

    def resolve(self, requested_model_id: str | None, user: User) -> ModelId:
        """Validate the requested model id against the user's role.

        Raises HTTPException(403) if a non-admin requests the admin model.
        Raises HTTPException(400) for unknown model ids.
        """
        if requested_model_id is None or requested_model_id == self._default.model_id:
            return self._default

        if requested_model_id == self._admin.model_id:
            if settings.workflow_opus_requires_admin and user.role != UserRole.ADMIN:
                raise HTTPException(
                    status_code=403,
                    detail=f"Model {self._admin.model_id} requires admin role",
                )
            return self._admin

        raise HTTPException(
            status_code=400,
            detail=f"Unknown model_id: {requested_model_id}",
        )

    @property
    def default(self) -> ModelId:
        return self._default

    @property
    def admin(self) -> ModelId:
        return self._admin
