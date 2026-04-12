"""WebSocket endpoint for real-time session monitoring."""
import asyncio
import json
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.events import event_bus
from app.core.security import decode_access_token

router = APIRouter()


@router.websocket("/ws/sessions/{session_id}")
async def session_ws(websocket: WebSocket, session_id: uuid.UUID):
    # Auth via query param token
    token = websocket.query_params.get("token")
    if not token or not decode_access_token(token):
        await websocket.close(code=4001)
        return

    await websocket.accept()
    queue = event_bus.subscribe(str(session_id))

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
