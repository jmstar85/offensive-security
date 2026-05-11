import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { SidebarShell } from './components/layout/SidebarShell'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Projects from './pages/Projects'
import ProjectDetail from './pages/ProjectDetail'
import Monitor from './pages/Monitor'
import Reports from './pages/Reports'
import AgentCatalog from './pages/AgentCatalog'
import WorkflowBuilder from './pages/WorkflowBuilder'
import InteractionDashboard from './pages/InteractionDashboard'

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

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<Shell><Dashboard /></Shell>} />
        <Route path="/projects" element={<Shell><Projects /></Shell>} />
        <Route path="/projects/:id" element={<Shell><ProjectDetail /></Shell>} />
        <Route path="/sessions/:id/monitor" element={<Shell><Monitor /></Shell>} />
        <Route path="/reports" element={<Shell><Reports /></Shell>} />
        <Route path="/agents" element={<Shell><AgentCatalog /></Shell>} />
        <Route path="/workflows" element={<Shell><AgentCatalog /></Shell>} />
        <Route path="/projects/:id/workflows/new" element={<PrivateRoute><WorkflowBuilder /></PrivateRoute>} />
        <Route path="/projects/:id/dashboard" element={<PrivateRoute><InteractionDashboard /></PrivateRoute>} />
        <Route path="/sessions/:id/dashboard" element={<PrivateRoute><InteractionDashboard /></PrivateRoute>} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
