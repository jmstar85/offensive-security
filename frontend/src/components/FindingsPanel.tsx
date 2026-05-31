/**
 * FindingsPanel — type-aware structured rendering for AgentResult.findings.
 *
 * The orchestrator forwards each adapter's parse_output() result through the
 * WebSocket status event (data.result.findings). Before this component the
 * legacy dashboard only counted the "[finding]" substring in log lines, so
 * the rich payloads emitted by kali_gobuster (directory_found),
 * kali_sqlmap (sql_injection), and kali_nikto (web_vuln) were invisible to
 * the user. This panel renders them grouped by type with severity-aware
 * styling, plus a graceful fallback for unknown finding types so we never
 * silently drop data the backend emitted.
 */
import { useMemo } from "react";
import { Badge } from "./ui/badge";
import { cn } from "../lib/utils";

export interface Finding {
  type: string;
  severity?: string;
  // gobuster
  path?: string;
  status?: number;
  size?: number;
  // sqlmap
  parameter?: string;
  location?: string;
  technique?: string | null;
  payload?: string | null;
  // nikto
  id?: string | null;
  message?: string | null;
  // nmap-style generic
  port?: number;
  service?: string;
  protocol?: string;
  version?: string;
  // proxy_request
  method?: string;
  url?: string;
  length?: number;
  // oob_callback
  correlation_id?: string;
  timestamp?: string;
  // dom_xss_probe
  detected?: boolean;
  // csrf_form_replay
  form_id?: string;
  replayed_count?: number;
  // Catch-all for unknown shapes — we render this as JSON in the fallback.
  [key: string]: unknown;
}

function severityVariant(sev?: string): "success" | "warning" | "destructive" | "secondary" {
  switch ((sev || "").toLowerCase()) {
    case "low":
    case "info":
      return "success";
    case "medium":
      return "warning";
    case "high":
    case "critical":
      return "destructive";
    default:
      return "secondary";
  }
}

