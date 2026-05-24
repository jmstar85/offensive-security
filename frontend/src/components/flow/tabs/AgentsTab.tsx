/**
 * AgentsTab — per-role MsgChain status panel (v4.0 P3-main).
 *
 * Data sources:
 * - Initial render: `GET /pentest-sessions/{id}/msgchains` (one row per role).
 * - Live updates: WebSocket `topic="agents"` events; each event may carry
 *   `{type: 'msgchain_updated' | 'role_retry' | 'adviser_injected', ...}`.
 *
 * v4.0 Minimal 6 roles: Generator, Pentester, Memorist, Adviser, Reflector,
 * Reporter. Each row shows the chain status + retries + message count.
 */
import { useEffect, useState } from 'react'
import { Activity, AlertTriangle, CheckCircle2, Loader2, RotateCcw } from 'lucide-react'

import { getMsgChains, MsgChainRow } from '@/api/client'
import { useTopicWebSocket } from '@/hooks/useTopicWebSocket'

const ROLE_DESCRIPTION: Record<string, string> = {
  generator: 'Plans + scores ambiguity',
  pentester: 'Executes structured tool calls',
  memorist: 'pgvector RAG lookup',
  adviser: 'Loop-break injection',
  reflector: 'Retry wrap on errors',
  reporter: 'Final report synthesis',
}

function StatusIcon({ status, retries }: { status: string; retries: number }) {
  if (status === 'finished')
    return <CheckCircle2 className="h-4 w-4 text-emerald-600" />
  if (status === 'failed')
    return <AlertTriangle className="h-4 w-4 text-rose-600" />
  if (retries > 0) return <RotateCcw className="h-4 w-4 text-amber-600" />
  if (status === 'running')
    return <Loader2 className="h-4 w-4 animate-spin text-sky-600" />
  return <Activity className="h-4 w-4 text-muted-foreground" />
}

export function AgentsTab({ sessionId }: { sessionId: string }) {
  const [chains, setChains] = useState<MsgChainRow[]>([])
  const [error, setError] = useState<string | null>(null)
  const { events } = useTopicWebSocket(sessionId, 'agents')

  // Initial fetch.
  useEffect(() => {
    let cancelled = false
    getMsgChains(sessionId)
      .then((r) => !cancelled && setChains(r.data))
      .catch((e) => !cancelled && setError(String(e)))
    return () => {
      cancelled = true
    }
  }, [sessionId])

  // Re-fetch on each `agents`-topic event. We could merge in-place but the
  // chain list is small (≤6 rows in v4.0) so the round-trip cost is fine.
  useEffect(() => {
    if (!events.length) return
    getMsgChains(sessionId).then((r) => setChains(r.data)).catch(() => {})
  }, [events.length, sessionId])

  if (error) {
    return <div className="text-sm text-rose-600">Failed to load chains: {error}</div>
  }

  if (!chains.length) {
    return (
      <div className="text-sm text-muted-foreground italic">
        No agent chains yet. Each role's chain appears once it begins
        running.
      </div>
    )
  }

  return (
    <ul className="space-y-2" data-testid="agents-list">
      {chains.map((c) => (
        <li
          key={c.id}
          className="border rounded p-2 bg-card flex items-start gap-3"
          data-testid={`agent-row-${c.role_name}`}
        >
          <div className="pt-1">
            <StatusIcon status={c.status} retries={c.retries} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-semibold capitalize text-sm">
                {c.role_name}
              </span>
              <span className="text-[10px] uppercase text-muted-foreground">
                {c.status}
              </span>
              {c.retries > 0 && (
                <span className="text-[10px] uppercase text-amber-700 bg-amber-500/10 ring-1 ring-amber-500/30 px-1.5 py-0.5 rounded">
                  retries: {c.retries}
                </span>
              )}
            </div>
            <p className="text-xs text-muted-foreground mt-0.5">
              {ROLE_DESCRIPTION[c.role_name] ?? 'Role chain'}
            </p>
            <p className="text-[11px] text-muted-foreground/70 mt-0.5">
              {c.message_count} message{c.message_count === 1 ? '' : 's'}
            </p>
          </div>
        </li>
      ))}
    </ul>
  )
}
