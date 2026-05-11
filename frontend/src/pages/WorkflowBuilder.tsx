import React, { useCallback, useEffect, useRef, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  type Connection,
  type Edge,
  type Node,
  type NodeTypes,
} from "reactflow";
import "reactflow/dist/style.css";
import { useParams, useNavigate } from "react-router-dom";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { getCatalog } from "../api/agents";
import apiClient from "../api/client";

// ---- Types ----
interface AgentEntry {
  agent_type: string;
  category?: string;
  risk_level: string;
  capabilities: string[];
  options_schema?: Record<string, unknown>;
}

interface AgentNodeData {
  agent_type: string;
  risk_level: string;
  config: Record<string, unknown>;
}

// ---- Custom Node ----
function AgentNode({ data }: { data: AgentNodeData }) {
  const riskColor: Record<string, string> = {
    low: "border-green-600",
    medium: "border-yellow-600",
    high: "border-red-600",
    critical: "border-red-800",
  };
  return (
    <div className={`bg-card border-2 ${riskColor[data.risk_level] ?? "border-border"} rounded-lg px-4 py-3 min-w-[140px] text-center shadow-lg`}>
      <div className="text-xs font-bold text-foreground capitalize">
        {data.agent_type.replace(/_/g, " ")}
      </div>
      <div className="text-xs text-muted-foreground capitalize mt-0.5">{data.risk_level}</div>
    </div>
  );
}

const nodeTypes: NodeTypes = { agentNode: AgentNode };

let nodeIdCounter = 0;
function nextId() {
  return `node_${++nodeIdCounter}`;
}

export default function WorkflowBuilder() {
  const { id: projectId } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [nodes, setNodes, onNodesChange] = useNodesState<AgentNodeData>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [catalog, setCatalog] = useState<AgentEntry[]>([]);
  const [workflowName, setWorkflowName] = useState("New Workflow");
  const [saving, setSaving] = useState(false);
  const [selectedNode, setSelectedNode] = useState<Node<AgentNodeData> | null>(null);
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [reactFlowInstance, setReactFlowInstance] = useState<ReturnType<typeof ReactFlow> | null>(null);

  useEffect(() => {
    getCatalog().then(data => {
      const all: AgentEntry[] = [
        ...data.tool_agents.map((a: AgentEntry) => ({ ...a, category: "tool" })),
        ...data.domain_agents,
      ];
      setCatalog(all);
    });
  }, []);

  const onConnect = useCallback(
    (params: Connection) => setEdges(eds => addEdge(params, eds)),
    [setEdges]
  );

  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      const agentType = event.dataTransfer.getData("application/agenttype");
      const riskLevel = event.dataTransfer.getData("application/risklevel");
      if (!agentType || !reactFlowWrapper.current) return;

      const bounds = reactFlowWrapper.current.getBoundingClientRect();
      const position = {
        x: event.clientX - bounds.left - 70,
        y: event.clientY - bounds.top - 30,
      };

      const newNode: Node<AgentNodeData> = {
        id: nextId(),
        type: "agentNode",
        position,
        data: { agent_type: agentType, risk_level: riskLevel, config: {} },
      };
      setNodes(nds => nds.concat(newNode));
    },
    [setNodes]
  );

  const handleSave = async () => {
    if (!projectId) return;
    setSaving(true);
    try {
      const dag = {
        steps: nodes.map(n => ({
          id: n.id,
          agent_type: n.data.agent_type,
          config: n.data.config,
        })),
        edges: edges.map(e => ({ source: e.source, target: e.target })),
      };
      await apiClient.post(`/projects/${projectId}/workflows`, {
        name: workflowName,
        description: "",
        dag,
      });
      navigate(`/projects/${projectId}`);
    } catch (err) {
      alert("Failed to save workflow");
    } finally {
      setSaving(false);
    }
  };

  const handleClear = () => {
    setNodes([]);
    setEdges([]);
    setSelectedNode(null);
  };

  return (
    <div className="flex flex-col h-screen bg-background">
      {/* Top bar */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-border bg-card">
        <input
          value={workflowName}
          onChange={e => setWorkflowName(e.target.value)}
          className="bg-transparent text-foreground text-sm font-semibold focus:outline-none border-b border-transparent focus:border-border px-1"
        />
        <div className="flex-1" />
        <Button variant="ghost" size="sm" onClick={handleClear}>Clear</Button>
        <Button size="sm" onClick={handleSave} disabled={saving}>
          {saving ? "Saving…" : "Save Workflow"}
        </Button>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Left palette */}
        <aside className="w-56 border-r border-border bg-card flex flex-col overflow-y-auto">
          <div className="px-3 py-3 border-b border-border">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Agent Palette</p>
            <p className="text-xs text-muted-foreground mt-0.5">Drag agents to canvas</p>
          </div>
          <div className="p-2 space-y-1">
            {catalog.map(agent => (
              <div
                key={agent.agent_type}
                draggable
                onDragStart={e => {
                  e.dataTransfer.setData("application/agenttype", agent.agent_type);
                  e.dataTransfer.setData("application/risklevel", agent.risk_level);
                  e.dataTransfer.effectAllowed = "move";
                }}
                className="flex items-center gap-2 px-3 py-2 rounded-md border border-border bg-background hover:bg-accent cursor-grab active:cursor-grabbing transition-colors"
              >
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium text-foreground capitalize truncate">
                    {agent.agent_type.replace(/_/g, " ")}
                  </p>
                  <p className="text-xs text-muted-foreground capitalize">{agent.risk_level}</p>
                </div>
                <Badge
                  variant={agent.category === "tool" ? "secondary" : "outline"}
                  className="text-xs flex-shrink-0"
                >
                  {agent.category ?? "domain"}
                </Badge>
              </div>
            ))}
          </div>
        </aside>

        {/* Canvas */}
        <div ref={reactFlowWrapper} className="flex-1 relative">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onDrop={onDrop}
            onDragOver={onDragOver}
            onNodeClick={(_, node) => setSelectedNode(node as Node<AgentNodeData>)}
            onPaneClick={() => setSelectedNode(null)}
            nodeTypes={nodeTypes}
            fitView
          >
            <Background />
            <Controls />
            <MiniMap />
          </ReactFlow>
        </div>

        {/* Right config panel */}
        {selectedNode && (
          <aside className="w-64 border-l border-border bg-card flex flex-col overflow-y-auto">
            <div className="px-4 py-3 border-b border-border">
              <p className="text-sm font-semibold text-foreground capitalize">
                {selectedNode.data.agent_type.replace(/_/g, " ")}
              </p>
              <p className="text-xs text-muted-foreground">Node: {selectedNode.id}</p>
            </div>
            <div className="p-4">
              <p className="text-xs text-muted-foreground">
                Configure agent options via the catalog page. Options schema is applied at runtime.
              </p>
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}
