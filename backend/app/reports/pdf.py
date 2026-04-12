"""PDF report generator using WeasyPrint."""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

REPORTS_DIR = Path("/tmp/osa_reports")


class PDFGenerator:
    def __init__(self) -> None:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    async def generate(
        self,
        report_id: uuid.UUID,
        summary: str,
        findings: list[dict],
        risk_score: float,
    ) -> str:
        loop = asyncio.get_event_loop()
        pdf_path = str(REPORTS_DIR / f"report-{report_id}.pdf")
        html = self._render_html(summary, findings, risk_score)
        await loop.run_in_executor(None, self._write_pdf, html, pdf_path)
        return pdf_path

    def _render_html(self, summary: str, findings: list[dict], risk_score: float) -> str:
        rows = ""
        for f in findings:
            sev = f.get("severity", "info")
            color = {"critical": "#dc2626", "high": "#ea580c", "medium": "#ca8a04",
                     "low": "#16a34a", "info": "#6b7280"}.get(sev, "#6b7280")
            rows += (
                f"<tr><td>{f.get('type','')}</td>"
                f"<td style='color:{color};font-weight:bold'>{sev.upper()}</td>"
                f"<td>{f.get('cvss_score', '')}</td>"
                f"<td>{f.get('description', f.get('detail', ''))}</td></tr>"
            )

        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: Arial, sans-serif; margin: 40px; color: #1f2937; }}
  h1 {{ color: #111827; border-bottom: 2px solid #e5e7eb; padding-bottom: 8px; }}
  .risk {{ font-size: 2em; font-weight: bold; color: #dc2626; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
  th {{ background: #374151; color: white; padding: 8px; text-align: left; }}
  td {{ border: 1px solid #e5e7eb; padding: 8px; }}
  tr:nth-child(even) {{ background: #f9fafb; }}
</style>
</head>
<body>
<h1>Penetration Test Report</h1>
<p><strong>Summary:</strong> {summary}</p>
<p><strong>Overall Risk Score:</strong> <span class="risk">{risk_score}/10</span></p>
<h2>Findings ({len(findings)})</h2>
<table>
  <tr><th>Type</th><th>Severity</th><th>CVSS</th><th>Description</th></tr>
  {rows if rows else "<tr><td colspan='4' style='text-align:center'>No findings</td></tr>"}
</table>
</body>
</html>"""

    def _write_pdf(self, html: str, path: str) -> None:
        from weasyprint import HTML
        HTML(string=html).write_pdf(path)
