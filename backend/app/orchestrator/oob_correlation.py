"""OOB (Interactsh) callback correlation (PR8 / C5).

Mints the per-session OOB canary and correlates inbound Interactsh callbacks back
to the originating session via the canary HMAC, persisting an ``OOBCallback`` row
and emitting it on the ``collaborator`` topic.

Milestone-2 (documented, NOT built here): a dedicated *validator agent* that
adjudicates exploit SUCCESS — independently re-triggering the OOB interaction and
asserting the callback arrives — is out of PR8 scope. PR8 provides the correlation
substrate + evidence tagging (``app/safety/evidence.py``); it does not prove that an
exploit worked, only that a callback verifiably originated from this session.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.canary import derive_canary_hmac, verify_canary_hmac
from app.models.oob import OOBCallback


class OOBCorrelationService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    def mint_canary(self, session_id: uuid.UUID) -> str:
        """Per-session OOB canary token (HMAC-SHA256 of the session id)."""
        return derive_canary_hmac(session_id)

    async def ingest_callback(
        self,
        *,
        session_id: uuid.UUID,
        canary_token: str,
        protocol: str,
        source_ip: str | None = None,
        correlation_id: str | None = None,
        raw: dict[str, Any] | None = None,
    ) -> OOBCallback | None:
        """Verify the callback's canary against the session; on success persist an
        ``OOBCallback`` row + emit on ``collaborator``; on mismatch, audit + drop.

        Canary verification prevents cross-session collisions — a callback whose
        token does not HMAC-match this session is rejected (never correlated).
        """
        from app.core.events import event_bus
        from app.safety.audit import AuditLogger

        audit = AuditLogger(self._db)
        if not verify_canary_hmac(session_id, canary_token):
            await audit.log(
                action="oob.canary_mismatch",
                actor_id=None,
                target_entity="pentest_session",
                target_id=str(session_id),
                details={"protocol": protocol, "source_ip": source_ip},
            )
            return None

        row = OOBCallback(
            pentest_session_id=session_id,
            protocol=protocol,
            source_ip=source_ip,
            correlation_id=correlation_id,
            canary_verified=True,
            raw_json=raw or {},
        )
        self._db.add(row)
        await self._db.flush()

        await event_bus.publish(
            str(session_id),
            {
                "type": "oob_callback",
                "protocol": protocol,
                "source_ip": source_ip,
                "correlation_id": correlation_id,
                "oob_callback_id": str(row.id),
            },
            topic="collaborator",
        )
        await audit.log(
            action="oob.callback_received",
            actor_id=None,
            target_entity="pentest_session",
            target_id=str(session_id),
            details={"protocol": protocol, "correlation_id": correlation_id},
        )
        return row
