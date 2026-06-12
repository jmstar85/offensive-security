"""Report generator — aggregates findings into a structured report with CVSS scores."""
from __future__ import annotations

import uuid
from collections import Counter

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.report import Report
from app.safety.evidence import tag_all

_SEVERITY_SCORE = {"critical": 9.0, "high": 7.0, "medium": 5.0, "low": 3.0, "info": 1.0}


class ReportGenerator:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def generate(
        self,
        session_id: uuid.UUID,
        findings: list[dict],
        plan: dict,
    ) -> Report:
        # PR8: evidence-tag every finding (provenance, not a success verdict). Done
        # at report time only — agent_execution.output_json stays byte-identical.
        findings = tag_all(findings)
        severity_counts = Counter(f.get("severity", "info") for f in findings)
        risk_score = self._calculate_risk_score(findings)
        summary = self._build_summary(findings, severity_counts, plan)

        report = Report(
            session_id=session_id,
            summary=summary,
            findings_json={
                "findings": findings,
                "severity_counts": dict(severity_counts),
                "total": len(findings),
            },
            risk_score=risk_score,
        )
        self._db.add(report)
        await self._db.flush()

        # Generate PDF asynchronously
        try:
            from app.reports.pdf import PDFGenerator
            pdf_gen = PDFGenerator()
            pdf_path = await pdf_gen.generate(report.id, summary, findings, risk_score)
            report.pdf_path = pdf_path
        except Exception:
            pass  # PDF failure is non-fatal

        return report

    def _calculate_risk_score(self, findings: list[dict]) -> float:
        if not findings:
            return 0.0
        scores = [_SEVERITY_SCORE.get(f.get("severity", "info"), 1.0) for f in findings]
        return round(max(scores), 1)

    def _build_summary(
        self, findings: list[dict], severity_counts: Counter, plan: dict
    ) -> str:
        total = len(findings)
        if total == 0:
            return "No vulnerabilities or findings detected during this assessment."
        critical = severity_counts.get("critical", 0)
        high = severity_counts.get("high", 0)
        medium = severity_counts.get("medium", 0)
        return (
            f"Penetration test completed. Found {total} findings: "
            f"{critical} critical, {high} high, {medium} medium. "
            f"Overall risk score: {self._calculate_risk_score(findings)}/10. "
            f"Agents used: {', '.join(set(f.get('agent_type', 'unknown') for f in findings if f.get('agent_type')))}."
        )
