import { useEffect, useRef } from "react";
import { useTopicWebSocket } from "../../hooks/useTopicWebSocket";
import { useFeatureFlags } from "../../hooks/useFeatureFlags";

interface OOBCallback {
  timestamp: string;
  protocol: "DNS" | "HTTP" | string;
  correlation_id: string;
  src_ip: string;
}

interface Props {
  sessionId: string;
  findings?: Array<{ correlation_id?: string; [key: string]: unknown }>;
}

export function CollaboratorTab({ sessionId, findings = [] }: Props) {
  const { events, status } = useTopicWebSocket(sessionId, "collaborator");
  const featureFlags = useFeatureFlags();
  const bottomRef = useRef<HTMLDivElement>(null);

  const callbacks = events.filter(
    (e) => (e as unknown as OOBCallback).correlation_id !== undefined
  ) as unknown as OOBCallback[];

  const correlatedIds = new Set(
    findings
      .map((f) => f.correlation_id)
      .filter((id): id is string => Boolean(id))
  );

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [callbacks.length]);

  if (!featureFlags?.osa_collaborator_enabled) {
    return (
      <div className="flex items-center justify-center h-full text-sm text-muted-foreground italic p-4">
        Collaborator OOB callbacks are disabled. Enable{" "}
        <code className="mx-1 font-mono text-xs bg-muted px-1 rounded">
          osa_collaborator_enabled
        </code>{" "}
        in feature flags.
      </div>
    );
  }

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
        {status === "connected"
          ? "Live"
          : status === "reconnecting"
          ? "Reconnecting..."
          : "Disconnected"}
        <span className="ml-auto text-muted-foreground/60">
          {callbacks.length} callback{callbacks.length !== 1 ? "s" : ""}
        </span>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {callbacks.length === 0 ? (
          <p className="text-center text-muted-foreground text-sm py-8">
            No OOB callbacks received yet.
          </p>
        ) : (
          callbacks.map((cb, i) => {
            const isCorrelated = correlatedIds.has(cb.correlation_id);
            const shortId = cb.correlation_id.slice(-8);

            return (
              <div
                key={i}
                className="flex items-start gap-3 rounded border border-border/50 bg-muted/20 px-3 py-2 text-xs"
              >
                <span className="text-muted-foreground whitespace-nowrap font-mono">
                  {cb.timestamp}
                </span>
                <span
                  className={`shrink-0 px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase ${
                    cb.protocol === "DNS"
                      ? "bg-purple-500/10 text-purple-400 border border-purple-500/20"
                      : cb.protocol === "HTTP"
                      ? "bg-blue-500/10 text-blue-400 border border-blue-500/20"
                      : "bg-muted text-muted-foreground border border-border"
                  }`}
                >
                  {cb.protocol}
                </span>
                <span className="font-mono text-foreground">
                  {shortId}
                </span>
                <span className="text-muted-foreground">{cb.src_ip}</span>
                {isCorrelated && (
                  <a
                    href="#findings"
                    className="ml-auto shrink-0 text-primary hover:underline text-[11px]"
                  >
                    Correlated with finding
                  </a>
                )}
              </div>
            );
          })
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
