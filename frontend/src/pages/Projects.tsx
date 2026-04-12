import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { createProject, listProjects } from '../api/client'

export default function Projects() {
  const [projects, setProjects] = useState<any[]>([])
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({
    name: '', client_name: '', ip_ranges: '', domains: '', cloud_provider: ''
  })

  useEffect(() => { listProjects().then((r) => setProjects(r.data)) }, [])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    await createProject({
      name: form.name,
      client_name: form.client_name,
      target: {
        ip_ranges: form.ip_ranges.split(',').map((s) => s.trim()).filter(Boolean),
        domains: form.domains.split(',').map((s) => s.trim()).filter(Boolean),
        cloud_provider: form.cloud_provider || null,
      },
    })
    setShowForm(false)
    listProjects().then((r) => setProjects(r.data))
  }

  return (
    <div className="min-h-screen bg-gray-950 p-8">
      <div className="flex justify-between items-center mb-6">
        <div className="flex items-center gap-4">
          <Link to="/" className="text-gray-400 hover:text-white">← Dashboard</Link>
          <h1 className="text-2xl font-bold">Projects</h1>
        </div>
        <button onClick={() => setShowForm(!showForm)}
          className="bg-red-600 hover:bg-red-700 text-white px-4 py-2 rounded-lg font-medium">
          + New Project
        </button>
      </div>

      {showForm && (
        <form onSubmit={handleCreate} className="bg-gray-900 rounded-xl p-6 border border-gray-800 mb-6 grid grid-cols-2 gap-4">
          {[
            { label: 'Project Name', key: 'name', placeholder: 'ACME Corp Assessment' },
            { label: 'Client Name', key: 'client_name', placeholder: 'ACME Corp' },
            { label: 'Target IP Ranges (comma-separated)', key: 'ip_ranges', placeholder: '192.168.1.0/24, 10.0.0.0/8' },
            { label: 'Target Domains (comma-separated)', key: 'domains', placeholder: 'acme.com, api.acme.com' },
            { label: 'Cloud Provider (optional)', key: 'cloud_provider', placeholder: 'AWS / GCP / Azure' },
          ].map(({ label, key, placeholder }) => (
            <div key={key} className={key === 'ip_ranges' || key === 'domains' ? 'col-span-2' : ''}>
              <label className="block text-sm text-gray-400 mb-1">{label}</label>
              <input value={form[key as keyof typeof form]}
                onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
                placeholder={placeholder}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white focus:outline-none focus:border-red-500"
                required={key === 'name' || key === 'client_name'}
              />
            </div>
          ))}
          <div className="col-span-2 flex gap-3">
            <button type="submit" className="bg-red-600 hover:bg-red-700 text-white px-6 py-2 rounded-lg font-medium">Create</button>
            <button type="button" onClick={() => setShowForm(false)} className="bg-gray-700 hover:bg-gray-600 px-6 py-2 rounded-lg">Cancel</button>
          </div>
        </form>
      )}

      <div className="grid gap-4">
        {projects.map((p) => (
          <Link key={p.id} to={`/projects/${p.id}`}
            className="bg-gray-900 rounded-xl p-5 border border-gray-800 hover:border-red-800 transition flex justify-between items-center">
            <div>
              <h3 className="font-semibold text-lg">{p.name}</h3>
              <p className="text-gray-400 text-sm">{p.client_name}</p>
            </div>
            <span className={`text-sm px-3 py-1 rounded-full ${p.status === 'active' ? 'bg-green-900 text-green-300' : 'bg-gray-700 text-gray-300'}`}>
              {p.status}
            </span>
          </Link>
        ))}
        {projects.length === 0 && (
          <div className="text-center py-16 text-gray-500">No projects yet. Create your first one.</div>
        )}
      </div>
    </div>
  )
}
