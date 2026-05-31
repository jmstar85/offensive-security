import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Badge } from "../ui/badge";
import api from "../../api/client";

interface Understanding {
  target_kind: string;
  detected_stack: string[];
  entry_points: string[];
  constraints: string[];
  revision_no: number;
}

interface Props {
  sessionId: string;
}

export function UnderstandingPanel({ sessionId }: Props) {
  const [data, setData] = useState<Understanding | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<Understanding>(`/pentest-sessions/${sessionId}/understanding`)
      .then((res) => {
        setData(res.data);
        setLoading(false);
      })
      .catch((err) => {
        if (err.response?.status === 404) {
          setError("No understanding generated yet");
        } else {
          setError("Failed to load understanding");
        }
        setLoading(false);
      });
  }, [sessionId]);

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-semibold flex items-center justify-between">
          <span>Understanding</span>
          {data && (
            <Badge variant="secondary" className="text-xs">
              rev {data.revision_no}
            </Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {loading && (
          <p className="text-muted-foreground text-center py-4">Loading...</p>
        )}
        {error && (
          <p className="text-muted-foreground text-center py-4">{error}</p>
        )}
        {data && (
          <>
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground uppercase tracking-wide">Target kind</p>
              <p className="font-medium">{data.target_kind}</p>
            </div>

            {data.detected_stack.length > 0 && (
              <div className="space-y-1">
                <p className="text-xs text-muted-foreground uppercase tracking-wide">Detected stack</p>
                <div className="flex flex-wrap gap-1.5">
                  {data.detected_stack.map((s) => (
                    <Badge key={s} variant="secondary" className="text-xs">
                      {s}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            {data.entry_points.length > 0 && (
              <div className="space-y-1">
                <p className="text-xs text-muted-foreground uppercase tracking-wide">Entry points</p>
                <ul className="space-y-0.5">
                  {data.entry_points.map((ep, i) => (
                    <li key={i} className="text-sm text-foreground pl-2 border-l border-border">
                      {ep}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {data.constraints.length > 0 && (
              <div className="space-y-1">
                <p className="text-xs text-muted-foreground uppercase tracking-wide">Constraints</p>
                <ul className="space-y-0.5">
                  {data.constraints.map((c, i) => (
                    <li key={i} className="text-sm text-muted-foreground pl-2 border-l border-border">
                      {c}
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
