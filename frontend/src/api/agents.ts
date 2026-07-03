import apiClient from "./client";

export const getCatalog = () =>
  apiClient.get("/agents/catalog").then(r => r.data);

// Workflow templates (recon-only/web-pentest/full-scope, agents.py:53-107).
// Newflow PR8 wires this into the new-flow page's template preset chips.
export interface WorkflowTemplateStep {
  id: string;
  agent: string;
  action: string;
  config: Record<string, unknown>;
}

export interface WorkflowTemplateEdge {
  source: string;
  target: string;
}

export interface WorkflowTemplate {
  id: string;
  name: string;
  description: string;
  executable: boolean;
  steps: WorkflowTemplateStep[];
  edges: WorkflowTemplateEdge[];
}

export const getTemplates = (): Promise<{ templates: WorkflowTemplate[] }> =>
  apiClient.get("/agents/templates").then(r => r.data);
