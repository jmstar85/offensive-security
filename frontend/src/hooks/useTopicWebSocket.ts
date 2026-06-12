/**
 * useTopicWebSocket — topic-scoped subscription to /ws/sessions/:id (v4.0 P3-spike)
 *
 * Per ADR-001, each /flow/:id UI panel subscribes to exactly one topic
 * ("terminal", "tasks", "agents", "automation", "session"). The backend
 * EventBus delivers only events whose `publish(..., topic=X)` matches the
 * subscriber's filter. This hook is the small (≤60 LOC per the plan) typed
 * companion to `useWebSocket` — coexists with the legacy hook until P5
 * deletes the old one.
 *
 * Usage:
 *   const { events, status } = useTopicWebSocket(sessionId, 'terminal')
 *
 * The token comes from localStorage same as useWebSocket. Auto-reconnects
 * with 3s delay (matches the legacy behavior).
 */
import { useCallback, useEffect, useRef, useState } from 'react'

export interface WsEvent {
  type?: string
  topic?: string
  [key: string]: unknown
}

export type WsStatus = 'disconnected' | 'connected' | 'reconnecting'

export function useTopicWebSocket(
  sessionId: string | null,
  topic: string,
): { events: WsEvent[]; status: WsStatus } {
  const [events, setEvents] = useState<WsEvent[]>([])
  const [status, setStatus] = useState<WsStatus>('disconnected')
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const connect = useCallback(() => {
    if (!sessionId || !topic) return
    const token = localStorage.getItem('token') ?? ''
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${proto}://${window.location.host}/api/v1/ws/sessions/${sessionId}?token=${token}&topics=${encodeURIComponent(topic)}`
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => setStatus('connected')
    ws.onmessage = (e) => {
      try {
        const evt = JSON.parse(e.data) as WsEvent
        if (evt.type !== 'ping') setEvents((prev) => [...prev, evt])
      } catch {
        // Malformed payload — ignore. The legacy hook does the same.
      }
    }
    ws.onclose = () => {
      setStatus('reconnecting')
      reconnectTimer.current = setTimeout(connect, 3000)
    }
    ws.onerror = () => ws.close()
  }, [sessionId, topic])

  useEffect(() => {
    connect()
    return () => {
      wsRef.current?.close()
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
    }
  }, [connect])

  return { events, status }
}
