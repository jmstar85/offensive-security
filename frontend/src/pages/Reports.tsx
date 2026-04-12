import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { downloadPdf, listReports } from '../api/client'

interface Report {
  id: string
  session_id: string
  summary: string | null
  findings_json: {
    findings: Finding[]
    severity_counts: Record<string, number>
    total: number
  }
  risk_score: number | null
  has_pdf: boolean
}

interface Finding {
  title?: string
  severity?: string
  description?: string
  agent_type?: string
  remediation?: string
}

export default function Reports() {
  const [reports, setReports] = useState<Report[]>([])
  const [selected, setSelected] = useState<Report | null>(null)
  const [downloading, setDownloading] = useState<string | null>(null)

  useEffect(() => {
    listReports().then((r) => setReports(r.data))
  }, [])

  const handleDownload = async (report: Report) => {
    setDownloading(report.id)
    try {
      const res = await downloadPdf(report.id)
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = `report-${report.id.slice(0, 8)}.pdf`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      alert('PDF not available yet')
    } finally {
      setDownloading(null)
    }
  }

  const riskColor = (score: number | null) => {
    if (!score) return 'text-gray-400'
    if (score >= 7) return 'text-red-400'
    if (score >= 4) return 'text-yellow-400'
    return 'text-green-400'
  }

  const severityBadge = (sev: string) =>
    ({
      critical: 'bg-red-900 text-red-300',
      high: 'bg-orange-900 text-orange-300',
      medium: 'bg-yellow-900 text-yellow-300',
      low: 'bg-blue-900 text-blue-300',
      info: 'bg-gray-700 text-gray-300',
    }[sev] ?? 'bg-gray-700 text-gray-300')

  return (
    <div className="min-h-screen bg-gray-950 p-8">
      <div className="flex items-center gap-4 mb-6">
        <Link to="/" className="text-gray-400 hover:text-white">← Dashboard</Link>
        <h1 className="text-2xl font-bold">Reports</h1>
      </div>

      <div className="grid grid-cols-3 gap-6">
        {/* Report List */}
        <div className="col-span-1 space-y-3">
          {reports.length === 0 && (
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 text-center text-gray-500">
              No reports yet. Complete a pentest session to generate a report.
            </div>
          )}
          {reports.map((r) => (
            <button
              key={r.id}
              onClick={() => setSelected(r)}
              className={`w-full text-left bg-gray-900 border rounded-xl p-4 transition hover:border-red-800 ${selected?.id === r.id ? 'border-red-700' : 'border-gray-800'}`}
            >
              <div className="flex justify-between items-start mb-2">
                <span className="text-xs text-gray-500 font-mono">{r.id.slice(0, 8)}...</span>
                <span className={`text-lg font-bold ${riskColor(r.risk_score)}`}>
                  {r.risk_score?.toFixed(1) ?? 'N/A'}
                  <span className="text-xs text-gray-500 ml-1">/10</span>
                </span>
              </div>
              <p className="text-sm text-gray-300 line-clamp-2">{r.summary ?? 'No summary'}</p>
              <div className="flex gap-2 mt-2">
                {Object.entries(r.findings_json.severity_counts ?? {}).map(([sev, count]) => (
                  count > 0 && (
                    <span key={sev} className={`text-xs px-2 py-0.5 rounded-full ${severityBadge(sev)}`}>
                      {count} {sev}
                    </span>
                  )
                ))}
              </div>
              <div className="flex justify-between items-center mt-3">
                <Link
                  to={`/sessions/${r.session_id}/monitor`}
                  onClick={(e) => e.stopPropagation()}
                  className="text-xs text-gray-500 hover:text-blue-400"
                >
                  View Session
                </Link>
                {r.has_pdf && (
                  <button
                    onClick={(e) => { e.stopPropagation(); handleDownload(r) }}
                    disabled={downloading === r.id}
                    className="text-xs text-red-400 hover:text-red-300 disabled:opacity-50"
                  >
                    {downloading === r.id ? 'Downloading...' : '↓ PDF'}
                  </button>
                )}
              </div>
            </button>
          ))}
        </div>

        {/* Report Detail */}
        <div className="col-span-2">
          {!selected ? (
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-8 text-center text-gray-500">
              Select a report to view details
            </div>
          ) : (
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
              <div className="flex justify-between items-start mb-4">
                <div>
                  <h2 className="text-lg font-semibold">Report Details</h2>
                  <p className="text-xs text-gray-500 font-mono mt-1">{selected.id}</p>
                </div>
                <div className="text-right">
                  <span className={`text-3xl font-bold ${riskColor(selected.risk_score)}`}>
                    {selected.risk_score?.toFixed(1) ?? 'N/A'}
                  </span>
                  <p className="text-xs text-gray-500">Risk Score</p>
                </div>
              </div>

              {/* Summary */}
              <div className="bg-gray-800 rounded-lg p-4 mb-4">
                <p className="text-sm text-gray-300">{selected.summary ?? 'No summary available.'}</p>
              </div>

              {/* Severity Summary */}
              <div className="flex gap-3 mb-4">
                {Object.entries(selected.findings_json.severity_counts ?? {}).map(([sev, count]) => (
                  <div key={sev} className={`flex-1 text-center rounded-lg p-3 ${severityBadge(sev)}`}>
                    <p className="text-2xl font-bold">{count}</p>
                    <p className="text-xs capitalize">{sev}</p>
                  </div>
                ))}
                {Object.keys(selected.findings_json.severity_counts ?? {}).length === 0 && (
                  <p className="text-gray-500 text-sm">No severity data</p>
                )}
              </div>

              {/* Findings */}
              <h3 className="text-sm font-semibold text-gray-300 mb-2">
                Findings ({selected.findings_json.total ?? 0})
              </h3>
              <div className="space-y-3 max-h-96 overflow-y-auto pr-1">
                {(selected.findings_json.findings ?? []).length === 0 ? (
                  <p className="text-gray-500 text-sm">No findings recorded.</p>
                ) : (
                  (selected.findings_json.findings ?? []).map((f, i) => (
                    <div key={i} className="bg-gray-800 rounded-lg p-3">
                      <div className="flex justify-between items-start mb-1">
                        <p className="text-sm font-medium text-gray-200">
                          {f.title ?? `Finding ${i + 1}`}
                        </p>
                        <span className={`text-xs px-2 py-0.5 rounded-full ml-2 flex-shrink-0 ${severityBadge(f.severity ?? 'info')}`}>
                          {f.severity ?? 'info'}
                        </span>
                      </div>
                      {f.agent_type && (
                        <p className="text-xs text-gray-500 mb-1">Agent: {f.agent_type}</p>
                      )}
                      {f.description && (
                        <p className="text-xs text-gray-400">{f.description}</p>
                      )}
                      {f.remediation && (
                        <p className="text-xs text-green-400 mt-1">Remediation: {f.remediation}</p>
                      )}
                    </div>
                  ))
                )}
              </div>

              {/* Actions */}
              <div className="mt-4 flex gap-3">
                {selected.has_pdf && (
                  <button
                    onClick={() => handleDownload(selected)}
                    disabled={downloading === selected.id}
                    className="bg-red-700 hover:bg-red-600 disabled:opacity-50 text-white px-5 py-2 rounded-lg text-sm font-semibold"
                  >
                    {downloading === selected.id ? 'Downloading...' : 'Download PDF Report'}
                  </button>
                )}
                <Link
                  to={`/sessions/${selected.session_id}/monitor`}
                  className="bg-gray-700 hover:bg-gray-600 text-white px-5 py-2 rounded-lg text-sm font-semibold"
                >
                  View Session
                </Link>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
