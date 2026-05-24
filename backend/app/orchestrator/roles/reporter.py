"""Reporter role (v4.0 P2a).

Consumes the session's accumulated SubTask outputs + findings and produces
the final report. Reuses the existing `backend/app/reports/generator.py`
ReportGenerator so the report format does not diverge between the legacy
PlanExecutor path and the new Performer path.

P2a ships the role class + a smoke `run()` that returns a placeholder
RoleResult. P4 wires the actual ReportGenerator invocation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.orchestrator.roles.base import Role, RoleResult
from app.orchestrator.roles.registry import register_role


REPORTER_SYSTEM_PROMPT = """\
You are the Reporter role of the OSA platform. You are invoked once the
Performer's role loop reports `done`. Your job is to summarize the session's
findings into the report format consumed by `backend/app/reports/generator.py`.
Do not call other tools; do not perform new scans; only synthesize.
"""


@dataclass
class Reporter(Role):
    slug: str = "reporter"

    def __init__(self, llm_model: str | None = None) -> None:
        super().__init__(
            name="reporter",
            system_prompt=REPORTER_SYSTEM_PROMPT,
            llm_model=llm_model or settings.anthropic_default_model,
            tools_allowed=["done"],
            max_tool_calls=settings.limited_role_max_tool_calls,
        )

    async def run(self, performer: Any, context: dict[str, Any]) -> RoleResult:
        """Invoke `ReportGenerator.generate(...)` to produce the final Report
        row from accumulated findings + plan (v4.0 gap-fill).

        Requires the calling context to provide:
        - `performer.state.db` — AsyncSession (Performer-managed)
        - `performer.state.session_id` — PentestSession.id (UUID)
        - `context["findings"]` — list of finding dicts (from Pentester chain)
        - `context["plan"]` — plan dict (from Generator/draft_plan_json)

        When any of these are missing (unit-test isolation or smoke runs)
        the role returns a placeholder summary so callers can still observe
        the `finished=True` signal without a real DB write.
        """
        db = getattr(getattr(performer, "state", None), "db", None)
        session_id = getattr(getattr(performer, "state", None), "session_id", None)
        findings = context.get("findings")
        plan = context.get("plan")

        if db is None or session_id is None or findings is None or plan is None:
            return RoleResult(
                role_name=self.name,
                messages=[
                    {
                        "role": "assistant",
                        "content": (
                            "Reporter placeholder (no findings/plan in context; "
                            "ReportGenerator skipped)."
                        ),
                    }
                ],
                finished=True,
                tool_calls=0,
            )

        from app.reports.generator import ReportGenerator

        generator = ReportGenerator(db=db)
        report = await generator.generate(
            session_id=session_id,
            findings=findings,
            plan=plan,
        )
        return RoleResult(
            role_name=self.name,
            messages=[
                {
                    "role": "assistant",
                    "content": (
                        f"Report generated for session {session_id}: "
                        f"risk_score={report.risk_score}, "
                        f"finding_count={len(findings)}, "
                        f"report_id={report.id}"
                    ),
                }
            ],
            finished=True,
            tool_calls=0,
        )


register_role(Reporter)
