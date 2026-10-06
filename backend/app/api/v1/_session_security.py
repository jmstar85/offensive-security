"""Shared session-security helpers (Phase 1-a): authoritative project-owner-team
authorization and response masking, used by BOTH the /pentest-sessions and the
legacy /sessions routers so every session-scoped REST reader enforces the same
boundary (no divergent copy). Generic string masking lives in
app.safety.history_masking (reused by the orchestrator persistence sites too)."""
from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole
from app.safety.conversation_scrubber import ConversationScrubber
from app.safety.history_masking import scrub_json_str, scrub_messages, scrub_payload


async def authorize_session(
    db: AsyncSession, session_id: uuid.UUID, current_user: User,
):
    """Return the session only when the caller owns it via the project's team.

    The authoritative owner is the project creator's team, NOT the session's
    cached team_id (a legacy row may leave it NULL or stale, and a poisoned cache
    must never grant access). A global ADMIN bypasses the team check. Any other
    cross-team caller gets 404 so the endpoint never discloses existence."""
    from app.models.project import Project
    from app.models.session import PentestSession

    session = await db.get(PentestSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    if current_user.role == UserRole.ADMIN:
        return session
    project = await db.get(Project, session.project_id)
    owner = await db.get(User, project.created_by) if project is not None else None
    if owner is None or owner.team_id != current_user.team_id:
        raise HTTPException(status_code=404, detail="session not found")
    return session


async def accessible_session_ids(db: AsyncSession, current_user: User):
    """Session ids the caller may read: all for a global ADMIN, else those whose
    project owner shares the caller's team. Scopes collection listings so
    enumeration never leaks another team's sessions."""
    from sqlalchemy import select

    from app.models.project import Project
    from app.models.session import PentestSession

    if current_user.role == UserRole.ADMIN:
        rows = await db.execute(select(PentestSession.id))
        return {r for (r,) in rows.all()}
    rows = await db.execute(
        select(PentestSession.id)
        .join(Project, PentestSession.project_id == Project.id)
        .join(User, Project.created_by == User.id)
        .where(User.team_id == current_user.team_id)
    )
    return {r for (r,) in rows.all()}


def scrub_model(model, session_id: uuid.UUID):
    """Deep-scrub a response model's string content (structure-preserving)."""
    scrubber = ConversationScrubber(session_id=session_id)
    data = scrub_payload(scrubber, model.model_dump())
    return type(model).model_validate(data)


# Re-export so existing api importers keep one import site.
__all__ = [
    "authorize_session",
    "accessible_session_ids",
    "scrub_model",
    "scrub_json_str",
    "scrub_messages",
]
