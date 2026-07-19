/**
 * TerminalTab — xterm.js terminal subscribed to topic="terminal" (v4.0 P3-main).
 *
 * Receives `event_bus.publish(session_id, event, topic="terminal")` events
 * from the backend over WebSocket via `useTopicWebSocket(sessionId, 'terminal')`
 * and writes each event's `line` field to an xterm instance. The xterm
 * instance lives for the lifetime of the component; addons (fit, search,
 * web-links, webgl) are loaded once on mount.
 */
import { useEffect, useRef } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { SearchAddon } from '@xterm/addon-search'
import { WebLinksAddon } from '@xterm/addon-web-links'
import { WebglAddon } from '@xterm/addon-webgl'
import '@xterm/xterm/css/xterm.css'

import { useTopicWebSocket, WsEvent } from '@/hooks/useTopicWebSocket'
import { getTerminalHistory } from '@/api/client'

interface TerminalEvent extends WsEvent {
  line?: string
  data?: { line?: string }
  // Live WS terminal events now carry a top-level monotonic `seq` alongside
  // the nested `data.line`. Used to de-dupe against replayed history.
  seq?: number
}

// Persisted terminal history row shape (GET /sessions/:id/terminal). Rows are
// seq-ascending and only include seq > after_seq.
interface TerminalHistoryRow {
  seq: number
  line: string
  agent_type: string | null
  execution_id: string | null
  created_at: string
}

export function TerminalTab({ sessionId }: { sessionId: string }) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const termRef = useRef<Terminal | null>(null)
  const fitRef = useRef<FitAddon | null>(null)
  const lastWritten = useRef<number>(0)
  // Highest terminal seq already written (from history replay or prior live
  // events). Live events with seq <= this are duplicates of replayed history
  // and are skipped — this is the history/live boundary de-dupe.
  const maxSeqRef = useRef<number>(0)
  // Records which sessionId's history we've already fetched. Doubles as the
  // StrictMode double-run guard: the dev-mode mount→cleanup→mount cycle keeps
  // the same sessionId, so the second mount sees a match and skips re-writing,
  // while a genuine sessionId change still re-fetches.
  const historyFetchedForRef = useRef<string | null>(null)
  const { events, status } = useTopicWebSocket(sessionId, 'terminal')

  useEffect(() => {
    if (!containerRef.current || termRef.current) return

    const term = new Terminal({
      cursorBlink: false,
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
      fontSize: 13,
      convertEol: true,
      theme: { background: '#0b0d10', foreground: '#e6e6e6' },
    })

    const fit = new FitAddon()
    term.loadAddon(fit)
    term.loadAddon(new SearchAddon())
    term.loadAddon(new WebLinksAddon())
    try {
      term.loadAddon(new WebglAddon())
    } catch {
      // WebGL not available — fall through to canvas renderer.
    }

    term.open(containerRef.current)
    fit.fit()

    termRef.current = term
    fitRef.current = fit

    const resizeObserver = new ResizeObserver(() => fit.fit())
    resizeObserver.observe(containerRef.current)

    // Replay persisted terminal history once per session, before live writes.
    // Guarded so the StrictMode double-mount doesn't write history twice; the
    // fetch resolves after the (possibly re-created) term exists, so we write
    // to termRef.current at resolution time rather than a captured instance.
    if (historyFetchedForRef.current !== sessionId) {
      historyFetchedForRef.current = sessionId
      maxSeqRef.current = 0
      getTerminalHistory(sessionId)
        .then((r) => {
          const rows = (r.data ?? []) as TerminalHistoryRow[]
          const t = termRef.current
          if (!t) return
          let maxSeq = maxSeqRef.current
          for (const row of rows) {
            if (typeof row.line === 'string') t.writeln(row.line)
            if (typeof row.seq === 'number' && row.seq > maxSeq) maxSeq = row.seq
          }
          maxSeqRef.current = maxSeq
        })
        .catch(() => {
          // History replay unavailable — proceed live-only, panel stays usable.
        })
    }

    term.writeln(`[90m[terminal] subscribed to session ${sessionId}[0m`)

    return () => {
      resizeObserver.disconnect()
      term.dispose()
      termRef.current = null
      fitRef.current = null
    }
  }, [sessionId])

  // Stream new events to the terminal as they arrive. We track `lastWritten`
  // so we don't re-write the entire backlog on every React render.
  useEffect(() => {
    const term = termRef.current
    if (!term) return
    for (let i = lastWritten.current; i < events.length; i++) {
      const e = events[i] as TerminalEvent
      // History/live boundary de-dupe: skip any live event already covered by
      // the replayed history (seq <= the highest seq we've written).
      if (typeof e.seq === 'number' && e.seq <= maxSeqRef.current) continue
      // Backend publishes the stdout line nested at `event.data.line`; the
      // future persisted-history shape uses top-level `line`. Read from either.
      const line = e.data?.line ?? e.line
      if (typeof line === 'string') term.writeln(line)
      else term.writeln(JSON.stringify(e))
      if (typeof e.seq === 'number') {
        maxSeqRef.current = Math.max(maxSeqRef.current, e.seq)
      }
    }
    lastWritten.current = events.length
  }, [events])

  return (
    <div className="relative h-full w-full bg-[#0b0d10]">
      <div
        ref={containerRef}
        className="absolute inset-0 p-2"
        data-testid="flow-terminal"
      />
      <div className="absolute top-1 right-2 text-[10px] text-muted-foreground/80 bg-background/40 px-1.5 py-0.5 rounded">
        ws: {status}
      </div>
    </div>
  )
}
