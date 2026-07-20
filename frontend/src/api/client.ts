import axios from 'axios'
import type { ApprovalFlags } from '../components/ApprovalPreviewPanel'

const api = axios.create({ baseURL: '/api/v1', timeout: 60000 })

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      window.location.href = '/login'
    }
    return Promise.reject(err)
  }
)

export default api

// Auth
export const login = (email: string, password: string) =>
  api.post('/auth/login', { email, password })
export const register = (
  email: string,
  password: string,
  full_name: string,
  team_name?: string
) => api.post('/auth/register', { email, password, full_name, team_name })
export const resetPassword = (
  email: string,
  current_password: string,
  new_password: string
) => api.post('/auth/reset-password', { email, current_password, new_password })
export const getMe = () => api.get('/auth/me')

// Projects
export const listProjects = () => api.get('/projects/')
export const createProject = (data: object) => api.post('/projects/', data)
export const getProject = (id: string) => api.get(`/projects/${id}`)
export const deleteProject = (id: string) => api.delete(`/projects/${id}`)
export const listAllProjects = () => api.get('/projects/all/admin')

// Sessions
export const createSession = (project_id: string, prompt: string, workflow_id?: string) =>
  api.post('/sessions/', { project_id, prompt, workflow_id })
export const listSessions = (project_id?: string) =>
  api.get('/sessions/', { params: project_id ? { project_id } : {} })
export const getSession = (id: string) => api.get(`/sessions/${id}`)
export const killSession = (id: string) => api.post(`/sessions/${id}/kill`)
// Permanently delete a session + its child rows (204). 409 while running.
export const deleteSession = (id: string) => api.delete(`/pentest-sessions/${id}`)

// Replay sources for /flow panels (Terminal + Tasks). Additive — the panels
// already render live over WS; these let a reloaded panel rebuild prior state.
// Terminal history returns ordered rows { seq, line, agent_type, execution_id,
// created_at } with seq ascending and only seq > after_seq.
export const getTerminalHistory = (id: string, afterSeq = 0) =>
  api.get(`/sessions/${id}/terminal?after_seq=${afterSeq}`)
// Executions returns { id, agent_type, status, step_order, started_at,
// ended_at } used to overlay completed/failed status onto seeded Tasks rows.
export const getExecutions = (id: string) => api.get(`/sessions/${id}/executions`)

// Workflows
export const listWorkflows = (project_id: string) =>
  api.get(`/projects/${project_id}/workflows`)
export const createWorkflow = (project_id: string, data: object) =>
  api.post(`/projects/${project_id}/workflows`, data)
export const getWorkflow = (workflow_id: string) => api.get(`/workflows/${workflow_id}`)
export const updateWorkflow = (workflow_id: string, data: object) =>
  api.patch(`/workflows/${workflow_id}`, data)
export const deleteWorkflow = (workflow_id: string) => api.delete(`/workflows/${workflow_id}`)

// Reports
export const listReports = (session_id?: string) =>
  api.get('/reports/', { params: session_id ? { session_id } : {} })
export const getReport = (id: string) => api.get(`/reports/${id}`)
export const downloadPdf = (id: string) =>
  api.get(`/reports/${id}/pdf`, { responseType: 'blob' })

// Admin: Users
export interface TeamRow {
  id: string
  name: string
}
export const listUsers = () => api.get('/users/')
export const listTeams = () => api.get<TeamRow[]>('/users/teams')
export const createUser = (data: {
  email: string
  full_name: string
  password: string
  role: string
  team_id?: string | null
  team_name?: string | null
}) => api.post('/users/', data)
export const updateUserRole = (id: string, role: string) =>
  api.patch(`/users/${id}/role`, { role })
export const deactivateUser = (id: string) => api.delete(`/users/${id}`)

// Admin: Audit Logs
export const listAuditLogs = (limit = 100) =>
  api.get('/audit-logs/', { params: { limit } })

// Agent catalog — real executable tool agents (agent_type + capabilities +
// tier). Used to ground the Draft plan editor so manual edits can only select
// tools that actually exist. Returns { tool_agents: [...], domain_agents: [...] }.
export const getAgentCatalog = () => api.get('/agents/catalog')

// Domain agents (plan v3.2.1 §3 / P2)
export const listDomainAgents = () => api.get('/domain-agents/')
export const getDomainAgent = (slug: string) => api.get(`/domain-agents/${slug}`)

