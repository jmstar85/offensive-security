"""Audit logger — records all orchestrator and safety actions to the DB."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog


class AuditLogger:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def log(
        self,
        action: str,
        actor_id: str | None = None,
        target_entity: str | None = None,
        target_id: str | None = None,
        details: dict[str, Any] | None = None,
        ip_address: str | None = None,
    ) -> None:
        entry = AuditLog(
            actor_id=uuid.UUID(actor_id) if actor_id else None,
            action=action,
            target_entity=target_entity,
            target_id=target_id,
            details_json=details,
            ip_address=ip_address,
        )
        self._db.add(entry)
        # Flush but don't commit — caller manages transaction
        await self._db.flush()
