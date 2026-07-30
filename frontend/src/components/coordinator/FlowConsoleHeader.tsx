/**
 * FlowConsoleHeader — thin session-level status bar (W4/PR4.4).
 *
 * Renders cost_usd_accum, per-family token badges (recon/exploit/extraction),
 * and coordinator iteration_no. Polls at 2s interval.
 */
import { useEffect, useRef, useState } from 'react'

import {
  AgentFamilyRow,
  getAgentFamilies,
  getPentestSessionCoordinator,
  PentestSessionRow,
} from '@/api/client'

const POLL_INTERVAL_MS = 2000
const FAMILY_ORDER = ['recon', 'exploit', 'extraction'] as const

function formatCost(usd: number | null): string {
  if (usd === null || usd === undefined) return '$—'
  return `$${usd.toFixed(4)}`
}

function FamilyBadge({ label, tokens }: { label: string; tokens: number }) {
  return (
    <span className="inline-flex items-center gap-1 text-[11px] font-mono bg-muted px-2 py-0.5 rounded ring-1 ring-border">
      <span className="text-muted-foreground capitalize">{label}</span>
      <span className="font-semibold tabular-nums">{tokens.toLocaleString()}</span>
    </span>
  )
}

// Map a session status to a short operator-facing label + badge classes. Terminal
// safety/abort states get a prominent colour so a run that was HALTED (egress kill)
// or FAILED (non-kill abort) is never mistaken for a clean completion — the whole
// point of the backend finalizing killed/failed instead of a rosy 'completed'.
function sessionStatusMeta(status: string): { label: string; className: string } {
  switch (status) {
    case 'killed':
      return { label: 'Halted · safety', className: 'bg-amber-900 text-amber-200 ring-amber-700' }
    case 'failed':
      return { label: 'Failed', className: 'bg-red-900 text-red-200 ring-red-700' }
    case 'paused_for_rescope':
      return { label: 'Paused · rescope', className: 'bg-orange-900 text-orange-200 ring-orange-700' }
    case 'completed':
      return { label: 'Completed', className: 'bg-blue-900 text-blue-200 ring-blue-700' }
    case 'executing':
      return { label: 'Executing', className: 'bg-purple-900 text-purple-200 ring-purple-700' }
    case 'running':
      return { label: 'Running', className: 'bg-emerald-900 text-emerald-200 ring-emerald-700' }
    case 'rejected':
      return { label: 'Rejected', className: 'bg-red-950 text-red-300 ring-red-800' }
    default:
      return { label: status.replace(/_/g, ' '), className: 'bg-muted text-muted-foreground ring-border' }
  }
}

function SessionStatusBadge({ status }: { status: string }) {
  const { label, className } = sessionStatusMeta(status)
  return (
    <span
      data-testid="flow-session-status"
      data-status={status}
      className={`inline-flex items-center text-[11px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded ring-1 ${className}`}
    >
      {label}
    </span>
  )
}

export function FlowConsoleHeader({ sessionId }: { sessionId: string }) {
  const [session, setSession] = useState<PentestSessionRow | null>(null)
  const [families, setFamilies] = useState<AgentFamilyRow[]>([])
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    let cancelled = false

    async function fetchAll() {
      try {
        const [sessionRes, familiesRes] = await Promise.all([
          getPentestSessionCoordinator(sessionId),
          getAgentFamilies(sessionId),
        ])
        if (!cancelled) {
          setSession(sessionRes.data)
          setFamilies(familiesRes.data)
        }
      } catch {
        // silently ignore — header is best-effort
      }
    }

    fetchAll()
    timerRef.current = setInterval(fetchAll, POLL_INTERVAL_MS)

    return () => {
      cancelled = true
      if (timerRef.current !== null) clearInterval(timerRef.current)
    }
  }, [sessionId])

  const familyMap = Object.fromEntries(families.map((f) => [f.family_kind, f.tokens_consumed]))

  return (
    <div
      className="flex items-center gap-3 px-3 py-1.5 border-b bg-muted/20 text-sm shrink-0 flex-wrap"
      data-testid="flow-console-header"
    >
      {session !== null && <SessionStatusBadge status={session.status} />}

      <span className="font-mono font-semibold text-emerald-700 dark:text-emerald-400">
        {formatCost(session?.cost_usd_accum ?? null)}
      </span>

      <span className="text-muted-foreground text-[11px]">tokens:</span>
      {FAMILY_ORDER.map((kind) => (
        <FamilyBadge key={kind} label={kind} tokens={familyMap[kind] ?? 0} />
      ))}

      {session !== null && (
        <span className="ml-auto text-[11px] text-muted-foreground tabular-nums">
          iter&nbsp;
          <span className="font-semibold text-foreground">
            {session.coordinator_revision_no}
          </span>
        </span>
      )}
    </div>
  )
}
