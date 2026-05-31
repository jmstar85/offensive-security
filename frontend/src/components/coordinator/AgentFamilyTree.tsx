import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Badge } from "../ui/badge";
import api from "../../api/client";
import { useFeatureFlags } from "../../hooks/useFeatureFlags";

export interface AgentFamilyInstanceDto {
  id: string;
  family_kind: "recon" | "exploit" | "extraction";
  parent_family_id: string | null;
  status: "active" | "completed" | "aborted";
  depth: number;
  max_depth: number;
}

interface Props {
  sessionId: string;
}

const KIND_LABEL: Record<AgentFamilyInstanceDto["family_kind"], string> = {
  recon: "Recon",
  exploit: "Exploit",
  extraction: "Extraction",
};

const STATUS_VARIANT: Record<
  AgentFamilyInstanceDto["status"],
  "default" | "secondary" | "destructive"
> = {
  active: "default",
  completed: "secondary",
  aborted: "destructive",
};

function DepthBar({ depth, maxDepth }: { depth: number; maxDepth: number }) {
  const pct = maxDepth > 0 ? Math.round((depth / maxDepth) * 100) : 0;
  return (
    <div className="flex items-center gap-1.5 min-w-0">
      <div className="h-1.5 flex-1 rounded-full bg-muted overflow-hidden">
        <div
          className="h-full rounded-full bg-primary transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs text-muted-foreground tabular-nums shrink-0">
        {depth}/{maxDepth}
      </span>
    </div>
  );
}

function FamilyRow({
  family,
  indentLevel,
}: {
  family: AgentFamilyInstanceDto;
  indentLevel: number;
}) {
  return (
    <div
      className="flex flex-col gap-1 py-1.5"
      style={{ paddingLeft: `${indentLevel * 12}px` }}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 min-w-0">
          {indentLevel > 0 && (
            <span className="text-muted-foreground text-xs shrink-0">└</span>
          )}
          <span className="text-sm font-medium truncate">
            {KIND_LABEL[family.family_kind]}
          </span>
          <span className="text-xs text-muted-foreground font-mono truncate">
            {family.id.slice(0, 8)}
          </span>
        </div>
        <Badge variant={STATUS_VARIANT[family.status]} className="text-xs shrink-0">
          {family.status}
        </Badge>
      </div>
      <DepthBar depth={family.depth} maxDepth={family.max_depth} />
    </div>
  );
}

function buildTree(
  families: AgentFamilyInstanceDto[],
  parentId: string | null,
  depth: number
): React.ReactNode[] {
  return families
    .filter((f) => f.parent_family_id === parentId)
    .flatMap((f) => [
      <FamilyRow key={f.id} family={f} indentLevel={depth} />,
      ...buildTree(families, f.id, depth + 1),
    ]);
}

export function AgentFamilyTree({ sessionId }: Props) {
  const flags = useFeatureFlags();
  const [data, setData] = useState<AgentFamilyInstanceDto[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!flags?.osa_xbow_families_enabled) {
      setLoading(false);
      return;
    }
    api
      .get<AgentFamilyInstanceDto[]>(`/pentest-sessions/${sessionId}/agent-families`)
      .then((res) => {
        setData(res.data);
        setLoading(false);
      })
      .catch((err) => {
        if (err.response?.status === 404) {
          setError("No families spawned yet — feature gated by osa_xbow_families_enabled");
        } else {
          setError("Failed to load agent families");
        }
        setLoading(false);
      });
  }, [sessionId, flags?.osa_xbow_families_enabled]);

  if (!flags?.osa_xbow_families_enabled) {
    return null;
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-semibold">Agent Family Tree</CardTitle>
      </CardHeader>
      <CardContent className="text-sm">
        {loading && (
          <p className="text-muted-foreground text-center py-4">Loading...</p>
        )}
        {error && (
          <p className="text-muted-foreground text-center py-4">{error}</p>
        )}
        {data && data.length === 0 && (
          <p className="text-muted-foreground text-center py-4">
            Coordinator has not requested family spawning for this session yet.
          </p>
        )}
        {data && data.length > 0 && (
          <div className="divide-y divide-border">
            <div className="pb-1.5">
              <span className="text-xs text-muted-foreground uppercase tracking-wide">
                SessionManagementAgent
              </span>
            </div>
            <div className="pt-1">{buildTree(data, null, 1)}</div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
