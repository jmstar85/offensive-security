"""Single source of the interview ambiguity target (Phase 1-b), in a neutral
module so workflow_service AND ambiguity_loop both import it without a cycle."""
from __future__ import annotations

from app.core.config import settings


def interview_ambiguity_target() -> float:
    """Ambiguity ceiling the interview must reach before ready_for_review:
    the tighter autoblock target when enabled, else the legacy threshold."""
    if getattr(settings, "osa_interview_autoblock_enabled", False):
        return settings.osa_interview_autoblock_threshold
    return settings.workflow_ambiguity_threshold
