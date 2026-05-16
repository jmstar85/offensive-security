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
export const register = (email: string, password: string, full_name: string, team_name: string) =>
  api.post('/auth/register', { email, password, full_name, team_name })
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
export const listUsers = () => api.get('/users/')
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
}) => api.post('/pentest-sessions/', data)

export const getPentestSession = (id: string) =>
  api.get(`/pentest-sessions/${id}`)

export const sendPentestMessage = (id: string, content: string) =>
  api.post(`/pentest-sessions/${id}/messages`, { content })

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
