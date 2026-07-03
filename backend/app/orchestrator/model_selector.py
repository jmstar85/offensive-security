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
    """Stateless catalog resolver (PR4, PM3 three-way default reconciliation).

    The catalog maps every selectable model_id to its RBAC entry:
    - ``claude-opus-4-8``  — session/engine default, non-admin selectable.
    - ``claude-sonnet-4-6`` — cheaper Anthropic model, non-admin selectable
      (also the None fallback, preserving the pre-PR4 selector default).
    - ``claude-opus-4-6``  — admin-only (existing opus-4-6 RBAC, unchanged).
    """

    def __init__(self) -> None:
        # None fallback / cheaper non-admin model (pre-PR4 default preserved).
        self._default = ModelId(
            model_id=settings.anthropic_default_model,
            anthropic_id=settings.anthropic_default_model_anthropic_id,
            is_admin_only=False,
        )
        # Session/engine default — non-admin selectable so the default is usable
        # by a non-admin session (Principle 8); NOT admin-gated.
        self._session_default = ModelId(
            model_id=settings.session_default_model,
            anthropic_id=settings.session_default_model_anthropic_id,
            is_admin_only=False,
        )
        self._admin = ModelId(
            model_id=settings.anthropic_admin_model,
            anthropic_id=settings.anthropic_admin_model_anthropic_id,
            is_admin_only=True,
        )
        self._catalog: dict[str, ModelId] = {
            self._session_default.model_id: self._session_default,
            self._default.model_id: self._default,
            self._admin.model_id: self._admin,
        }

    def resolve(self, requested_model_id: str | None, user: User) -> ModelId:
        """Validate the requested model id against the user's role.

        Raises HTTPException(403) if a non-admin requests an admin-only model
        (existing opus-4-6 semantics). Raises HTTPException(400) for unknown ids.
        """
        if requested_model_id is None:
            return self._default

        entry = self._catalog.get(requested_model_id)
        if entry is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown model_id: {requested_model_id}",
            )

        if entry.is_admin_only:
            if settings.workflow_opus_requires_admin and user.role != UserRole.ADMIN:
                raise HTTPException(
                    status_code=403,
                    detail=f"Model {entry.model_id} requires admin role",
                )
        return entry

    @property
    def default(self) -> ModelId:
        return self._default

    @property
    def session_default(self) -> ModelId:
        return self._session_default

    @property
    def admin(self) -> ModelId:
        return self._admin