// Pentest sessions — workflow chat flow (plan v3.2.1 §4 / P3)
export const createPentestDraft = (data: {
  project_id: string
  initial_prompt: string
  model_id?: string | null
  domain_agent_slug?: string | null
  // Newflow additive fields (PR8). `provider` persists as session
  // llm_provider_pref; `model_map` is the per-role override dict (empty =
  // session default only); `mode` is "automation" | "assistant", fixed at
  // create. All optional/backward-compatible — omitting them yields the
  // server defaults (NULL / {} / "automation").
  provider?: 'anthropic' | 'ollama' | 'openai' | 'copilot' | null
  model_map?: Record<string, string>
  mode?: 'automation' | 'assistant'
  // Workflow-template preset selection (recon-only/web-pentest/full-scope,
  // from getTemplates()). NOTE: CreateDraftBody does not yet have a
  // template/plan_json seed field, so the backend currently ignores this
  // (Pydantic extra="ignore") — it is forwarded so a follow-up backend PR
  // can wire it to seed draft_plan_json/the deterministic lane without a
  // frontend change. Until then the template selection only prefills the
  // objective textarea client-side.
  template_id?: string | null
}) => api.post('/pentest-sessions/', data)

export const getPentestSession = (id: string) =>
  api.get(`/pentest-sessions/${id}`)

export const sendPentestMessage = (id: string, content: string) =>
  api.post(`/pentest-sessions/${id}/messages`, { content })

// Interview history (auto-kickoff replay). Returns the ordered WorkflowMessage
// rows so a reloaded /flow/:id or /pentest-sessions/:id replays the prompt +
// prior turns instead of landing on an empty panel.
export const getPentestMessages = (id: string) =>
  api.get(`/pentest-sessions/${id}/messages`)

// Assistant mode (newflow PR7/PR8) — interactive chat turn. 409 when
// session.mode != "assistant" or a turn is already in progress (per-session
// turn mutex); the caller surfaces that as an inline notice rather than a
// hard error.
export interface AssistantMessageResponse {
  role: string
  content: string
  [key: string]: unknown
}

export const sendAssistantMessage = (id: string, content: string) =>
  api.post<AssistantMessageResponse>(`/pentest-sessions/${id}/assistant/messages`, { content })

export const forceReadyForReview = (id: string, override_reason: string) =>
  api.post(`/pentest-sessions/${id}/force-ready-for-review`, { override_reason })

export const getApprovalPreview = (id: string) =>
  api.get(`/pentest-sessions/${id}/approval-preview`)

export const approvePentestSession = (
  id: string,
  approval_flags?: ApprovalFlags,
) =>
  api.post(
    `/pentest-sessions/${id}/approve`,
    approval_flags ? { approval_flags } : undefined,
  )

export const rejectPentestSession = (id: string) =>
  api.post(`/pentest-sessions/${id}/reject`)

// Rescope (plan v3.2.1 §5 / P4)
export const listPendingRescopes = (id: string) =>
  api.get(`/pentest-sessions/${id}/rescope-pending`)

export const decideRescope = (
  id: string,
  body: { rescope_id: string; accept: string[]; reject: string[]; reason?: string }
) => api.post(`/pentest-sessions/${id}/rescope`, body)

// v4.0 P3-main — Agents tab data source.
export interface MsgChainRow {
  id: string
  role_name: string
  status: string
  retries: number
  started_at: string
  ended_at: string | null
  message_count: number
}

export const getMsgChains = (sessionId: string) =>
  api.get<MsgChainRow[]>(`/pentest-sessions/${sessionId}/msgchains`)

// W4/PR4.4 — FlowConsoleHeader data sources.
export interface AgentFamilyRow {
  id: string
  family_kind: string
  status: string
  depth: number
  max_depth: number
  context_json: Record<string, unknown> | null
  tokens_consumed: number
}

export const getAgentFamilies = (sessionId: string) =>
  api.get<AgentFamilyRow[]>(`/pentest-sessions/${sessionId}/agent-families`)

export interface PentestSessionRow {
  id: string
  cost_usd_accum: number | null
  status: string
  coordinator_revision_no: number
}

export const getPentestSessionCoordinator = (sessionId: string) =>
  api.get<PentestSessionRow>(`/pentest-sessions/${sessionId}`)
