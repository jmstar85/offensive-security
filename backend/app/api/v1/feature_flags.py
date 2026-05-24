"""Feature flag API (v4.0 P3-main).

Single endpoint that surfaces the v4.0 flag set to the frontend so the React
app can branch between the legacy 12-page layout and the new /flow/:id shell.
The flag itself lives in `settings.osa_flow_ui_enabled` (default False); the
endpoint reads from that and never sets it — flag flips happen out-of-band
(env var or settings override).

ADR-004 scope: global flag (no per-team / per-user override in v4.0).
"""
from __future__ import annotations

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()


@router.get("/config/feature-flags")
async def get_feature_flags() -> dict[str, bool]:
    """Return the v4.0 feature-flag set. Public — no auth required so the
    frontend can fetch it before login (the login page itself reads the
    flag to decide whether to redirect to /flow/:id after success).
    """
    return {
        "osa_flow_ui_enabled": settings.osa_flow_ui_enabled,
    }
