import { useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { listProjects } from "../api/client";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";

export default function Workflows() {
  const location = useLocation();
  const [projects, setProjects] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);

  const agent = useMemo(() => {
    const params = new URLSearchParams(location.search);
    return params.get("agent") || "";
  }, [location.search]);

  useEffect(() => {
    listProjects()
      .then((res) => setProjects(res.data))
      .catch(() => setError("Failed to load projects"));
  }, []);

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">Workflows</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Choose a project to build, configure, and run executable agent workflows.
        </p>
        {agent && (
          <p className="text-sm text-primary mt-2">
            Selected agent: <span className="font-mono">{agent}</span>. Pick a project to add it.
          </p>
        )}
      </div>

      {error && (
        <div className="rounded-lg border border-destructive bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {projects.map((project) => (
          <Card key={project.id}>
            <CardHeader>
              <CardTitle>{project.name}</CardTitle>
              <CardDescription>{project.client_name}</CardDescription>
            </CardHeader>
            <CardContent className="flex gap-2">
              <Button asChild size="sm">
                <Link to={`/projects/${project.id}/workflows/new${agent ? `?agent=${encodeURIComponent(agent)}` : ""}`}>
                  New Workflow
                </Link>
              </Button>
              <Button asChild variant="outline" size="sm">
                <Link to={`/projects/${project.id}`}>View Project</Link>
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>

      {projects.length === 0 && !error && (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            No projects yet. Create a project first, then build a workflow for it.
          </CardContent>
        </Card>
      )}
    </div>
  );
}
