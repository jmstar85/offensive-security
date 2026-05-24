"""Rescope state-machine service — plan v3.2.1 §5.1 (Critic D-1 BLOCKER resolution).

Lifecycle:

    executing → paused_for_rescope          (validate_discovered_targets returns rejected)
    paused_for_rescope → executing          (decide_rescope: all pending resolved + accept set non-empty)
    paused_for_rescope → killed             (decide_rescope: all rejected, no accept)
    paused_for_rescope → executing          (timeout janitor: auto-drop rejected, safety-favoring default)

Every transition writes a ``rescope_approvals`` row and emits an audit action.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.project import Target
from app.models.session import PentestSession, RescopeApproval
from app.models.user import User
from app.observability.metrics import metrics
from app.safety.audit import AuditLogger
from app.safety.whitelist import WhitelistValidator


# ── data classes ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DiscoveredTarget:
    host: str
    tier: str
    discovered_by_step_id: str


@dataclass(frozen=True)
class RescopeValidationResult:
    accepted: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    blocked_by_wildcard: list[str] = field(default_factory=list)

    @property
    def needs_operator_decision(self) -> bool:
        return bool(self.rejected)


@dataclass(frozen=True)
class RescopeDecision:
    session_status: str
    rescope_id: uuid.UUID
    accepted_targets: list[str]
    rejected_targets: list[str]


# ── service ──────────────────────────────────────────────────────────────────


class RescopeService:
    """Manages discovered-target re-validation and operator approval flow."""

    def __init__(self, db: AsyncSession, audit: AuditLogger | None = None) -> None:
        self._db = db
        self._audit = audit or AuditLogger(db)

    # ── orchestrator entry point ────────────────────────────────────────

    async def validate_discovered_targets(
        self,
        *,
        session_id: uuid.UUID,
        targets: list[DiscoveredTarget],
    ) -> RescopeValidationResult:
        """Classify newly-discovered hosts against the project whitelist.

        Does NOT mutate state. The caller decides whether to pause the
        session via ``pause_for_rescope``.
        """
        session = await self._fetch_session(session_id)
        target = await self._fetch_project_target(session.project_id)
        validator = WhitelistValidator(target.whitelist_rules if target else {})

        accepted: list[str] = []
        rejected: list[str] = []
        blocked: list[str] = []

        for dt in targets:
            if validator.is_wildcard_blocked(dt.host):
                blocked.append(dt.host)
                continue
            ok, _ = validator.validate_host_by_tier(dt.host, dt.tier)
            if ok:
                accepted.append(dt.host)
            else:
                rejected.append(dt.host)

        return RescopeValidationResult(
            accepted=accepted,
            rejected=rejected,
            blocked_by_wildcard=blocked,
        )

    async def pause_for_rescope(
        self,
        *,
        session_id: uuid.UUID,
        discovered: list[DiscoveredTarget],
        requesting_step_id: str,
        validation: RescopeValidationResult | None = None,
    ) -> RescopeApproval:
        """Transition session to ``paused_for_rescope`` and persist an approval row.

        ``wildcard_block_regex`` matches are auto-dropped before the operator
        ever sees them (safety-favoring default).
        """
        session = await self._fetch_session(session_id)
        if session.status not in {"executing", "paused_for_rescope"}:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Cannot pause for rescope from state '{session.status}'; "
                    "session must be 'executing'"
                ),
            )

        v = validation or await self.validate_discovered_targets(
            session_id=session_id, targets=discovered,
        )

        # Auto-dropped (wildcard-blocked) hosts do NOT enter the pending row.
        if not v.rejected:
            return None  # type: ignore[return-value]

        now = datetime.now(timezone.utc)
        approval = RescopeApproval(
            pentest_session_id=session.id,
            requested_at=now,
            discovered_targets={
                "rejected": v.rejected,
                "accepted_at_classify": v.accepted,
                "blocked_by_wildcard": v.blocked_by_wildcard,
                "tier_map": {dt.host: dt.tier for dt in discovered},
            },
            requesting_step_id=requesting_step_id,
            status="pending",
        )
        self._db.add(approval)

        session.status = "paused_for_rescope"
        session.paused_for_rescope_at = now
        session.rescope_request_json = {
            "discovered_targets": v.rejected,
            "requested_at": now.isoformat(),
            "requesting_step_id": requesting_step_id,
        }
        await self._db.flush()

        # ── observability (P5) ──────────────────────────────────────────
        metrics.rescope_events_total.inc(action="paused")
        for host in v.accepted:
            metrics.active_recon_targets_total.inc(result="accepted")
            _ = host
        for host in v.rejected:
            metrics.active_recon_targets_total.inc(result="needs_rescope")
            _ = host
        for host in v.blocked_by_wildcard:
            metrics.active_recon_targets_total.inc(result="wildcard_blocked")
            _ = host
        await self._audit.log(
            action="paused_for_rescope",
            actor_id=None,
            target_entity="pentest_session",
            target_id=str(session.id),
            details={
                "rejected": v.rejected,
                "accepted_at_classify": v.accepted,
                "blocked_by_wildcard": v.blocked_by_wildcard,
                "requesting_step_id": requesting_step_id,
            },
        )
        return approval

    # ── operator decision ───────────────────────────────────────────────

    async def decide_rescope(
        self,
        *,
        session_id: uuid.UUID,
        rescope_id: uuid.UUID,
        accept: list[str],
        reject: list[str],
        user: User,
        reason: str | None = None,
    ) -> RescopeDecision:
        """Operator decides accept/reject sets for a pending rescope row."""
        approval = await self._fetch_approval(rescope_id)
        if approval.pentest_session_id != session_id:
            raise HTTPException(
                status_code=400,
                detail="rescope_id does not belong to this session",
            )
        if approval.status != "pending":
            raise HTTPException(
                status_code=409,
                detail=f"rescope already decided: status={approval.status}",
            )

        # Reject set must be exact complement of accept among the discovered set.
        discovered_set = set(approval.discovered_targets.get("rejected", []))
        provided = set(accept) | set(reject)
        if provided != discovered_set:
            missing = sorted(discovered_set - provided)
            extra = sorted(provided - discovered_set)
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "accept_reject_must_partition_discovered",
                    "missing": missing,
                    "extra": extra,
                },
            )

        approval.status = "approved" if accept else "rejected"
        approval.decided_at = datetime.now(timezone.utc)
        approval.decided_by = user.id
        approval.accepted_targets = list(accept)
        approval.rejected_targets = list(reject)
        approval.decision_reason = reason

        new_status = await self._resume_or_kill(session_id, accept)
        await self._db.flush()

        # ── observability (P5) ──────────────────────────────────────────
        metrics.rescope_events_total.inc(
            action="approved" if accept else "rejected",
        )
        await self._audit.log(
            action="rescope_approved" if accept else "rescope_rejected",
            actor_id=str(user.id),
            target_entity="pentest_session",
            target_id=str(session_id),
            details={
                "rescope_id": str(approval.id),
                "accepted": list(accept),
                "rejected": list(reject),
                "reason": reason,
                "session_status_after": new_status,
            },
        )

        return RescopeDecision(
            session_status=new_status,
            rescope_id=approval.id,
            accepted_targets=list(accept),
            rejected_targets=list(reject),
        )

    # ── timeout janitor ─────────────────────────────────────────────────

    async def expire_stale_pending(self) -> list[uuid.UUID]:
        """Auto-drop pending rescope rows older than the configured timeout.

        Safety-favoring default: time-out → the discovered set is dropped
        (not accepted). Session resumes with the original scope intact.

        Returns the list of expired rescope_approvals IDs (for the caller's
        audit log).
        """
        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=settings.rescope_decision_timeout_seconds
        )
        result = await self._db.execute(
            select(RescopeApproval).where(
                RescopeApproval.status == "pending",
                RescopeApproval.requested_at < cutoff,
            )
        )
        expired_ids: list[uuid.UUID] = []
        for row in result.scalars().all():
            row.status = "timed_out"
            row.decided_at = datetime.now(timezone.utc)
            row.accepted_targets = []
            row.rejected_targets = row.discovered_targets.get("rejected", [])
            row.decision_reason = "auto_drop_after_timeout"
            expired_ids.append(row.id)
            # Resume session with empty accept set.
            await self._resume_or_kill(row.pentest_session_id, [])
            metrics.rescope_events_total.inc(action="auto_drop")
            await self._audit.log(
                action="rescope_auto_drop",
                actor_id=None,
                target_entity="pentest_session",
                target_id=str(row.pentest_session_id),
                details={
                    "rescope_id": str(row.id),
                    "dropped": row.rejected_targets,
                    "timeout_seconds": settings.rescope_decision_timeout_seconds,
                },
            )
        await self._db.flush()
        return expired_ids

    # ── helpers ─────────────────────────────────────────────────────────

    async def _fetch_session(self, session_id: uuid.UUID) -> PentestSession:
        result = await self._db.execute(
            select(PentestSession).where(PentestSession.id == session_id)
        )
        s = result.scalar_one_or_none()
        if s is None:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
        return s

    async def _fetch_approval(self, rescope_id: uuid.UUID) -> RescopeApproval:
        result = await self._db.execute(
            select(RescopeApproval).where(RescopeApproval.id == rescope_id)
        )
        r = result.scalar_one_or_none()
        if r is None:
            raise HTTPException(status_code=404, detail=f"Rescope not found: {rescope_id}")
        return r

    async def _fetch_project_target(self, project_id: uuid.UUID) -> Target | None:
        result = await self._db.execute(
            select(Target).where(Target.project_id == project_id)
        )
        return result.scalars().first()

    async def _resume_or_kill(
        self,
        session_id: uuid.UUID,
        accepted: list[str],
    ) -> str:
        """If any remaining pending rows exist, stay paused; else resume or kill."""
        pending_count = await self._db.scalar(
            select(_count(RescopeApproval.id)).where(
                RescopeApproval.pentest_session_id == session_id,
                RescopeApproval.status == "pending",
            )
        ) or 0
        session = await self._fetch_session(session_id)

        if pending_count > 0:
            # Still other rescopes outstanding; stay paused.
            return session.status

        if accepted:
            session.status = "executing"
        else:
            # No host accepted across every decided row → kill session
            # only if there was never an accepted host. Reuse rescope_request_json
            # to convey final disposition.
            any_accepted = await self._db.scalar(
                select(_count(RescopeApproval.id)).where(
                    RescopeApproval.pentest_session_id == session_id,
                    RescopeApproval.status == "approved",
                )
            ) or 0
            if any_accepted > 0:
                session.status = "executing"
            else:
                session.status = "killed"
                session.ended_at = datetime.now(timezone.utc)

        session.rescope_request_json = None
        return session.status


# Small util to avoid pulling sqlalchemy.func at module import.
def _count(col):  # noqa: ANN001
    from sqlalchemy import func
    return func.count(col)
