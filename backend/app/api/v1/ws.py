"""WebSocket endpoint for real-time session monitoring.

v4.0 P3-spike (ADR-001): supports a `topics` query parameter for per-panel
subscription. Examples:
- `/ws/sessions/{id}` — legacy: receives all topics (Monitor page).
- `/ws/sessions/{id}?topics=terminal` — Terminal tab only.
- `/ws/sessions/{id}?topics=terminal,tasks,agents` — multi-topic (rare; one
  panel = one topic is the recommended pattern).

Backward compatibility: clients that omit `topics` see the same stream as
v2.1 (all events delivered as before, because the default publish topic is
`"session"` and the unfiltered subscription receives every topic).
"""
import asyncio
import json
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.events import event_bus
from app.core.security import decode_access_token

router = APIRouter()


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
    # Auth via query param token
    token = websocket.query_params.get("token")
    if not token or not decode_access_token(token):
        await websocket.close(code=4001)
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
