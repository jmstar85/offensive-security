import axios from 'axios'

const api = axios.create({ baseURL: '/api/v1' })

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
  provider?: 'anthropic' | 'ollama' | 'openai' | null
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

export const approvePentestSession = (id: string) =>
  api.post(`/pentest-sessions/${id}/approve`)

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
