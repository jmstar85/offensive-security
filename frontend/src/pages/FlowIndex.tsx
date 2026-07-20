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
import { PanelsLeftRight, Plus, Loader2, Trash2 } from 'lucide-react'

import { deleteSession, listProjects, listSessions } from '../api/client'
import { LegacyPageBanner } from '../components/banners/LegacyPageBanner'

interface SessionRow {
  id: string
  prompt?: string
  status?: string
  created_at?: string
  project_id?: string
}

interface ProjectRow {
  id: string
  name?: string
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
  const [projects, setProjects] = useState<ProjectRow[] | null>(null)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  useEffect(() => {
    listSessions()
      .then((r) => setSessions(r.data ?? []))
      .catch((e) => setError(String(e?.response?.data?.detail ?? e)))
    listProjects()
      .then((r) => setProjects(r.data ?? []))
      .catch(() => setProjects([]))
  }, [])

  // The new-session buttons must always land on a form with a non-null
  // projectId (AC-1.1): one project → attach ?project=<id>; several → open a
  // lightweight picker; none → route to the project-creation flow (/projects).
  const startNewSession = async () => {
    let list: ProjectRow[]
    if (projects !== null) {
      list = projects
    } else {
      try {
        const r = await listProjects()
        list = r.data ?? []
      } catch {
        list = []
      }
      setProjects(list)
    }
    if (list.length === 1) {
      navigate(`/pentest-sessions/new?project=${list[0].id}`)
    } else if (list.length === 0) {
      navigate('/projects')
    } else {
      setPickerOpen(true)
    }
  }

  // Delete a session + its data. Optimistically drop the card on success; a
  // running session returns 409 (surface the reason so the operator knows to
  // wait or reject it first).
  const handleDelete = async (id: string) => {
    if (
      !window.confirm(
        'Delete this session and all of its data (terminal, tasks, agents, findings)? This cannot be undone.',
      )
    ) {
      return
    }
    setDeletingId(id)
    setError(null)
    try {
      await deleteSession(id)
      setSessions((prev) => (prev ?? []).filter((x) => x.id !== id))
    } catch (e: any) {
      setError(String(e?.response?.data?.detail ?? e))
    } finally {
      setDeletingId(null)
    }
  }

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
          onClick={startNewSession}
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
            onClick={startNewSession}
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
            <li key={s.id} className="relative group">
              <Link
                to={`/flow/${s.id}`}
                className="block border border-border rounded-lg p-3 pb-8 bg-card hover:bg-muted/40 transition-colors"
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
              <button
                type="button"
                aria-label="Delete session"
                title="Delete session"
                disabled={deletingId === s.id}
                data-testid={`flow-session-delete-${s.id}`}
                onClick={(e) => {
                  e.preventDefault()
                  e.stopPropagation()
                  void handleDelete(s.id)
                }}
                className="absolute bottom-2 right-2 p-1.5 rounded-md text-muted-foreground/60 hover:text-rose-600 hover:bg-rose-500/10 opacity-0 group-hover:opacity-100 focus:opacity-100 transition disabled:opacity-50"
              >
                {deletingId === s.id ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Trash2 className="h-4 w-4" />
                )}
              </button>
            </li>
          ))}
        </ul>
      )}

      {pickerOpen && (
        <div
          className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4"
          onClick={() => setPickerOpen(false)}
        >
          <div
            className="w-full max-w-md bg-card border border-border rounded-xl shadow-2xl p-6 space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-foreground">Choose a project</h2>
              <button
                type="button"
                onClick={() => setPickerOpen(false)}
                className="text-muted-foreground hover:text-foreground text-sm"
              >
                Cancel
              </button>
            </div>
            <p className="text-sm text-muted-foreground">
              Pick the project this pentest session belongs to.
            </p>
            <ul className="space-y-2 max-h-72 overflow-y-auto">
              {(projects ?? []).map((p) => (
                <li key={p.id}>
                  <Link
                    to={`/pentest-sessions/new?project=${p.id}`}
                    onClick={() => setPickerOpen(false)}
                    className="block border border-border rounded-lg px-3 py-2 bg-card hover:bg-muted/40 transition-colors text-sm text-foreground"
                  >
                    {p.name ?? p.id}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  )
}
