import React, { useCallback, useEffect, useRef, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  type Node,
  type Edge,
} from "reactflow";
import "reactflow/dist/style.css";
import { useParams } from "react-router-dom";
import { cn } from "../lib/utils";

interface AgentNodeData {
  agent_type: string;
  status: "idle" | "running" | "done" | "failed";
  label: string;
}

function statusColor(status: string) {
  switch (status) {
    case "running": return "border-blue-500 bg-blue-500/10";
    case "done": return "border-green-500 bg-green-500/10";
    case "failed": return "border-red-500 bg-red-500/10";
    default: return "border-border bg-muted/20";
  }
}

function LiveAgentNode({ data }: { data: AgentNodeData }) {
  return (
    <div className={cn(
      "border-2 rounded-lg px-4 py-3 min-w-[140px] text-center shadow-lg transition-colors",
      statusColor(data.status),
      data.status === "running" && "animate-pulse-slow"
    )}>
      <div className="text-xs font-bold text-foreground capitalize">
        {data.label.replace(/_/g, " ")}
      </div>
      <div className={cn("text-xs capitalize mt-0.5", {
        "text-blue-400": data.status === "running",
        "text-green-400": data.status === "done",
        "text-red-400": data.status === "failed",
        "text-muted-foreground": data.status === "idle",
      })}>
        {data.status}
      </div>
    </div>
  );
}

const nodeTypes = { liveAgent: LiveAgentNode };

export default function InteractionDashboard() {
  const { id: sessionId } = useParams<{ id: string }>();
  const [nodes, setNodes] = useState<Node<AgentNodeData>[]>([]);
  const [edges] = useState<Edge[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const logsEndRef = useRef<HTMLDivElement>(null);

  // KPI state
  const activeCount = nodes.filter(n => n.data.status === "running").length;
  const doneCount = nodes.filter(n => n.data.status === "done").length;
  const totalCount = nodes.length;
  const progressPct = totalCount > 0 ? Math.round((doneCount / totalCount) * 100) : 0;
  const findingsCount = logs.filter(l => l.includes("[finding]")).length;

  useEffect(() => {
    if (!sessionId) return;
    const wsUrl = `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/api/v1/ws/${sessionId}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onmessage = event => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.event_type === "log") {
          setLogs(prev => [...prev.slice(-499), msg.data?.line ?? JSON.stringify(msg.data)]);
        } else if (msg.event_type === "status") {
          const status = msg.data?.status;
          const agentType = msg.agent_type;
          setNodes(prev => {
            const existing = prev.find(n => n.data.agent_type === agentType);
            if (existing) {
              return prev.map(n =>
                n.data.agent_type === agentType
                  ? { ...n, data: { ...n.data, status: status === "completed" ? "done" : status === "running" ? "running" : status === "failed" ? "failed" : "idle" } }
                  : n
              );
            }
            return [
              ...prev,
              {
                id: `${agentType}_${Date.now()}`,
                type: "liveAgent",
                position: { x: prev.length * 200, y: 100 },
                data: { agent_type: agentType, status: "running", label: agentType },
              },
            ];
          });
        }
      } catch {
        setLogs(prev => [...prev.slice(-499), event.data]);
      }
    };

    return () => { ws.close(); };
  }, [sessionId]);

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  return (
    <div className="flex flex-col h-screen bg-background">
      {/* KPI bar */}
      <div className="flex items-center gap-6 px-6 py-3 border-b border-border bg-card">
        <h1 className="text-sm font-bold text-foreground">Live Dashboard</h1>
        <div className="flex gap-4 text-xs">
          <span className="text-muted-foreground">Active Agents: <span className="text-blue-400 font-semibold">{activeCount}</span></span>
          <span className="text-muted-foreground">Findings: <span className="text-yellow-400 font-semibold">{findingsCount}</span></span>
          <span className="text-muted-foreground">Progress: <span className="text-green-400 font-semibold">{progressPct}%</span></span>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* React Flow canvas */}
        <div className="flex-1 relative">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodeClick={(_, node) => setSelectedNodeId(node.id)}
            onPaneClick={() => setSelectedNodeId(null)}
            fitView
          >
            <Background />
            <Controls />
          </ReactFlow>
          {nodes.length === 0 && (
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
              <p className="text-muted-foreground text-sm">Waiting for agent activity…</p>
            </div>
          )}
        </div>

        {/* Right log panel */}
        <aside className="w-80 border-l border-border bg-card flex flex-col">
          <div className="px-4 py-3 border-b border-border">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
              {selectedNodeId ? `Logs — ${selectedNodeId}` : "Event Stream"}
            </p>
          </div>
          <div className="flex-1 overflow-y-auto p-3 font-mono text-xs text-muted-foreground space-y-0.5">
            {logs.map((line, i) => (
              <div key={i} className="break-all">{line}</div>
            ))}
            {logs.length === 0 && (
              <div className="text-center pt-8">No events yet</div>
            )}
            <div ref={logsEndRef} />
          </div>
        </aside>
      </div>
    </div>
  );
}
