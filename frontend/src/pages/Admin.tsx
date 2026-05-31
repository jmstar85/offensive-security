import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  deactivateUser,
  listAllProjects,
  listAuditLogs,
  listUsers,
  updateUserRole,
} from '../api/client'

interface UserItem {
  id: string
  email: string
  full_name: string
  role: string
  is_active: boolean
  team_id: string
}

interface AuditLogItem {
  id: string
  actor_id: string | null
  action: string
  target_entity: string | null
  target_id: string | null
  details_json: Record<string, unknown> | null
  created_at: string
}

interface ProjectItem {
  id: string
  name: string
  client_name: string
  status: string
  created_by: string
}

type Tab = 'users' | 'audit' | 'projects' | 'stats'

export default function Admin() {
  const [tab, setTab] = useState<Tab>('users')
  const [users, setUsers] = useState<UserItem[]>([])
  const [logs, setLogs] = useState<AuditLogItem[]>([])
  const [projects, setProjects] = useState<ProjectItem[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    loadData()
  }, [])

  const loadData = async () => {
    try {
      const [u, l, p] = await Promise.all([
        listUsers(),
        listAuditLogs(200),
        listAllProjects(),
      ])
      setUsers(u.data)
      setLogs(l.data)
      setProjects(p.data)
    } catch (err: any) {
      if (err.response?.status === 403) {
        setError('Admin access required')
      }
    }
  }

  const handleRoleChange = async (userId: string, newRole: string, userEmail: string) => {
    if (newRole === 'team_admin') {
      if (!confirm(`Grant TEAM_ADMIN role to ${userEmail}? This allows raw_conversation subscription.`)) return
    }
    try {
      await updateUserRole(userId, newRole)
      await loadData()
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to update role')
    }
  }

  const handleDeactivate = async (userId: string, email: string) => {
    if (!confirm(`Deactivate user ${email}?`)) return
    try {
      await deactivateUser(userId)
      await loadData()
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to deactivate user')
    }
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <div className="text-red-400 text-xl">{error}</div>
      </div>
    )
  }

  const activeUsers = users.filter((u) => u.is_active)
  const adminCount = activeUsers.filter((u) => u.role === 'admin').length

  const tabs: { key: Tab; label: string }[] = [
    { key: 'users', label: 'Users' },
    { key: 'audit', label: 'Audit Logs' },
    { key: 'projects', label: 'All Projects' },
    { key: 'stats', label: 'Statistics' },
  ]

  return (
    <div className="min-h-screen bg-gray-950 p-8">
      <nav className="flex items-center justify-between mb-8">
        <h1 className="text-2xl font-bold text-red-500">Admin Panel</h1>
        <div className="flex gap-4">
          <Link to="/" className="text-gray-300 hover:text-white">Dashboard</Link>
          <Link to="/projects" className="text-gray-300 hover:text-white">Projects</Link>
          <Link to="/reports" className="text-gray-300 hover:text-white">Reports</Link>
          <button
            onClick={() => {
              localStorage.removeItem('token')
              localStorage.removeItem('user')
              window.location.href = '/login'
            }}
            className="text-gray-400 hover:text-red-400"
          >
            Logout
          </button>
        </div>
      </nav>

      {/* Tab Bar */}
      <div className="flex gap-2 mb-6">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition ${
              tab === t.key
                ? 'bg-red-600 text-white'
                : 'bg-gray-800 text-gray-400 hover:text-white'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Users Tab */}
      {tab === 'users' && (
        <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
          <table className="w-full text-left">
            <thead className="bg-gray-800">
              <tr>
                <th className="px-4 py-3 text-gray-400 text-sm">Email</th>
                <th className="px-4 py-3 text-gray-400 text-sm">Name</th>
                <th className="px-4 py-3 text-gray-400 text-sm">Role</th>
                <th className="px-4 py-3 text-gray-400 text-sm">Status</th>
                <th className="px-4 py-3 text-gray-400 text-sm">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-t border-gray-800 hover:bg-gray-800/50">
                  <td className="px-4 py-3">{u.email}</td>
                  <td className="px-4 py-3">{u.full_name}</td>
                  <td className="px-4 py-3">
                    <select
                      value={u.role}
                      onChange={(e) => handleRoleChange(u.id, e.target.value, u.email)}
                      className="bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm"
                      disabled={!u.is_active}
                    >
                      <option value="admin">admin</option>
                      <option value="member">member</option>
                      <option value="team_admin">team_admin</option>
                    </select>
                  </td>
                  <td className="px-4 py-3">
                    {u.is_active ? (
                      <span className="text-green-400 text-sm">Active</span>
                    ) : (
                      <span className="text-red-400 text-sm">Inactive</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {u.is_active && (
                      <button
                        onClick={() => handleDeactivate(u.id, u.email)}
                        className="text-red-400 hover:text-red-300 text-sm"
                      >
                        Deactivate
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Audit Logs Tab */}
      {tab === 'audit' && (
        <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
          <table className="w-full text-left">
            <thead className="bg-gray-800">
              <tr>
                <th className="px-4 py-3 text-gray-400 text-sm">Time</th>
                <th className="px-4 py-3 text-gray-400 text-sm">Action</th>
                <th className="px-4 py-3 text-gray-400 text-sm">Target</th>
                <th className="px-4 py-3 text-gray-400 text-sm">Details</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log) => (
                <tr key={log.id} className="border-t border-gray-800 hover:bg-gray-800/50">
                  <td className="px-4 py-3 text-sm text-gray-400">
                    {new Date(log.created_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-3 text-sm font-medium">{log.action}</td>
                  <td className="px-4 py-3 text-sm text-gray-400">
                    {log.target_entity} {log.target_id?.slice(0, 8)}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-500">
                    {log.details_json ? JSON.stringify(log.details_json) : '—'}
                  </td>
                </tr>
              ))}
              {logs.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-6 text-center text-gray-500">
                    No audit logs yet
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* All Projects Tab */}
      {tab === 'projects' && (
        <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
          <table className="w-full text-left">
            <thead className="bg-gray-800">
              <tr>
                <th className="px-4 py-3 text-gray-400 text-sm">Name</th>
                <th className="px-4 py-3 text-gray-400 text-sm">Client</th>
                <th className="px-4 py-3 text-gray-400 text-sm">Status</th>
                <th className="px-4 py-3 text-gray-400 text-sm">Owner</th>
              </tr>
            </thead>
            <tbody>
              {projects.map((p) => (
                <tr key={p.id} className="border-t border-gray-800 hover:bg-gray-800/50">
                  <td className="px-4 py-3">
                    <Link to={`/projects/${p.id}`} className="hover:text-red-400">
                      {p.name}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-gray-400">{p.client_name}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`text-sm ${
                        p.status === 'active' ? 'text-green-400' : 'text-yellow-400'
                      }`}
                    >
                      {p.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-sm">{p.created_by.slice(0, 8)}…</td>
                </tr>
              ))}
              {projects.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-6 text-center text-gray-500">
                    No projects
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Statistics Tab */}
      {tab === 'stats' && (
        <div className="grid grid-cols-4 gap-6">
          {[
            { label: 'Total Users', value: users.length, color: 'text-blue-400' },
            { label: 'Active Users', value: activeUsers.length, color: 'text-green-400' },
            { label: 'Admins', value: adminCount, color: 'text-red-400' },
            { label: 'Total Projects', value: projects.length, color: 'text-yellow-400' },
          ].map((stat) => (
            <div
              key={stat.label}
              className="bg-gray-900 rounded-xl p-6 border border-gray-800"
            >
              <p className="text-gray-400 text-sm">{stat.label}</p>
              <p className={`text-4xl font-bold ${stat.color} mt-1`}>{stat.value}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