function FindingRow({ f }: { f: Finding }) {
  const sev = (
    <Badge variant={severityVariant(f.severity)} className="text-[10px] capitalize">
      {f.severity || "info"}
    </Badge>
  );

  if (f.type === "directory_found") {
    return (
      <div className="flex items-center gap-2 text-xs">
        {sev}
        <span className="font-mono text-foreground">{f.path}</span>
        <span className="text-muted-foreground">{f.status}</span>
        {typeof f.size === "number" && (
          <span className="text-muted-foreground">{f.size}B</span>
        )}
      </div>
    );
  }
  if (f.type === "sql_injection") {
    return (
      <div className="flex flex-col gap-0.5 text-xs">
        <div className="flex items-center gap-2">
          {sev}
          <span className="font-mono text-foreground">
            {f.location || "?"} {f.parameter}
          </span>
          {f.technique && (
            <span className="text-muted-foreground">[{f.technique}]</span>
          )}
        </div>
        {f.payload && (
          <code className="block ml-12 break-all text-[11px] text-muted-foreground">
            {f.payload}
          </code>
        )}
      </div>
    );
  }
  if (f.type === "web_vuln") {
    return (
      <div className="flex items-start gap-2 text-xs">
        {sev}
        {f.id && <span className="font-mono text-muted-foreground">{f.id}</span>}
        <span className="text-foreground break-words flex-1">{f.message}</span>
      </div>
    );
  }
  if (f.type === "open_port") {
    return (
      <div className="flex items-center gap-2 text-xs">
        {sev}
        <span className="font-mono text-foreground">
          {f.port}/{f.protocol}
        </span>
        <span className="text-muted-foreground">{f.service}</span>
        {f.version && <span className="text-muted-foreground">{f.version}</span>}
      </div>
    );
  }
  if (f.type === "proxy_request") {
    return (
      <div className="flex items-center gap-2 text-xs">
        {sev}
        <span
          className={`font-mono font-semibold ${
            f.method === "GET"
              ? "text-blue-400"
              : f.method === "POST"
              ? "text-green-400"
              : f.method === "PUT" || f.method === "PATCH"
              ? "text-amber-400"
              : f.method === "DELETE"
              ? "text-rose-400"
              : "text-foreground"
          }`}
        >
          {f.method}
        </span>
        <span className="font-mono text-foreground truncate max-w-[200px]">{f.url}</span>
        {typeof f.status === "number" && (
          <span
            className={`font-mono ${
              f.status >= 500
                ? "text-rose-400"
                : f.status >= 400
                ? "text-amber-400"
                : f.status >= 300
                ? "text-blue-400"
                : "text-green-400"
            }`}
          >
            {f.status}
          </span>
        )}
        {typeof f.length === "number" && (
          <span className="text-muted-foreground">{f.length}B</span>
        )}
      </div>
    );
  }
  if (f.type === "oob_callback") {
    const shortId = f.correlation_id ? f.correlation_id.slice(-8) : "?";
    return (
      <div className="flex items-center gap-2 text-xs">
        {sev}
        <span
          className={`px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase ${
            f.protocol === "DNS"
              ? "bg-purple-500/10 text-purple-400 border border-purple-500/20"
              : f.protocol === "HTTP"
              ? "bg-blue-500/10 text-blue-400 border border-blue-500/20"
              : "bg-muted text-muted-foreground border border-border"
          }`}
        >
          {f.protocol}
        </span>
        <span className="font-mono text-foreground">{shortId}</span>
        {f.timestamp && (
          <span className="text-muted-foreground">{f.timestamp}</span>
        )}
      </div>
    );
  }
  if (f.type === "dom_xss_probe") {
    const payloadPreview = f.payload
      ? String(f.payload).slice(0, 60) + (String(f.payload).length > 60 ? "…" : "")
      : null;
    return (
      <div className="flex items-center gap-2 text-xs">
        {sev}
        <span className="font-mono text-foreground truncate max-w-[160px]">{f.url}</span>
        {payloadPreview && (
          <code className="text-[11px] text-muted-foreground truncate max-w-[120px]">
            {payloadPreview}
          </code>
        )}
        <span
          className={`font-semibold ${
            f.detected ? "text-green-400" : "text-rose-400"
          }`}
        >
          {f.detected ? "✓" : "✗"}
        </span>
      </div>
    );
  }
  if (f.type === "csrf_form_replay") {
    return (
      <div className="flex items-center gap-2 text-xs">
        {sev}
        <span className="font-mono text-foreground truncate max-w-[160px]">{f.url}</span>
        {f.form_id && (
          <span className="text-muted-foreground font-mono">{f.form_id}</span>
        )}
        {typeof f.replayed_count === "number" && (
          <span className="text-muted-foreground">×{f.replayed_count}</span>
        )}
      </div>
    );
  }
  // Unknown type — pretty-printed JSON. Never silently drop.
  const { type: _type, severity: _sev, ...rest } = f;
  return (
    <div className="flex items-start gap-2 text-xs">
      {sev}
      <span className="font-mono text-muted-foreground">{f.type}</span>
      <code className="text-[11px] text-muted-foreground break-all flex-1">
        {JSON.stringify(rest)}
      </code>
    </div>
  );
}

export interface FindingsPanelProps {
  findings: Finding[];
  className?: string;
}

export function FindingsPanel({ findings, className }: FindingsPanelProps) {
  const grouped = useMemo(() => {
    const out: Record<string, Finding[]> = {};
    for (const f of findings) {
      const key = f.type || "unknown";
      (out[key] ||= []).push(f);
    }
    return out;
  }, [findings]);

  const types = Object.keys(grouped).sort();

  if (findings.length === 0) {
    return (
      <div className={cn("text-xs text-muted-foreground italic", className)}>
        No findings yet.
      </div>
    );
  }

  return (
    <div className={cn("flex flex-col gap-3", className)}>
      {types.map((type) => (
        <section key={type}>
          <header className="text-[11px] uppercase tracking-wide text-muted-foreground mb-1.5 flex items-center gap-2">
            <span>{type.replace(/_/g, " ")}</span>
            <span className="text-muted-foreground/60">×{grouped[type].length}</span>
          </header>
          <div className="space-y-1.5 pl-1">
            {grouped[type].map((f, i) => (
              <FindingRow key={`${type}-${i}`} f={f} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
