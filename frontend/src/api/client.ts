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

// Projects
export const listProjects = () => api.get('/projects/')
export const createProject = (data: object) => api.post('/projects/', data)
export const getProject = (id: string) => api.get(`/projects/${id}`)

// Sessions
export const createSession = (project_id: string, prompt: string) =>
  api.post('/sessions/', { project_id, prompt })
export const listSessions = (project_id?: string) =>
  api.get('/sessions/', { params: project_id ? { project_id } : {} })
export const getSession = (id: string) => api.get(`/sessions/${id}`)
export const killSession = (id: string) => api.post(`/sessions/${id}/kill`)

// Reports
export const listReports = (session_id?: string) =>
  api.get('/reports/', { params: session_id ? { session_id } : {} })
export const getReport = (id: string) => api.get(`/reports/${id}`)
export const downloadPdf = (id: string) =>
  api.get(`/reports/${id}/pdf`, { responseType: 'blob' })
