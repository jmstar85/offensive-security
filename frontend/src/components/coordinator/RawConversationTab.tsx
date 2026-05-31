import { useCallback, useEffect, useRef, useState } from "react";

interface RawMessage {
  role: string;
  iteration: number;
  content: string;
}

type WsStatus = "disconnected" | "connected" | "reconnecting" | "denied";

interface Props {
  sessionId: string;
}

function roleBadgeClass(role: string): string {
  switch (role) {
    case "user":
      return "bg-blue-500/10 text-blue-400 border-blue-500/20";
    case "assistant":
      return "bg-green-500/10 text-green-400 border-green-500/20";
    case "system":
      return "bg-amber-500/10 text-amber-400 border-amber-500/20";
    default:
      return "bg-muted text-muted-foreground";
  }
}

export function RawConversationTab({ sessionId }: Props) {
  const [messages, setMessages] = useState<RawMessage[]>([]);
  const [status, setStatus] = useState<WsStatus>("disconnected");
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const connect = useCallback(() => {
    if (!sessionId) return;
    const token = localStorage.getItem("token") ?? "";
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const url = `${proto}://${window.location.host}/ws/sessions/${sessionId}?token=${token}&topics=raw_conversation&accept_raw=true`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => setStatus("connected");
    ws.onmessage = (e) => {
      try {
        const evt = JSON.parse(e.data);
        if (evt.type !== "ping" && evt.role !== undefined) {
          setMessages((prev) => [...prev, evt as RawMessage]);
        }
      } catch {
        // ignore malformed payload
      }
    };
    ws.onclose = (ev) => {
      if (ev.code === 4003) {
        setStatus("denied");
        return;
      }
      setStatus("reconnecting");
      reconnectTimer.current = setTimeout(connect, 3000);
    };
    ws.onerror = () => ws.close();
  }, [sessionId]);

  useEffect(() => {
    connect();
    return () => {
      wsRef.current?.close();
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    };
  }, [connect]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  if (status === "denied") {
    return (
      <div className="flex items-center justify-center h-full p-8">
        <p className="text-sm text-destructive">Access denied (4003)</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-2 bg-red-900/20 border-b border-red-700/40 text-xs text-red-300 font-medium">
        RAW unscrubbed conversation — TEAM_ADMIN only. Treat as sensitive. May contain secrets.
      </div>

      <div className="flex items-center gap-2 px-4 py-2 border-b border-border text-xs text-muted-foreground">
        <span
          className={`w-2 h-2 rounded-full ${
            status === "connected"
              ? "bg-green-500"
              : status === "reconnecting"
              ? "bg-amber-500 animate-pulse"
              : "bg-muted-foreground"
          }`}
        />
        {status === "connected" ? "Live" : status === "reconnecting" ? "Reconnecting..." : "Disconnected"}
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.length === 0 && (
          <p className="text-center text-muted-foreground text-sm py-8">
            No raw conversation messages yet.
          </p>
        )}

        {messages.map((msg, i) => (
          <div key={i} className="space-y-1">
            <div className="flex items-center gap-2">
              <span
                className={`text-xs px-2 py-0.5 rounded border font-medium ${roleBadgeClass(msg.role)}`}
              >
                {msg.role}
              </span>
              <span className="text-xs text-muted-foreground">iter {msg.iteration}</span>
            </div>
            <div className="text-sm text-foreground bg-muted/30 rounded px-3 py-2 whitespace-pre-wrap break-words font-mono">
              {msg.content}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
