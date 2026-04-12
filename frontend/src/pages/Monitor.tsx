import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getSession, killSession, listReports } from '../api/client'
import { useWebSocket, WsEvent } from '../hooks/useWebSocket'

interface AgentCard {
  agent: string
  execution_id: string
  status: 'running' | 'completed' | 'failed'
  logs: string[]
  finding_count?: number
}

export default function Monitor() {
  const { id } = useParams<{ id: string }>()
  const { events, status: wsStatus } = useWebSocket(id ?? null)
  const [session, setSession] = useState<any>(null)
  const [agents, setAgents] = useState<Record<string, AgentCard>>({})
  const [sessionStatus, setSessionStatus] = useState<string>('pending')
  const [statusMessage, setStatusMessage] = useState<string>('Waiting...')
  const [plan, setPlan] = useState<any>(null)
  const [killing, setKilling] = useState(false)
  const [reportId, setReportId] = useState<string | null>(null)
  const logsEndRef = useRef<HTMLDivElement>(null)
  const allLogs = useRef<string[]>([])
  const [displayLogs, setDisplayLogs] = useState<string[]>([])

  useEffect(() => {
    if (!id) return
    getSession(id).then((r) => {
      setSession(r.data)
      setSessionStatus(r.data.status)
      if (r.data.plan_json) setPlan(r.data.plan_json)
    })
    // Check if report already exists
    listReports(id).then((r) => {
      if (r.data.length > 0) setReportId(r.data[0].id)
    })
  }, [id])

  useEffect(() => {
    events.forEach((evt: WsEvent) => processEvent(evt))
  }, [events])

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [displayLogs])

  const processEvent = (evt: WsEvent) => {
    if (evt.type === 'session_update') {
      const s = evt.status as string
      setSessionStatus(s)
      if (evt.message) setStatusMessage(evt.message as string)
      if (evt.plan) setPlan(evt.plan)
      if (s === 'completed') {
        // fetch report
        if (id) {
          listReports(id).then((r) => {
            if (r.data.length > 0) setReportId(r.data[0].id)
          })
        }
      }
    } else if (evt.type === 'agent_started') {
      const execId = evt.execution_id as string
      const agent = evt.agent as string
      setAgents((prev) => ({
        ...prev,
        [execId]: { agent, execution_id: execId, status: 'running', logs: [] },
      }))
      appendLog(`[${agent}] Started (step ${evt.step})`)
    } else if (evt.type === 'log') {
      const execId = evt.execution_id as string
      const line = (evt.data as any)?.line ?? ''
      setAgents((prev) => {
        const card = prev[execId]
        if (!card) return prev
        return { ...prev, [execId]: { ...card, logs: [...card.logs, line] } }
      })
      appendLog(`[${evt.agent}] ${line}`)
    } else if (evt.type === 'agent_completed') {
      const execId = evt.execution_id as string
      setAgents((prev) => {
        const card = prev[execId]
        if (!card) return prev
        return { ...prev, [execId]: { ...card, status: 'completed', finding_count: evt.finding_count as number } }
      })
      appendLog(`[${evt.agent}] Completed — ${evt.finding_count} findings`)
    } else if (evt.type === 'agent_failed') {
      const execId = evt.execution_id as string
      setAgents((prev) => {
        const card = prev[execId]
        if (!card) return prev
        return { ...prev, [execId]: { ...card, status: 'failed' } }
      })
      appendLog(`[${evt.agent}] FAILED: ${evt.error}`)
    }
  }

  const appendLog = (line: string) => {
    allLogs.current = [...allLogs.current, line]
    setDisplayLogs([...allLogs.current])
  }

  const handleKill = async () => {
    if (!id || killing) return
    setKilling(true)
    try {
      await killSession(id)
      setSessionStatus('killed')
      setStatusMessage('Session killed by operator')
    } finally {
      setKilling(false)
    }
  }

  const statusColor = (s: string) =>
    ({ running: 'text-green-400', completed: 'text-blue-400', failed: 'text-red-400', killed: 'text-yellow-400', pending: 'text-gray-400', executing: 'text-purple-400' }[s] ?? 'text-gray-400')

  const agentStatusBadge = (s: string) =>
    ({ running: 'bg-green-900 text-green-300', completed: 'bg-blue-900 text-blue-300', failed: 'bg-red-900 text-red-300' }[s] ?? 'bg-gray-700 text-gray-300')

  const isActive = sessionStatus === 'running' || sessionStatus === 'executing' || sessionStatus === 'pending'

  return (
    <div className="min-h-screen bg-gray-950 p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          {session?.project_id && (
            <Link to={`/projects/${session.project_id}`} className="text-gray-400 hover:text-white">← Project</Link>
          )}
          <h1 className="text-xl font-bold">Session Monitor</h1>
          <span className={`text-sm font-semibold uppercase ${statusColor(sessionStatus)}`}>
            {sessionStatus}
          </span>
          <span className={`text-xs px-2 py-0.5 rounded-full ${wsStatus === 'connected' ? 'bg-green-900 text-green-300' : 'bg-yellow-900 text-yellow-300'}`}>
            WS: {wsStatus}
          </span>
        </div>

        {isActive && (
          <button
            onClick={handleKill}
            disabled={killing}
            className="bg-red-700 hover:bg-red-600 disabled:opacity-50 text-white px-5 py-2 rounded-lg font-semibold text-sm"
          >
            {killing ? 'Stopping...' : '⚠ Kill Session'}
          </button>
        )}
        {reportId && (
          <Link to="/reports" className="bg-blue-700 hover:bg-blue-600 text-white px-5 py-2 rounded-lg font-semibold text-sm">
            View Report
          </Link>
        )}
      </div>

      {/* Status message */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg px-4 py-3 mb-4 text-sm text-gray-300">
        {statusMessage}
      </div>

      {/* Prompt */}
      {session?.prompt && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg px-4 py-3 mb-4">
          <p className="text-xs text-gray-500 mb-1">Prompt</p>
          <p className="text-sm text-gray-200">{session.prompt}</p>
        </div>
      )}

      <div className="grid grid-cols-3 gap-4">
        {/* Left: Plan + Agent Cards */}
        <div className="col-span-1 space-y-4">
          {/* Attack Plan */}
          {plan && (
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
              <h2 className="text-sm font-semibold text-gray-300 mb-2">Attack Plan</h2>
              <p className="text-xs text-gray-400 mb-2">{plan.target_summary}</p>
              <span className={`text-xs px-2 py-0.5 rounded-full ${plan.risk_level === 'high' ? 'bg-red-900 text-red-300' : plan.risk_level === 'medium' ? 'bg-yellow-900 text-yellow-300' : 'bg-green-900 text-green-300'}`}>
                Risk: {plan.risk_level}
              </span>
              <div className="mt-3 space-y-1">
                {plan.steps?.map((step: any) => (
                  <div key={step.order} className="flex items-center gap-2 text-xs text-gray-400">
                    <span className="text-gray-600">#{step.order}</span>
                    <span className="uppercase text-gray-500">[{step.agent}]</span>
                    <span className="truncate">{step.description}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Agent Cards */}
          {Object.values(agents).map((card) => (
            <div key={card.execution_id} className="bg-gray-900 border border-gray-800 rounded-xl p-4">
              <div className="flex justify-between items-center mb-2">
                <span className="text-sm font-semibold uppercase text-gray-200">{card.agent}</span>
                <span className={`text-xs px-2 py-0.5 rounded-full ${agentStatusBadge(card.status)}`}>
                  {card.status}
                </span>
              </div>
              {card.finding_count !== undefined && (
                <p className="text-xs text-gray-400">{card.finding_count} findings</p>
              )}
              {card.logs.length > 0 && (
                <div className="mt-2 bg-gray-950 rounded p-2 max-h-24 overflow-y-auto">
                  {card.logs.slice(-10).map((l, i) => (
                    <p key={i} className="text-xs text-gray-500 font-mono truncate">{l}</p>
                  ))}
                </div>
              )}
            </div>
          ))}

          {Object.keys(agents).length === 0 && !plan && (
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 text-center text-gray-500 text-sm">
              Waiting for agents...
            </div>
          )}
        </div>

        {/* Right: Live Logs */}
        <div className="col-span-2">
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 h-full">
            <h2 className="text-sm font-semibold text-gray-300 mb-3">Live Output</h2>
            <div className="bg-gray-950 rounded-lg p-3 h-[560px] overflow-y-auto font-mono text-xs">
              {displayLogs.length === 0 ? (
                <p className="text-gray-600">Waiting for output...</p>
              ) : (
                displayLogs.map((line, i) => (
                  <p key={i} className={`leading-5 ${line.includes('FAILED') || line.includes('error') ? 'text-red-400' : line.includes('Completed') ? 'text-green-400' : 'text-gray-400'}`}>
                    {line}
                  </p>
                ))
              )}
              <div ref={logsEndRef} />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
