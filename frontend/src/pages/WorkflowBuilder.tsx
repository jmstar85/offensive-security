import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  type Connection,
  type Node,
  type NodeTypes,
} from "reactflow";
import "reactflow/dist/style.css";
import { useParams, useNavigate, useLocation } from "react-router-dom";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { getCatalog } from "../api/agents";
import { createSession, createWorkflow, getWorkflow, updateWorkflow } from "../api/client";
import { Input, Label } from "../components/ui/input";

interface AgentEntry {
  agent_type: string;
  category?: string;
  risk_level: string;
  capabilities: string[];
  options_schema?: JsonSchema;
  executable?: boolean;
}

interface AgentNodeData {
  agent_type: string;
  risk_level: string;
  config: Record<string, unknown>;
}

interface JsonSchema {
  type?: string;
  properties?: Record<string, JsonSchemaProperty>;
}

interface JsonSchemaProperty {
  type?: string;
  enum?: string[];
  default?: unknown;
  description?: string;
  minimum?: number;
  maximum?: number;
  items?: { type?: string; enum?: string[] };
}

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
  const { id: projectId, workflowId } = useParams<{ id: string; workflowId?: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const initialAgent = useMemo(() => new URLSearchParams(location.search).get("agent"), [location.search]);

  const [nodes, setNodes, onNodesChange] = useNodesState<AgentNodeData>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [catalog, setCatalog] = useState<AgentEntry[]>([]);
  const [workflowName, setWorkflowName] = useState("New Workflow");
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const initialAgentAdded = useRef(false);
  const workflowLoaded = useRef(false);

  const selectedNode = nodes.find((node) => node.id === selectedNodeId) ?? null;
  const selectedAgent = selectedNode
    ? catalog.find((agent) => agent.agent_type === selectedNode.data.agent_type)
    : null;

  const addAgentNode = useCallback((agent: AgentEntry, position = { x: 120, y: 120 }) => {
    if (agent.executable === false) return;
    const newNode: Node<AgentNodeData> = {
      id: nextId(),
      type: "agentNode",
      position,
      data: { agent_type: agent.agent_type, risk_level: agent.risk_level, config: defaultConfig(agent.options_schema) },
    };
    setNodes(nds => nds.concat(newNode));
    setSelectedNodeId(newNode.id);
  }, [setNodes]);

  useEffect(() => {
    getCatalog().then(data => {
      const all: AgentEntry[] = [
        ...data.tool_agents.map((a: AgentEntry) => ({ ...a, category: "tool" })),
        ...data.domain_agents,
      ];
      setCatalog(all);
      if (initialAgent && !initialAgentAdded.current) {
        const match = all.find(agent => agent.agent_type === initialAgent && agent.executable !== false);
        if (match) {
          initialAgentAdded.current = true;
          addAgentNode(match);
        }
      }
    }).catch(() => setError("Failed to load agent catalog"));
  }, [addAgentNode, initialAgent]);

  useEffect(() => {
    if (!workflowId || catalog.length === 0 || workflowLoaded.current) return;
    workflowLoaded.current = true;
    getWorkflow(workflowId).then((res) => {
      const workflow = res.data;
      const dag = workflow.dag ?? {};
      const uiNodes = new Map<string, { position?: { x: number; y: number } }>(
        (dag.ui?.nodes ?? []).map((node: any) => [node.id, node])
      );
      setWorkflowName(workflow.name ?? "Workflow");
      setNodes((dag.steps ?? []).map((step: any, index: number) => {
        const agentType = step.agent ?? step.agent_type;
        const agent = catalog.find(item => item.agent_type === agentType);
        return {
          id: step.id,
          type: "agentNode",
          position: uiNodes.get(step.id)?.position ?? { x: 120 + index * 180, y: 120 },
          data: {
            agent_type: agentType,
            risk_level: agent?.risk_level ?? "medium",
            config: step.config ?? {},
          },
        };
      }));
      setEdges((dag.edges ?? []).map((edge: any, index: number) => ({
        id: edge.id ?? `${edge.source}-${edge.target}-${index}`,
        source: edge.source,
        target: edge.target,
      })));
    }).catch(() => setError("Failed to load workflow"));
  }, [catalog, setEdges, setNodes, workflowId]);

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
      const agent = catalog.find(item => item.agent_type === agentType);
      if (!agentType || !reactFlowWrapper.current) return;
      if (agent?.executable === false) return;

      const bounds = reactFlowWrapper.current.getBoundingClientRect();
      const position = {
        x: event.clientX - bounds.left - 70,
        y: event.clientY - bounds.top - 30,
      };

      addAgentNode(
        agent ?? { agent_type: agentType, risk_level: riskLevel, capabilities: [], executable: true },
        position
      );
    },
    [addAgentNode, catalog]
  );

  const buildDag = () => ({
    version: 1,
    kind: "workflow",
    steps: nodes.map((n, index) => ({
      id: n.id,
      order: index + 1,
      agent: n.data.agent_type,
      action: `${n.data.agent_type}_execute`,
      config: n.data.config,
    })),
    edges: edges.map(e => ({ source: e.source, target: e.target, condition: "success" })),
    ui: {
      nodes: nodes.map(n => ({ id: n.id, position: n.position })),
    },
  });

  const saveWorkflow = async () => {
    if (!projectId) return;
    setSaving(true);
    setError(null);
    try {
      const payload = {
        name: workflowName,
        description: "",
        dag: buildDag(),
      };
      const res = workflowId
        ? await updateWorkflow(workflowId, payload)
        : await createWorkflow(projectId, payload);
      return res.data;
    } catch {
      setError("Failed to save workflow");
      return null;
    } finally {
      setSaving(false);
    }
  };

  const handleSave = async () => {
    const saved = await saveWorkflow();
    if (saved && projectId) {
      navigate(`/projects/${projectId}`);
    }
  };

  const handleRun = async () => {
    if (!projectId) return;
    setRunning(true);
    setError(null);
    try {
      const saved = await saveWorkflow();
      const idToRun = workflowId || saved?.id;
      if (!idToRun) return;
      const session = await createSession(projectId, `Run workflow: ${workflowName}`, idToRun);
      navigate(`/sessions/${session.data.id}/monitor`);
    } catch {
      setError("Failed to run workflow");
    } finally {
      setRunning(false);
    }
  };

  const handleClear = () => {
    setNodes([]);
    setEdges([]);
    setSelectedNodeId(null);
  };

  const updateSelectedConfig = (key: string, value: unknown) => {
    if (!selectedNode) return;
    setNodes(nds => nds.map(node => {
      if (node.id !== selectedNode.id) return node;
      return {
        ...node,
        data: {
          ...node.data,
          config: { ...node.data.config, [key]: value },
        },
      };
    }));
  };

  return (
    <div className="flex flex-col h-screen bg-background">
      <div className="flex items-center gap-3 px-4 py-3 border-b border-border bg-card">
        <input
          value={workflowName}
          onChange={e => setWorkflowName(e.target.value)}
          className="bg-transparent text-foreground text-sm font-semibold focus:outline-none border-b border-transparent focus:border-border px-1"
        />
        <div className="flex-1" />
        {error && <span className="text-xs text-destructive">{error}</span>}
        <Button variant="ghost" size="sm" onClick={handleClear}>Clear</Button>
        <Button size="sm" onClick={handleSave} disabled={saving}>
          {saving ? "Saving…" : "Save Workflow"}
        </Button>
        <Button size="sm" variant="secondary" onClick={handleRun} disabled={running || saving || nodes.length === 0}>
          {running ? "Running…" : "Save & Run"}
        </Button>
      </div>

      <div className="flex flex-1 overflow-hidden">
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
                  if (agent.executable === false) return;
                  e.dataTransfer.setData("application/agenttype", agent.agent_type);
                  e.dataTransfer.setData("application/risklevel", agent.risk_level);
                  e.dataTransfer.effectAllowed = "move";
                }}
                className={`flex items-center gap-2 px-3 py-2 rounded-md border border-border bg-background transition-colors ${
                  agent.executable === false
                    ? "opacity-50 cursor-not-allowed"
                    : "hover:bg-accent cursor-grab active:cursor-grabbing"
                }`}
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
                {agent.executable === false && (
                  <Badge variant="outline" className="text-xs flex-shrink-0">ref</Badge>
                )}
              </div>
            ))}
          </div>
        </aside>

        <div ref={reactFlowWrapper} className="flex-1 relative">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onDrop={onDrop}
            onDragOver={onDragOver}
            onNodeClick={(_, node) => setSelectedNodeId(node.id)}
            onPaneClick={() => setSelectedNodeId(null)}
            nodeTypes={nodeTypes}
            fitView
          >
            <Background />
            <Controls />
            <MiniMap />
          </ReactFlow>
        </div>

        {selectedNode && (
          <aside className="w-64 border-l border-border bg-card flex flex-col overflow-y-auto">
            <div className="px-4 py-3 border-b border-border">
              <p className="text-sm font-semibold text-foreground capitalize">
                {selectedNode.data.agent_type.replace(/_/g, " ")}
              </p>
              <p className="text-xs text-muted-foreground">Node: {selectedNode.id}</p>
            </div>
            <div className="p-4 space-y-4">
              {selectedAgent?.options_schema?.properties ? (
                Object.entries(selectedAgent.options_schema.properties).map(([key, schema]) => (
                  <SchemaField
                    key={key}
                    name={key}
                    schema={schema}
                    value={selectedNode.data.config[key]}
                    onChange={(value) => updateSelectedConfig(key, value)}
                  />
                ))
              ) : (
                <p className="text-xs text-muted-foreground">No configurable options for this agent.</p>
              )}
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}

function defaultConfig(schema?: JsonSchema): Record<string, unknown> {
  const config: Record<string, unknown> = {};
  Object.entries(schema?.properties ?? {}).forEach(([key, property]) => {
    if (property.default !== undefined) config[key] = property.default;
  });
  return config;
}

function SchemaField({
  name,
  schema,
  value,
  onChange,
}: {
  name: string;
  schema: JsonSchemaProperty;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const label = name.replace(/_/g, " ");
  const current = value ?? schema.default ?? (schema.type === "array" ? [] : schema.type === "boolean" ? false : "");

  if (schema.type === "boolean") {
    return (
      <label className="flex items-center gap-2 text-sm text-foreground">
        <input
          type="checkbox"
          checked={Boolean(current)}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span className="capitalize">{label}</span>
      </label>
    );
  }

  if (schema.enum?.length) {
    return (
      <div className="space-y-1.5">
        <Label className="capitalize">{label}</Label>
        <select
          value={String(current)}
          onChange={(event) => onChange(event.target.value)}
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
        >
          {schema.enum.map((option) => (
            <option key={option} value={option}>{option}</option>
          ))}
        </select>
      </div>
    );
  }

  if (schema.type === "array") {
    return (
      <div className="space-y-1.5">
        <Label className="capitalize">{label}</Label>
        <Input
          value={Array.isArray(current) ? current.join(", ") : String(current)}
          placeholder={schema.description ?? "comma-separated values"}
          onChange={(event) => onChange(event.target.value.split(",").map(item => item.trim()).filter(Boolean))}
        />
      </div>
    );
  }

  if (schema.type === "integer" || schema.type === "number") {
    return (
      <div className="space-y-1.5">
        <Label className="capitalize">{label}</Label>
        <Input
          type="number"
          min={schema.minimum}
          max={schema.maximum}
          value={Number(current)}
          onChange={(event) => onChange(Number(event.target.value))}
        />
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      <Label className="capitalize">{label}</Label>
      <Input
        value={String(current)}
        placeholder={schema.description}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}
