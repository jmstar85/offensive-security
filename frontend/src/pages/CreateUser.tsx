/**
 * Admin → Create User page.
 *
 * Admin-gated account provisioning (route guarded by <AdminRoute>). Unlike the
 * public /auth/register self-signup — which always spins up a fresh team — this
 * lets an admin set the role and assign the new user to an existing team, a new
 * team, or (default) the admin's own team. Styled to match the Admin panel.
 */
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { createUser, listTeams, type TeamRow } from '../api/client'

const NEW_TEAM = '__new__'
const OWN_TEAM = '__own__'

const inputClass =
  'w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder:text-gray-500 focus:outline-none focus:ring-1 focus:ring-red-500'

export default function CreateUser() {
  const navigate = useNavigate()

  const [email, setEmail] = useState('')
  const [fullName, setFullName] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState('member')
  const [teamChoice, setTeamChoice] = useState(OWN_TEAM)
  const [newTeamName, setNewTeamName] = useState('')
  const [teams, setTeams] = useState<TeamRow[]>([])

  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    listTeams()
      .then((res) => setTeams(res.data))
      .catch(() => {
        /* Non-fatal — admin can still create in their own / a new team. */
      })
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    if (password.length < 8) {
      setError('Password must be at least 8 characters')
      return
    }
    if (teamChoice === NEW_TEAM && !newTeamName.trim()) {
      setError('Enter a name for the new team')
      return
    }

    const payload: {
      email: string
      full_name: string
      password: string
      role: string
      team_id?: string | null
      team_name?: string | null
    } = { email: email.trim(), full_name: fullName.trim(), password, role }

    if (teamChoice === NEW_TEAM) {
      payload.team_name = newTeamName.trim()
    } else if (teamChoice !== OWN_TEAM) {
      payload.team_id = teamChoice
    }

    setSubmitting(true)
    try {
      await createUser(payload)
      navigate('/admin')
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response
        ?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Failed to create user')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-950 p-8 text-white">
      <nav className="flex items-center justify-between mb-8">
        <h1 className="text-2xl font-bold text-red-500">Create User</h1>
        <Link to="/admin" className="text-gray-300 hover:text-white text-sm">
          ← Back to Admin
        </Link>
      </nav>

      <form
        onSubmit={handleSubmit}
        className="max-w-lg bg-gray-900 rounded-xl border border-gray-800 p-6 space-y-5"
      >
        <div className="space-y-1.5">
          <label htmlFor="cu-email" className="text-sm text-gray-400">
            Email
          </label>
          <input
            id="cu-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="user@example.com"
            autoFocus
            required
            className={inputClass}
          />
        </div>

        <div className="space-y-1.5">
          <label htmlFor="cu-name" className="text-sm text-gray-400">
            Full Name
          </label>
          <input
            id="cu-name"
            type="text"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            placeholder="Jane Doe"
            required
            className={inputClass}
          />
        </div>

        <div className="space-y-1.5">
          <label htmlFor="cu-password" className="text-sm text-gray-400">
            Initial Password
          </label>
          <input
            id="cu-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="At least 8 characters"
            minLength={8}
            required
            className={inputClass}
          />
        </div>

        <div className="space-y-1.5">
          <label htmlFor="cu-role" className="text-sm text-gray-400">
            Role
          </label>
          <select
            id="cu-role"
            value={role}
            onChange={(e) => setRole(e.target.value)}
            className={inputClass}
          >
            <option value="member">member</option>
            <option value="team_admin">team_admin</option>
            <option value="admin">admin</option>
          </select>
        </div>

        <div className="space-y-1.5">
          <label htmlFor="cu-team" className="text-sm text-gray-400">
            Team
          </label>
          <select
            id="cu-team"
            value={teamChoice}
            onChange={(e) => setTeamChoice(e.target.value)}
            className={inputClass}
          >
            <option value={OWN_TEAM}>My team (default)</option>
            {teams.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
            <option value={NEW_TEAM}>+ Create new team…</option>
          </select>
        </div>

        {teamChoice === NEW_TEAM && (
          <div className="space-y-1.5">
            <label htmlFor="cu-new-team" className="text-sm text-gray-400">
              New Team Name
            </label>
            <input
              id="cu-new-team"
              type="text"
              value={newTeamName}
              onChange={(e) => setNewTeamName(e.target.value)}
              placeholder="Red Team Alpha"
              className={inputClass}
            />
          </div>
        )}

        {error && (
          <p role="alert" className="text-sm text-red-400 font-medium">
            {error}
          </p>
        )}

        <div className="flex items-center gap-3 pt-2">
          <button
            type="submit"
            disabled={submitting}
            className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-500 text-white text-sm font-medium transition disabled:opacity-50 disabled:pointer-events-none"
            data-testid="create-user-submit"
          >
            {submitting ? 'Creating…' : 'Create User'}
          </button>
          <Link
            to="/admin"
            className="px-4 py-2 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-300 text-sm font-medium transition"
          >
            Cancel
          </Link>
        </div>
      </form>
    </div>
  )
}
