/**
 * FlowIndex — landing page for the v4.0 /flow shell (P3-main gap-fill).
 *
 * Operators land here from the sidebar's "Flow Console" entry (flag-gated
 * via `useFeatureFlags`). The page lists active pentest sessions and lets
 * the operator drop into the new 2-pane flow shell at `/flow/<session_id>`,
 * or create a new session via the existing PentestWorkflow page.
 *
 * If no sessions exist yet, the page surfaces a clear CTA to create one.
 */
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { PanelsLeftRight, Plus, Loader2 } from 'lucide-react'

import { listSessions } from '../api/client'
import { LegacyPageBanner } from '../components/banners/LegacyPageBanner'

interface SessionRow {
  id: string
  prompt?: string
  status?: string
  created_at?: string
  project_id?: string
}

const STATUS_STYLE: Record<string, string> = {
  running: 'bg-amber-500/15 text-amber-700 ring-amber-500/30',
  completed: 'bg-emerald-500/15 text-emerald-700 ring-emerald-500/30',
  failed: 'bg-rose-500/15 text-rose-700 ring-rose-500/30',
  pending: 'bg-sky-500/15 text-sky-700 ring-sky-500/30',
  paused_for_rescope: 'bg-purple-500/15 text-purple-700 ring-purple-500/30',
}

export default function FlowIndex() {
  const navigate = useNavigate()
  const [sessions, setSessions] = useState<SessionRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listSessions()
      .then((r) => setSessions(r.data ?? []))
      .catch((e) => setError(String(e?.response?.data?.detail ?? e)))
  }, [])

  return (
    <div className="p-6 space-y-6">
      {/* The /flow index itself is the new UI, so no DeprecationBanner — but
          we still mount one zero-impact when flag is OFF (returns null). */}
      <LegacyPageBanner pageName="(none)" />

      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <PanelsLeftRight className="h-6 w-6 text-primary" />
            Flow Console
          </h1>
          <p className="text-muted-foreground text-sm mt-1 max-w-2xl">
            Unified 2-pane workspace for autonomous pentest sessions. Pick an
            active session below to enter the Terminal · Tasks · Agents shell,
            or start a new one.
          </p>
        </div>
        <button
          type="button"
          onClick={() => navigate('/pentest-sessions/new')}
          className="inline-flex items-center gap-2 bg-primary text-primary-foreground hover:opacity-90 px-3 py-2 rounded-md text-sm font-medium"
        >
          <Plus className="h-4 w-4" />
          New Pentest Session
        </button>
      </div>

      {error && (
        <div className="border border-rose-500/40 bg-rose-500/10 text-rose-700 dark:text-rose-300 rounded p-3 text-sm">
          {error}
        </div>
      )}

      {!error && sessions === null && (
        <div className="text-sm text-muted-foreground inline-flex items-center gap-2">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading sessions…
        </div>
      )}

      {sessions !== null && sessions.length === 0 && (
        <div className="border border-dashed border-border rounded-lg p-8 text-center">
          <PanelsLeftRight className="h-10 w-10 text-muted-foreground/50 mx-auto mb-3" />
          <p className="text-sm text-muted-foreground">
            No pentest sessions yet. Create one to drop into the Flow shell.
          </p>
          <button
            type="button"
            onClick={() => navigate('/pentest-sessions/new')}
            className="mt-4 inline-flex items-center gap-2 bg-primary text-primary-foreground hover:opacity-90 px-3 py-2 rounded-md text-sm font-medium"
          >
            <Plus className="h-4 w-4" />
            Start your first pentest
          </button>
        </div>
      )}

      {sessions !== null && sessions.length > 0 && (
        <ul className="grid gap-3 grid-cols-1 md:grid-cols-2 lg:grid-cols-3">
          {sessions.map((s) => (
            <li key={s.id}>
              <Link
                to={`/flow/${s.id}`}
                className="block border border-border rounded-lg p-3 bg-card hover:bg-muted/40 transition-colors"
                data-testid={`flow-session-card-${s.id}`}
              >
                <div className="flex items-center justify-between mb-1.5">
                  <span className="font-mono text-[11px] text-muted-foreground/80 truncate">
                    {s.id.slice(0, 8)}…
                  </span>
                  {s.status && (
                    <span
                      className={
                        'text-[10px] uppercase ring-1 px-1.5 py-0.5 rounded ' +
                        (STATUS_STYLE[s.status] ??
                          'bg-muted text-muted-foreground ring-border')
                      }
                    >
                      {s.status}
                    </span>
                  )}
                </div>
                <p className="text-sm text-foreground line-clamp-3">
                  {s.prompt ?? '(no prompt)'}
                </p>
                {s.created_at && (
                  <p className="text-[11px] text-muted-foreground mt-2">
                    {new Date(s.created_at).toLocaleString()}
                  </p>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
