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

interface TerminalEvent extends WsEvent {
  line?: string
  data?: { line?: string }
}

export function TerminalTab({ sessionId }: { sessionId: string }) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const termRef = useRef<Terminal | null>(null)
  const fitRef = useRef<FitAddon | null>(null)
  const lastWritten = useRef<number>(0)
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
      // Backend publishes the stdout line nested at `event.data.line`; the
      // future persisted-history shape uses top-level `line`. Read from either.
      const line = e.data?.line ?? e.line
      if (typeof line === 'string') term.writeln(line)
      else term.writeln(JSON.stringify(e))
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
