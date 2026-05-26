"""WebSocket endpoint for real-time session monitoring.

Mount: the router is included with `prefix=settings.api_prefix` in main.py,
so the externally visible path is `/api/v1/ws/sessions/{id}`.

Auth:
  1. ?token=<JWT> must decode to a valid user_id (close 4001 on failure)
  2. The session_id must belong to a project owned by that user's team
     (close 4003 on failure) — non-admins cannot subscribe to another
     team's session even if they happen to know its UUID.

Topics (ADR-001): `?topics=terminal,tasks,agents` for per-panel subscription;
omit for the legacy unfiltered stream.
"""
import asyncio
import json
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.database import async_session
from app.core.events import event_bus
from app.core.security import decode_access_token
from app.models.project import Project
from app.models.session import PentestSession
from app.models.user import User, UserRole

router = APIRouter()


async def _authorize_session_access(
    token: str | None, session_id: uuid.UUID
) -> tuple[bool, int]:
    """Return (ok, close_code).

    close_code 4001 = bad/missing token, 4003 = forbidden (not your session),
    4004 = session not found. Done in a fresh AsyncSession so this function
    is callable from the WebSocket handler without an HTTP request scope.
    """
    if not token:
        return False, 4001
    user_id_raw = decode_access_token(token)
    if not user_id_raw:
        return False, 4001
    try:
        user_id = uuid.UUID(user_id_raw)
    except (TypeError, ValueError):
        return False, 4001

    async with async_session() as db:
        user = (
            await db.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user is None or not user.is_active:
            return False, 4001
        if user.role == UserRole.ADMIN:
            # Admins can observe any session — useful for operator triage.
            return True, 0

        sess = (
            await db.execute(
                select(PentestSession).where(PentestSession.id == session_id)
            )
        ).scalar_one_or_none()
        if sess is None:
            return False, 4004
        project = (
            await db.execute(select(Project).where(Project.id == sess.project_id))
        ).scalar_one_or_none()
        if project is None:
            return False, 4004
        # Session ownership = same team as the project that owns it.
        if project.team_id != user.team_id:
            return False, 4003
    return True, 0


def _parse_topics(raw: str | None) -> set[str] | None:
    """Parse the `topics` query param (comma-separated) into a filter set.

    Returns `None` if the param is absent or empty (legacy behavior).
    Empty entries are dropped: `topics=,terminal,` → `{"terminal"}`.
    """
    if not raw:
        return None
    parts = {t.strip() for t in raw.split(",") if t.strip()}
    return parts or None


@router.websocket("/ws/sessions/{session_id}")
async def session_ws(websocket: WebSocket, session_id: uuid.UUID):
    token = websocket.query_params.get("token")
    ok, close_code = await _authorize_session_access(token, session_id)
    if not ok:
        await websocket.close(code=close_code)
        return

    topics = _parse_topics(websocket.query_params.get("topics"))

    await websocket.accept()
    queue = event_bus.subscribe(str(session_id), topics=topics)

    try:
        # Heartbeat + event relay loop
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_text(json.dumps(event))
            except asyncio.TimeoutError:
                # Send heartbeat ping
                try:
                    await websocket.send_text(json.dumps({"type": "ping"}))
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    finally:
        event_bus.unsubscribe(str(session_id), queue)
