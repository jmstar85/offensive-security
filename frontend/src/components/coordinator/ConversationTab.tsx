import { useEffect, useRef, useState } from "react";
import { Badge } from "../ui/badge";
import { useTopicWebSocket } from "../../hooks/useTopicWebSocket";
import { sendPentestMessage } from "../../api/client";

interface ConversationMessage {
  role: string;
  iteration: number;
  content: string;
  layer_hits?: string[];
  circuit_open?: boolean;
}

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

export function ConversationTab({ sessionId }: Props) {
  const { events, status } = useTopicWebSocket(sessionId, "conversation");
  const bottomRef = useRef<HTMLDivElement>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // PR5: the operator answers the Coordinator's clarifying questions here. The
  // reply round-trips through the turn-based interview (CoordinatorService.
  // run_interview_turn) via /pentest-sessions/{id}/messages.
  const onSend = async () => {
    const content = input.trim();
    if (!content || sending) return;
    setSending(true);
    setError(null);
    try {
      await sendPentestMessage(sessionId, content);
      setInput("");
    } catch {
      setError("Failed to send. Try again.");
    } finally {
      setSending(false);
    }
  };

  const messages = events.filter(
    (e) => e.role !== undefined
  ) as unknown as ConversationMessage[];

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  return (
    <div className="flex flex-col h-full">
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
            No conversation messages yet.
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
              {msg.circuit_open && (
                <span className="text-xs px-2 py-0.5 rounded bg-red-500/10 text-red-400 border border-red-500/20 font-medium">
                  scrubber circuit open
                </span>
              )}
            </div>

            <div className="text-sm text-foreground bg-muted/30 rounded px-3 py-2 whitespace-pre-wrap break-words">
              {msg.content}
            </div>

            {msg.layer_hits && msg.layer_hits.length > 0 && (
              <div className="flex flex-wrap gap-1">
                <span className="text-xs text-muted-foreground">redacted:</span>
                {msg.layer_hits.map((hit, j) => (
                  <Badge key={j} variant="secondary" className="text-xs">
                    {hit}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="border-t border-border p-3 space-y-2">
        {error && <p className="text-xs text-red-400">{error}</p>}
        <div className="flex gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void onSend();
              }
            }}
            rows={2}
            placeholder="Answer the Coordinator's question…"
            className="flex-1 resize-none rounded border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
          />
          <button
            type="button"
            onClick={() => void onSend()}
            disabled={sending || !input.trim()}
            className="self-end rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            {sending ? "Sending…" : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
}
