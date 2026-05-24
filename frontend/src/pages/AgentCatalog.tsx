import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { LegacyPageBanner } from "../components/banners/LegacyPageBanner";
import { getCatalog } from "../api/agents";
import { useFeatureFlags } from "../hooks/useFeatureFlags";

interface AgentEntry {
  agent_type: string;
  category?: string;
  risk_level: string;
  description?: string;
  capabilities: string[];
  options_schema?: object;
  docker_image?: string;
  executable?: boolean;
  // Backend now also returns these two — surfacing them is critical for
  // operators to understand the safety profile of a tool before adding it
  // to a workflow (especially destructive_capable tools like kali_sqlmap).
  tier?: string;
  is_destructive_capable?: boolean;
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

function tierLabel(tier?: string): string {
  if (!tier) return "";
  return tier.replace(/_/g, " ");
}

function AgentCard({ agent }: { agent: AgentEntry }) {
  const navigate = useNavigate();
  const executable = agent.executable !== false;
  const destructive = agent.is_destructive_capable === true;

  return (
    <Card className="flex flex-col">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-base capitalize">{agent.agent_type.replace(/_/g, " ")}</CardTitle>
          <div className="flex gap-1.5 flex-shrink-0 flex-wrap justify-end">
            <Badge variant={agent.category === "tool" ? "secondary" : "outline"} className="text-xs">
              {agent.category ?? "domain"}
            </Badge>
            <Badge variant={riskVariant(agent.risk_level)} className="text-xs capitalize">
              {agent.risk_level}
            </Badge>
            {agent.tier && (
              <Badge variant="outline" className="text-xs capitalize" title="Required session approval tier">
                {tierLabel(agent.tier)}
              </Badge>
            )}
            {destructive && (
              <Badge variant="destructive" className="text-xs" title="Tool can mutate target state — requires explicit operator approval">
                destructive
              </Badge>
            )}
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
  const flags = useFeatureFlags();

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
        {flags && !flags.osa_kali_backend_enabled && (
          <div
            className="mt-3 rounded-md border border-amber-700/40 bg-amber-900/20 px-3 py-2 text-xs text-amber-200"
            role="note"
          >
            Kali coexistence is disabled (OSA_KALI_BACKEND_ENABLED=false). The
            <span className="font-mono"> kali_gobuster</span>,
            <span className="font-mono"> kali_sqlmap</span>, and
            <span className="font-mono"> kali_nikto</span> tools are hidden until an
            operator enables the feature flag.
          </div>
        )}
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
