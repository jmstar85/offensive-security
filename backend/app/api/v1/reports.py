import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.report import Report
from app.models.user import User

router = APIRouter()


class ReportResponse(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    summary: str | None
    findings_json: dict
    risk_score: float | None
    has_pdf: bool


@router.get("/", response_model=list[ReportResponse])
async def list_reports(
    session_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(Report)
    if session_id:
        query = query.where(Report.session_id == session_id)
    result = await db.execute(query.order_by(Report.created_at.desc()))
    return [
        ReportResponse(
            id=r.id, session_id=r.session_id, summary=r.summary,
            findings_json=r.findings_json, risk_score=r.risk_score,
            has_pdf=bool(r.pdf_path),
        )
        for r in result.scalars().all()
    ]


@router.get("/{report_id}", response_model=ReportResponse)
async def get_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Report).where(Report.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return ReportResponse(
        id=report.id, session_id=report.session_id, summary=report.summary,
        findings_json=report.findings_json, risk_score=report.risk_score,
        has_pdf=bool(report.pdf_path),
    )


@router.get("/{report_id}/pdf")
async def download_pdf(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Report).where(Report.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if not report.pdf_path or not Path(report.pdf_path).exists():
        raise HTTPException(status_code=404, detail="PDF not yet generated")
    return FileResponse(
        path=report.pdf_path,
        media_type="application/pdf",
        filename=f"report-{report_id}.pdf",
    )
