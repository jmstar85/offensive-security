import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { createSession, getProject, listSessions } from '../api/client'

export default function ProjectDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [project, setProject] = useState<any>(null)
  const [sessions, setSessions] = useState<any[]>([])
  const [prompt, setPrompt] = useState('')
  const [launching, setLaunching] = useState(false)

  useEffect(() => {
    if (!id) return
    getProject(id).then((r) => setProject(r.data))
    listSessions(id).then((r) => setSessions(r.data))
  }, [id])

  const handleLaunch = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!id || !prompt.trim()) return
    setLaunching(true)
    try {
      const res = await createSession(id, prompt)
      navigate(`/sessions/${res.data.id}/monitor`)
    } finally {
      setLaunching(false)
    }
  }

  const statusColor = (s: string) => ({
    running: 'text-green-400', completed: 'text-blue-400',
    failed: 'text-red-400', killed: 'text-yellow-400', pending: 'text-gray-400',
  }[s] ?? 'text-gray-400')

  return (
    <div className="min-h-screen bg-gray-950 p-8">
      <div className="flex items-center gap-4 mb-6">
        <Link to="/projects" className="text-gray-400 hover:text-white">← Projects</Link>
        <h1 className="text-2xl font-bold">{project?.name ?? 'Loading...'}</h1>
        {project && <span className="text-gray-400">— {project.client_name}</span>}
      </div>

      <div className="bg-gray-900 rounded-xl p-6 border border-gray-800 mb-6">
        <h2 className="text-lg font-semibold mb-3">Launch New Pentest Session</h2>
        <p className="text-gray-400 text-sm mb-3">
          Describe the target environment in natural language. The AI orchestrator will automatically
          select tools and execute the penetration test.
        </p>
        <form onSubmit={handleLaunch} className="flex gap-3">
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="e.g. Test the AWS EC2 instances at 192.168.1.0/24 running Ubuntu. Look for open ports, web vulnerabilities, and misconfigured services."
            className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-4 py-3 text-white focus:outline-none focus:border-red-500 resize-none h-24"
            required
          />
          <button type="submit" disabled={launching}
            className="bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white px-6 py-3 rounded-lg font-semibold whitespace-nowrap self-start">
            {launching ? 'Launching...' : 'Launch'}
          </button>
        </form>
      </div>

      <div className="bg-gray-900 rounded-xl p-6 border border-gray-800">
        <h2 className="text-lg font-semibold mb-4">Sessions</h2>
        {sessions.map((s) => (
          <Link key={s.id} to={`/sessions/${s.id}/monitor`}
            className="flex justify-between items-center py-3 border-b border-gray-800 hover:bg-gray-800 px-2 rounded transition">
            <div>
              <p className="text-sm font-medium truncate max-w-xl">{s.prompt.slice(0, 80)}</p>
              <p className="text-xs text-gray-500">{new Date(s.created_at).toLocaleString()}</p>
            </div>
            <span className={`text-sm font-semibold ${statusColor(s.status)}`}>{s.status.toUpperCase()}</span>
          </Link>
        ))}
        {sessions.length === 0 && <p className="text-gray-500">No sessions yet.</p>}
      </div>
    </div>
  )
}
