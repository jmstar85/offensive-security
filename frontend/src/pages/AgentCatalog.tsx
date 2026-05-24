import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { LegacyPageBanner } from "../components/banners/LegacyPageBanner";
import { getCatalog } from "../api/agents";

interface AgentEntry {
  agent_type: string;
  category?: string;
  risk_level: string;
  description?: string;
  capabilities: string[];
  options_schema?: object;
  docker_image?: string;
  executable?: boolean;
}

interface CatalogData {
  tool_agents: AgentEntry[];
  domain_agents: AgentEntry[];
}

function riskVariant(level: string): "success" | "warning" | "destructive" | "secondary" {
  switch (level) {
    case "low": return "success";
    case "medium": return "warning";
    case "high": return "destructive";
    case "critical": return "destructive";
    default: return "secondary";
  }
}

function AgentCard({ agent }: { agent: AgentEntry }) {
  const navigate = useNavigate();
  const executable = agent.executable !== false;

  return (
    <Card className="flex flex-col">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-base capitalize">{agent.agent_type.replace(/_/g, " ")}</CardTitle>
          <div className="flex gap-1.5 flex-shrink-0">
            <Badge variant={agent.category === "tool" ? "secondary" : "outline"} className="text-xs">
              {agent.category ?? "domain"}
            </Badge>
            <Badge variant={riskVariant(agent.risk_level)} className="text-xs capitalize">
              {agent.risk_level}
            </Badge>
          </div>
        </div>
        {agent.description && (
          <CardDescription className="text-xs mt-1">{agent.description}</CardDescription>
        )}
        {agent.docker_image && (
          <CardDescription className="text-xs font-mono">{agent.docker_image}</CardDescription>
        )}
      </CardHeader>
      <CardContent className="flex-1 flex flex-col gap-3">
        <div className="flex flex-wrap gap-1">
          {agent.capabilities.map(cap => (
            <span key={cap} className="text-xs bg-accent text-accent-foreground px-2 py-0.5 rounded-full">
              {cap.replace(/_/g, " ")}
            </span>
          ))}
        </div>
        <Button
          variant={executable ? "outline" : "secondary"}
          size="sm"
          className="mt-auto w-full"
          disabled={!executable}
          onClick={() => navigate(`/workflows?agent=${encodeURIComponent(agent.agent_type)}`)}
        >
          {executable ? "Configure & Add to Workflow" : "Reference Only"}
        </Button>
      </CardContent>
    </Card>
  );
}

export default function AgentCatalog() {
  const [catalog, setCatalog] = useState<CatalogData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "tool" | "domain">("all");
  const [riskFilter, setRiskFilter] = useState<string>("all");

  useEffect(() => {
    getCatalog()
      .then(data => { setCatalog(data); setLoading(false); })
      .catch(() => { setError("Failed to load agent catalog"); setLoading(false); });
  }, []);

  const allAgents: AgentEntry[] = catalog
    ? [
        ...catalog.tool_agents.map(a => ({ ...a, category: "tool" })),
        ...catalog.domain_agents,
      ]
    : [];

  const filtered = allAgents.filter(a => {
    if (filter !== "all" && a.category !== filter) return false;
    if (riskFilter !== "all" && a.risk_level !== riskFilter) return false;
    return true;
  });

  return (
    <div className="p-6 space-y-6">
      <LegacyPageBanner pageName="AgentCatalog" />
      <div>
        <h1 className="text-2xl font-bold text-foreground">Agent Catalog</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Browse available security agents, view capabilities, and add them to your workflows.
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        {(["all", "tool", "domain"] as const).map(f => (
          <Button
            key={f}
            variant={filter === f ? "default" : "outline"}
            size="sm"
            onClick={() => setFilter(f)}
            className="capitalize"
          >
            {f}
          </Button>
        ))}
        <div className="w-px bg-border mx-1" />
        {["all", "low", "medium", "high", "critical"].map(r => (
          <Button
            key={r}
            variant={riskFilter === r ? "secondary" : "ghost"}
            size="sm"
            onClick={() => setRiskFilter(r)}
            className="capitalize"
          >
            {r}
          </Button>
        ))}
      </div>

      {loading && (
        <div className="text-center py-12 text-muted-foreground">Loading agents...</div>
      )}
      {error && (
        <div className="text-center py-12 text-destructive">{error}</div>
      )}
      {!loading && !error && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {filtered.map(agent => (
            <AgentCard key={agent.agent_type} agent={agent} />
          ))}
          {filtered.length === 0 && (
            <div className="col-span-full text-center py-12 text-muted-foreground">
              No agents match the current filters.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
