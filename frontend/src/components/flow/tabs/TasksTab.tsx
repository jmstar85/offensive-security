/**
 * TasksTab — SubTask tree from session.draft_plan_json + live `tasks` events
 * (v4.0 P3-main).
 *
 * Hybrid data source:
 * - Initial render fetches `GET /pentest-sessions/{id}` and reads
 *   `draft_plan_json.steps` to seed the list.
 * - Live updates arrive over WebSocket on `topic="tasks"` and are merged
 *   into the local list by `order` (sub-event type: `task_created` /
 *   `task_updated`).
 */
import { useEffect, useState } from 'react'
import { useTopicWebSocket, WsEvent } from '@/hooks/useTopicWebSocket'
import { getPentestSession, getExecutions } from '@/api/client'

interface TaskRow {
  order: number
  agent: string
  action: string
  description: string
  tier: string
  status?: string
}

// Execution row shape (GET /sessions/:id/executions). `step_order` maps an
// execution back to the seeded plan step (TaskRow.order).
interface ExecutionRow {
  id: string
  agent_type: string
  status: string
  step_order: number | null
  started_at: string
  ended_at: string | null
}

interface TaskEvent extends WsEvent {
  type?: string
  step?: TaskRow
}

const TIER_LABEL: Record<string, string> = {
  passive_no_target_contact: 'passive',
  passive_low_touch: 'passive',
  active_recon: 'active-recon',
  active_exploit: 'active-exploit',
}

function tierBadgeClass(tier: string): string {
  switch (tier) {
    case 'active_exploit':
      return 'bg-rose-500/15 text-rose-600 ring-rose-500/30'
    case 'active_recon':
      return 'bg-amber-500/15 text-amber-600 ring-amber-500/30'
    default:
      return 'bg-emerald-500/15 text-emerald-600 ring-emerald-500/30'
  }
}

export function TasksTab({ sessionId }: { sessionId: string }) {
  const [tasks, setTasks] = useState<TaskRow[]>([])
  const [error, setError] = useState<string | null>(null)
  const { events } = useTopicWebSocket(sessionId, 'tasks')

  // Initial fetch.
  useEffect(() => {
    let cancelled = false
    getPentestSession(sessionId)
      .then((r) => {
        if (cancelled) return
        const steps = (r.data?.draft_plan_json?.steps ?? []) as TaskRow[]
        setTasks(steps)
        // Overlay persisted execution status onto the seeded rows so a
        // reloaded panel shows completed/failed states, not just the plan.
        // Match each execution to its step by step_order === row.order.
        getExecutions(sessionId)
          .then((er) => {
            if (cancelled) return
            const execs = (er.data ?? []) as ExecutionRow[]
            setTasks((prev) => {
              const next = [...prev]
              for (const ex of execs) {
                if (typeof ex.step_order !== 'number') continue
                const idx = next.findIndex((t) => t.order === ex.step_order)
                if (idx >= 0) next[idx] = { ...next[idx], status: ex.status }
              }
              return next
            })
          })
          .catch(() => {
            // Execution overlay unavailable — keep the seeded rows as-is.
          })
      })
      .catch((e) => !cancelled && setError(String(e)))
    return () => {
      cancelled = true
    }
  }, [sessionId])

  // Merge live events by `order`.
  useEffect(() => {
    if (!events.length) return
    setTasks((prev) => {
      const next = [...prev]
      for (const ev of events as TaskEvent[]) {
        if (!ev.step) continue
        const idx = next.findIndex((t) => t.order === ev.step!.order)
        if (idx >= 0) next[idx] = { ...next[idx], ...ev.step }
        else next.push(ev.step)
      }
      next.sort((a, b) => a.order - b.order)
      return next
    })
  }, [events])

  if (error) {
    return <div className="text-sm text-rose-600">Failed to load tasks: {error}</div>
  }

  if (!tasks.length) {
    return (
      <div className="text-sm text-muted-foreground italic">
        No SubTasks yet. Tasks appear after Generator produces a plan and the
        operator approves it.
      </div>
    )
  }

  return (
    <ol className="space-y-2">
      {tasks.map((t) => (
        <li
          key={`${t.order}-${t.agent}`}
          className="border rounded p-2 bg-card flex items-start gap-2"
          data-testid="task-row"
        >
          <span className="font-mono text-xs text-muted-foreground w-6 shrink-0">
            #{t.order}
          </span>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-medium text-sm">{t.agent}</span>
              <span className="text-xs text-muted-foreground">{t.action}</span>
              <span
                className={`text-[10px] uppercase ring-1 px-1.5 py-0.5 rounded ${tierBadgeClass(t.tier)}`}
              >
                {TIER_LABEL[t.tier] ?? t.tier}
              </span>
              {t.status && (
                <span className="text-[10px] uppercase text-muted-foreground">
                  {t.status}
                </span>
              )}
            </div>
            <p className="text-sm text-muted-foreground mt-0.5 truncate">
              {t.description}
            </p>
          </div>
        </li>
      ))}
    </ol>
  )
}
