import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getMe, listProjects, listSessions } from '../api/client'

export default function Dashboard() {
  const [projects, setProjects] = useState<any[]>([])
  const [sessions, setSessions] = useState<any[]>([])
  const [isAdmin, setIsAdmin] = useState(false)

  useEffect(() => {
    listProjects().then((r) => setProjects(r.data))
    listSessions().then((r) => setSessions(r.data))
    getMe().then((r) => setIsAdmin(r.data.role === 'admin')).catch(() => {})
  }, [])

  const activeSessions = sessions.filter((s) => s.status === 'running')

  return (
    <div className="min-h-screen bg-gray-950 p-8">
      <nav className="flex items-center justify-between mb-8">
        <h1 className="text-2xl font-bold text-red-500">OSA Platform</h1>
        <div className="flex gap-4">
          <Link to="/projects" className="text-gray-300 hover:text-white">Projects</Link>
          <Link to="/reports" className="text-gray-300 hover:text-white">Reports</Link>
          {isAdmin && <Link to="/admin" className="text-red-400 hover:text-red-300">Admin</Link>}
          <button onClick={() => { localStorage.removeItem('token'); localStorage.removeItem('user'); window.location.href = '/login' }}
            className="text-gray-400 hover:text-red-400">Logout</button>
        </div>
      </nav>

      <div className="grid grid-cols-3 gap-6 mb-8">
        {[
          { label: 'Total Projects', value: projects.length, color: 'text-blue-400' },
          { label: 'Active Sessions', value: activeSessions.length, color: 'text-green-400' },
          { label: 'Total Sessions', value: sessions.length, color: 'text-yellow-400' },
        ].map((stat) => (
          <div key={stat.label} className="bg-gray-900 rounded-xl p-6 border border-gray-800">
            <p className="text-gray-400 text-sm">{stat.label}</p>
            <p className={`text-4xl font-bold ${stat.color} mt-1`}>{stat.value}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-6">
        <div className="bg-gray-900 rounded-xl p-6 border border-gray-800">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold">Recent Projects</h2>
            <Link to="/projects" className="text-red-400 text-sm hover:text-red-300">View all</Link>
          </div>
          {projects.slice(0, 5).map((p) => (
            <Link key={p.id} to={`/projects/${p.id}`}
              className="block py-2 border-b border-gray-800 hover:text-red-400 transition">
              <span className="font-medium">{p.name}</span>
              <span className="text-gray-400 text-sm ml-2">({p.client_name})</span>
            </Link>
          ))}
          {projects.length === 0 && <p className="text-gray-500">No projects yet</p>}
        </div>

        <div className="bg-gray-900 rounded-xl p-6 border border-gray-800">
          <h2 className="text-lg font-semibold mb-4">Active Sessions</h2>
          {activeSessions.map((s) => (
            <Link key={s.id} to={`/sessions/${s.id}/monitor`}
              className="block py-2 border-b border-gray-800 hover:text-green-400 transition">
              <span className="text-green-400">●</span>
              <span className="ml-2 text-sm">{s.prompt.slice(0, 60)}...</span>
            </Link>
          ))}
          {activeSessions.length === 0 && <p className="text-gray-500">No active sessions</p>}
        </div>
      </div>
    </div>
  )
}
