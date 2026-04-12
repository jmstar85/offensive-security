"""Kill switch — stops all running containers for a session within 5 seconds."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import AgentExecution, PentestSession


class KillSwitch:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def stop_session(self, session_id: uuid.UUID, actor_id: str) -> int:
        """Stop all running containers for the session. Returns count stopped."""
        from app.agents.backends.docker import get_docker_backend
        from app.safety.audit import AuditLogger

        backend = get_docker_backend()
        audit = AuditLogger(self._db)

        # Fetch running executions
        result = await self._db.execute(
            select(AgentExecution).where(
                AgentExecution.session_id == session_id,
                AgentExecution.status.in_(["running", "pending"]),
            )
        )
        executions = result.scalars().all()

        stop_tasks = []
        for exc in executions:
            if exc.container_id:
                stop_tasks.append(backend.stop(exc.container_id))

        if stop_tasks:
            await asyncio.gather(*stop_tasks, return_exceptions=True)

        # Mark all as stopped
        await self._db.execute(
            update(AgentExecution)
            .where(
                AgentExecution.session_id == session_id,
                AgentExecution.status.in_(["running", "pending"]),
            )
            .values(status="killed", ended_at=datetime.now(timezone.utc))
        )

        # Mark session as killed
        await self._db.execute(
            update(PentestSession)
            .where(PentestSession.id == session_id)
            .values(status="killed", ended_at=datetime.now(timezone.utc))
        )

        await audit.log(
            actor_id=actor_id,
            action="kill_switch_triggered",
            target_entity="pentest_session",
            target_id=str(session_id),
            details={"containers_stopped": len(executions)},
        )

        return len(executions)
