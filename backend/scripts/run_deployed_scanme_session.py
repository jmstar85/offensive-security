"""Deployed-stack demo: create a real autonomous pentest session against
scanme.nmap.org in the running backend (real Postgres + Ollama + host Docker), so it
shows up in the UI. Run inside the backend container:

    docker compose exec -T backend python scripts/run_deployed_scanme_session.py
"""
from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select

from app.core.database import async_session
from app.models.project import Project, Target
from app.models.report import Report
from app.models.session import AgentExecution, PentestSession
from app.models.user import Team, User, UserRole
from app.orchestrator.service import OrchestratorService


async def main() -> None:
    async with async_session() as db:
        suffix = uuid.uuid4().hex[:6]
        team = Team(name=f"scanme-demo-{suffix}")
        db.add(team)
        await db.flush()
        user = User(
            email=f"demo-{suffix}@kt.com", password_hash="x" * 60,
            full_name="Scanme Demo", role=UserRole.ADMIN, team_id=team.id,
        )
        db.add(user)
        await db.flush()
        project = Project(
            name=f"scanme demo {suffix}", client_name="nmap-sanctioned-target",
            status="active", created_by=user.id,
        )
        db.add(project)
        await db.flush()
        db.add(Target(
            project_id=project.id, ip_ranges=[], domains=["scanme.nmap.org"],
            whitelist_rules={"ip_ranges": ["45.33.32.156/32"], "domains": ["scanme.nmap.org"]},
        ))
        await db.flush()
        session = PentestSession(
            project_id=project.id,
            prompt=(
                "Authorized reconnaissance of scanme.nmap.org. Run an nmap port scan "
                "on ONLY ports 22,80 with service detection (-p 22,80 -sV --open -T4 -Pn). "
                "Emit one tool call, then done."
            ),
            status="pending",
            approval_flags={"approved_active_recon": True},  # recon approved (D4 gate)
        )
        db.add(session)
        await db.flush()
        sid = session.id
        await db.commit()
        print(f"SESSION_ID={sid}")
        print(f"PROJECT_ID={project.id}")

        print("Running the autonomous pipeline (Coordinator -> Ollama planner -> "
              "Pentester tool-use loop -> real nmap container)...")
        try:
            await OrchestratorService(db).run(sid, session.prompt, user.id)
        except Exception as exc:  # noqa: BLE001 — report, don't crash the demo
            print(f"run() raised: {exc!r}")

        s = (await db.execute(
            select(PentestSession).where(PentestSession.id == sid)
        )).scalar_one()
        print(f"STATUS={s.status}")
        print(f"UNDERSTANDING={bool(s.understanding_json)} PLAN_OF_WORK={bool(s.plan_of_work_json)}")
        execs = (await db.execute(
            select(AgentExecution).where(AgentExecution.session_id == sid)
        )).scalars().all()
        for e in execs:
            findings = (e.output_json or {}).get("findings") if isinstance(e.output_json, dict) else None
            print(f"  EXEC {e.agent_type} status={e.status} findings={findings}")
        rep = (await db.execute(
            select(Report).where(Report.session_id == sid)
        )).scalars().first()
        if rep:
            print(f"REPORT total_findings={rep.findings_json.get('total')} risk={rep.risk_score}")


if __name__ == "__main__":
    asyncio.run(main())
