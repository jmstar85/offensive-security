import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Badge } from "../ui/badge";
import api from "../../api/client";

interface FamilyRecommendation {
  family_kind: string;
  rationale: string;
  depth_hint: string;
}

interface PlanOfWork {
  objectives: string[];
  family_recommendations: FamilyRecommendation[];
  ordered_phases: string[];
  success_criteria: string[];
  revision_no: number;
}

interface Props {
  sessionId: string;
}

const PHASE_LABELS: Record<string, string> = {
  recon: "Recon",
  exploit: "Exploit",
  extraction: "Extraction",
};

function PhasesPipeline({ phases }: { phases: string[] }) {
  const display = phases.length > 0 ? phases : ["recon", "exploit", "extraction"];
  return (
    <div className="flex items-center gap-0">
      {display.map((phase, i) => (
        <div key={phase} className="flex items-center">
          <div
            className={`
              px-3 py-1.5 text-xs font-medium bg-primary/10 text-primary border border-primary/20
              ${i === 0 ? "rounded-l-full" : ""}
              ${i === display.length - 1 ? "rounded-r-full" : ""}
            `}
          >
            {PHASE_LABELS[phase] ?? phase}
          </div>
          {i < display.length - 1 && (
            <div className="w-0 h-0 border-t-[10px] border-b-[10px] border-l-[8px] border-t-transparent border-b-transparent border-l-primary/20 -ml-px z-10" />
          )}
        </div>
      ))}
    </div>
  );
}

export function PlanOfWorkPanel({ sessionId }: Props) {
  const [data, setData] = useState<PlanOfWork | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<PlanOfWork>(`/pentest-sessions/${sessionId}/plan-of-work`)
      .then((res) => {
        setData(res.data);
        setLoading(false);
      })
      .catch((err) => {
        if (err.response?.status === 404) {
          setError("No plan of work generated yet");
        } else {
          setError("Failed to load plan of work");
        }
        setLoading(false);
      });
  }, [sessionId]);

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-semibold flex items-center justify-between">
          <span>Plan of Work</span>
          {data && (
            <Badge variant="secondary" className="text-xs">
              rev {data.revision_no}
            </Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        {loading && (
          <p className="text-muted-foreground text-center py-4">Loading...</p>
        )}
        {error && (
          <p className="text-muted-foreground text-center py-4">{error}</p>
        )}
        {data && (
          <>
            {data.objectives.length > 0 && (
              <div className="space-y-1">
                <p className="text-xs text-muted-foreground uppercase tracking-wide">Objectives</p>
                <ul className="space-y-0.5">
                  {data.objectives.map((obj, i) => (
                    <li key={i} className="text-sm text-foreground pl-2 border-l border-border">
                      {obj}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {data.ordered_phases.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs text-muted-foreground uppercase tracking-wide">Phases</p>
                <PhasesPipeline phases={data.ordered_phases} />
              </div>
            )}

            {data.family_recommendations.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs text-muted-foreground uppercase tracking-wide">Family recommendations</p>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-border text-left text-muted-foreground">
                        <th className="pb-1.5 pr-3 font-medium">Family</th>
                        <th className="pb-1.5 pr-3 font-medium">Rationale</th>
                        <th className="pb-1.5 font-medium">Depth</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.family_recommendations.map((rec, i) => (
                        <tr key={i} className="border-b border-border last:border-0">
                          <td className="py-1.5 pr-3 font-medium">{rec.family_kind}</td>
                          <td className="py-1.5 pr-3 text-muted-foreground">{rec.rationale}</td>
                          <td className="py-1.5">
                            <Badge variant="secondary" className="text-xs">{rec.depth_hint}</Badge>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {data.success_criteria.length > 0 && (
              <div className="space-y-1">
                <p className="text-xs text-muted-foreground uppercase tracking-wide">Success criteria</p>
                <ul className="space-y-0.5">
                  {data.success_criteria.map((sc, i) => (
                    <li key={i} className="text-sm text-foreground pl-2 border-l border-border">
                      {sc}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
