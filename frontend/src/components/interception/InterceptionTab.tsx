import { useState, useEffect, useRef } from "react";
import { useTopicWebSocket } from "../../hooks/useTopicWebSocket";
import { useFeatureFlags } from "../../hooks/useFeatureFlags";

interface InterceptedRequest {
  time: string;
  method: string;
  url: string;
  status: number;
  length: number;
  flow_id: string;
  request_body?: string;
  response_body?: string;
}

const MAX_BODY_DISPLAY = 4096;

function truncateBody(body: string): { text: string; truncated: boolean } {
  if (body.length <= MAX_BODY_DISPLAY) return { text: body, truncated: false };
  return { text: body.slice(0, MAX_BODY_DISPLAY), truncated: true };
}

interface Props {
  sessionId: string;
}

export function InterceptionTab({ sessionId }: Props) {
  const { events, status } = useTopicWebSocket(sessionId, "interception");
  const featureFlags = useFeatureFlags();
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const requests = events.filter(
    (e) => (e as unknown as InterceptedRequest).flow_id !== undefined
  ) as unknown as InterceptedRequest[];

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [requests.length]);

  if (!featureFlags?.osa_mitm_proxy_enabled) {
    return (
      <div className="flex items-center justify-center h-full text-sm text-muted-foreground italic p-4">
        MITM proxy interception is disabled. Enable{" "}
        <code className="mx-1 font-mono text-xs bg-muted px-1 rounded">
          osa_mitm_proxy_enabled
        </code>{" "}
        in feature flags.
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-2 border-b border-border bg-amber-500/10 text-amber-400 text-xs font-medium">
        MITM interception live — TEAM_ADMIN only. Sensitive headers redacted by sidecar addon.
      </div>

      <div className="flex items-center gap-2 px-4 py-1.5 border-b border-border text-xs text-muted-foreground">
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
      </div>

      <div className="flex-1 overflow-y-auto">
        {requests.length === 0 ? (
          <p className="text-center text-muted-foreground text-sm py-8">
            No intercepted requests yet.
          </p>
        ) : (
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-muted/60 border-b border-border">
              <tr>
                <th className="text-left px-3 py-1.5 font-medium text-muted-foreground">Time</th>
                <th className="text-left px-3 py-1.5 font-medium text-muted-foreground">Method</th>
                <th className="text-left px-3 py-1.5 font-medium text-muted-foreground flex-1">URL</th>
                <th className="text-left px-3 py-1.5 font-medium text-muted-foreground">Status</th>
                <th className="text-left px-3 py-1.5 font-medium text-muted-foreground">Length</th>
                <th className="text-left px-3 py-1.5 font-medium text-muted-foreground">Flow ID</th>
              </tr>
            </thead>
            <tbody>
              {requests.map((req, i) => {
                const isExpanded = expandedRow === req.flow_id;
                const reqBody = req.request_body
                  ? truncateBody(req.request_body)
                  : null;
                const resBody = req.response_body
                  ? truncateBody(req.response_body)
                  : null;

                return (
                  <>
                    <tr
                      key={`${req.flow_id}-${i}`}
                      className="border-b border-border/50 hover:bg-muted/30 cursor-pointer"
                      onClick={() =>
                        setExpandedRow(isExpanded ? null : req.flow_id)
                      }
                    >
                      <td className="px-3 py-1.5 font-mono text-muted-foreground whitespace-nowrap">
                        {req.time}
                      </td>
                      <td className="px-3 py-1.5">
                        <span
                          className={`font-mono font-semibold ${
                            req.method === "GET"
                              ? "text-blue-400"
                              : req.method === "POST"
                              ? "text-green-400"
                              : req.method === "PUT" || req.method === "PATCH"
                              ? "text-amber-400"
                              : req.method === "DELETE"
                              ? "text-rose-400"
                              : "text-foreground"
                          }`}
                        >
                          {req.method}
                        </span>
                      </td>
                      <td className="px-3 py-1.5 font-mono text-foreground max-w-[240px] truncate">
                        {req.url}
                      </td>
                      <td className="px-3 py-1.5 font-mono">
                        <span
                          className={
                            req.status >= 500
                              ? "text-rose-400"
                              : req.status >= 400
                              ? "text-amber-400"
                              : req.status >= 300
                              ? "text-blue-400"
                              : "text-green-400"
                          }
                        >
                          {req.status}
                        </span>
                      </td>
                      <td className="px-3 py-1.5 text-muted-foreground">
                        {req.length}
                      </td>
                      <td className="px-3 py-1.5 font-mono text-muted-foreground text-[10px]">
                        {req.flow_id}
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr key={`${req.flow_id}-expanded`} className="bg-muted/20">
                        <td colSpan={6} className="px-4 py-3 space-y-3">
                          {reqBody && (
                            <div>
                              <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1">
                                Request Body
                              </div>
                              <pre className="font-mono text-[11px] text-foreground bg-muted/40 rounded p-2 overflow-x-auto whitespace-pre-wrap break-all max-h-48 overflow-y-auto">
                                {reqBody.text}
                                {reqBody.truncated && (
                                  <span className="text-muted-foreground">
                                    {" "}...
                                  </span>
                                )}
                              </pre>
                              {reqBody.truncated && (
                                <button className="mt-1 text-[11px] text-primary hover:underline">
                                  Open raw
                                </button>
                              )}
                            </div>
                          )}
                          {resBody && (
                            <div>
                              <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1">
                                Response Body
                              </div>
                              <pre className="font-mono text-[11px] text-foreground bg-muted/40 rounded p-2 overflow-x-auto whitespace-pre-wrap break-all max-h-48 overflow-y-auto">
                                {resBody.text}
                                {resBody.truncated && (
                                  <span className="text-muted-foreground">
                                    {" "}...
                                  </span>
                                )}
                              </pre>
                              {resBody.truncated && (
                                <button className="mt-1 text-[11px] text-primary hover:underline">
                                  Open raw
                                </button>
                              )}
                            </div>
                          )}
                          {!reqBody && !resBody && (
                            <p className="text-xs text-muted-foreground italic">
                              No body captured.
                            </p>
                          )}
                        </td>
                      </tr>
                    )}
                  </>
                );
              })}
            </tbody>
          </table>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
