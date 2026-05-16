import { useEffect, useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { getMe } from './api/client'
import { SidebarShell } from './components/layout/SidebarShell'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Projects from './pages/Projects'
import ProjectDetail from './pages/ProjectDetail'
import Monitor from './pages/Monitor'
import Reports from './pages/Reports'
import Admin from './pages/Admin'
import PentestWorkflow from './pages/PentestWorkflow'
import AgentCatalog from './pages/AgentCatalog'
import WorkflowBuilder from './pages/WorkflowBuilder'
import InteractionDashboard from './pages/InteractionDashboard'
import Workflows from './pages/Workflows'

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem('token')
  return token ? <>{children}</> : <Navigate to="/login" replace />
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <PrivateRoute>
      <SidebarShell>{children}</SidebarShell>
    </PrivateRoute>
  )
}

function AdminRoute({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem('token')
  const [allowed, setAllowed] = useState<boolean | null>(null)

  useEffect(() => {
    if (!token) return
    getMe()
      .then((res) => setAllowed(res.data.role === 'admin'))
      .catch(() => setAllowed(false))
  }, [token])

  if (!token) return <Navigate to="/login" replace />
  if (allowed === null) return <div className="min-h-screen bg-background" />
  if (!allowed) return <Navigate to="/" replace />
  return <SidebarShell>{children}</SidebarShell>
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<Shell><Dashboard /></Shell>} />
        <Route path="/projects" element={<Shell><Projects /></Shell>} />
        <Route path="/projects/:id" element={<Shell><ProjectDetail /></Shell>} />
        <Route path="/pentest-sessions/new" element={<Shell><PentestWorkflow /></Shell>} />
        <Route path="/pentest-sessions/:id" element={<Shell><PentestWorkflow /></Shell>} />
        <Route path="/sessions/:id/monitor" element={<Shell><Monitor /></Shell>} />
        <Route path="/reports" element={<Shell><Reports /></Shell>} />
        <Route path="/agents" element={<Shell><AgentCatalog /></Shell>} />
        <Route path="/workflows" element={<Shell><Workflows /></Shell>} />
        <Route path="/projects/:id/workflows/new" element={<Shell><WorkflowBuilder /></Shell>} />
        <Route path="/projects/:id/workflows/:workflowId/edit" element={<Shell><WorkflowBuilder /></Shell>} />
        <Route path="/projects/:id/dashboard" element={<Shell><InteractionDashboard /></Shell>} />
        <Route path="/sessions/:id/dashboard" element={<Shell><InteractionDashboard /></Shell>} />
        <Route path="/admin" element={<AdminRoute><Admin /></AdminRoute>} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
