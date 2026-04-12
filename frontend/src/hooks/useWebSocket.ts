import { useCallback, useEffect, useRef, useState } from 'react'

export interface WsEvent {
  type: string
  [key: string]: unknown
}

export function useWebSocket(sessionId: string | null) {
  const [events, setEvents] = useState<WsEvent[]>([])
  const [status, setStatus] = useState<'disconnected' | 'connected' | 'reconnecting'>('disconnected')
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const connect = useCallback(() => {
    if (!sessionId) return
    const token = localStorage.getItem('token') ?? ''
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${proto}://${window.location.host}/ws/sessions/${sessionId}?token=${token}`
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => setStatus('connected')
    ws.onmessage = (e) => {
      try {
        const evt = JSON.parse(e.data) as WsEvent
        if (evt.type !== 'ping') setEvents((prev) => [...prev, evt])
      } catch {}
    }
    ws.onclose = () => {
      setStatus('reconnecting')
      reconnectTimer.current = setTimeout(connect, 3000)
    }
    ws.onerror = () => ws.close()
  }, [sessionId])

  useEffect(() => {
    connect()
    return () => {
      wsRef.current?.close()
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
    }
  }, [connect])

  return { events, status }
}
