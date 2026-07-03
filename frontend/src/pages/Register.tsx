/**
 * Public sign-up page — mirrors the Login 2-pane shell.
 *
 * Open registration (no auth required), reachable from the login page via the
 * "회원가입" link. Calls /auth/register, then auto-logs-in so the new user lands
 * straight in the app. Team/Organization is optional — the backend creates a
 * personal team when it is omitted.
 */
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AxiosError } from 'axios'
import { Loader2, Moon, Sun } from 'lucide-react'

import { login, register } from '../api/client'
import { useTheme } from '../lib/theme'

const inputClass =
  'flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50'

export default function Register() {
  const navigate = useNavigate()
  const { theme, toggleTheme } = useTheme()
  const isDark = theme === 'dark'

  const [email, setEmail] = useState('')
  const [fullName, setFullName] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [teamName, setTeamName] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    if (password.length < 8) {
      setError('Password must be at least 8 characters')
      return
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match')
      return
    }

    setLoading(true)
    try {
      await register(email, password, fullName, teamName.trim() || undefined)
    } catch (err) {
      const detail = (err as AxiosError<{ detail?: string }>)?.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Could not create account')
      setLoading(false)
      return
    }

    // The account now exists. Try to auto-login so the user lands straight in
    // the app; if that step fails (transient blip), don't imply signup failed —
    // send them to sign-in, where their new credentials work.
    try {
      const res = await login(email, password)
      localStorage.setItem('token', res.data.access_token)
      navigate('/')
    } catch {
      navigate('/login', {
        state: { notice: '계정이 생성되었습니다. 로그인해 주세요.' },
      })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="relative h-dvh w-full lg:grid lg:grid-cols-2 bg-background text-foreground">
      {/* ── Theme toggle (absolute top-right of the page) ── */}
      <button
        type="button"
        onClick={toggleTheme}
        aria-label={`Switch to ${isDark ? 'light' : 'dark'} mode`}
        className="absolute top-4 right-4 z-10 inline-flex items-center justify-center h-9 w-9 rounded-md border border-input bg-background/60 backdrop-blur-sm text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
        data-testid="register-theme-toggle"
      >
        {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
      </button>

      {/* ── Left column — sign-up form (centered card, 350px wide) ── */}
      <div className="flex items-center justify-center p-6">
        <div className="mx-auto grid w-[350px] gap-8">
          <header className="space-y-1 text-center">
            <h1 className="text-3xl font-bold tracking-tight">회원가입</h1>
            <p className="text-sm text-muted-foreground">
              OSA Platform — create your account
            </p>
          </header>

          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="space-y-1.5">
              <label htmlFor="reg-email" className="text-sm font-medium leading-none">
                Email
              </label>
              <input
                id="reg-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                autoFocus
                required
                className={inputClass}
              />
            </div>

            <div className="space-y-1.5">
              <label htmlFor="reg-name" className="text-sm font-medium leading-none">
                Full Name
              </label>
              <input
                id="reg-name"
                type="text"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                placeholder="Jane Doe"
                required
                className={inputClass}
              />
            </div>

            <div className="space-y-1.5">
              <label htmlFor="reg-password" className="text-sm font-medium leading-none">
                Password
              </label>
              <input
                id="reg-password"
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
              <label htmlFor="reg-confirm" className="text-sm font-medium leading-none">
                Confirm Password
              </label>
              <input
                id="reg-confirm"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="Re-enter your password"
                minLength={8}
                required
                className={inputClass}
              />
            </div>

            <div className="space-y-1.5">
              <label htmlFor="reg-team" className="text-sm font-medium leading-none">
                Team / Organization{' '}
                <span className="text-muted-foreground font-normal">(optional)</span>
              </label>
              <input
                id="reg-team"
                type="text"
                value={teamName}
                onChange={(e) => setTeamName(e.target.value)}
                placeholder="Defaults to a personal team"
                className={inputClass}
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="inline-flex items-center justify-center gap-2 h-9 w-full rounded-md bg-primary text-primary-foreground text-sm font-medium shadow-sm transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50"
              data-testid="register-submit"
            >
              {loading && <Loader2 className="h-4 w-4 animate-spin" />}
              <span>{loading ? 'Creating account…' : 'Sign up'}</span>
            </button>

            {error && (
              <p role="alert" className="text-sm text-destructive font-medium text-center">
                {error}
              </p>
            )}

            <p className="text-sm text-muted-foreground text-center">
              Already have an account?{' '}
              <Link to="/login" className="text-foreground hover:underline">
                Sign in
              </Link>
            </p>
          </form>
        </div>
      </div>

      {/* ── Right column — brand panel with slow-spinning favicon mark ── */}
      <aside
        aria-hidden="true"
        className="hidden lg:flex relative overflow-hidden bg-gradient-to-br from-primary/20 via-primary/10 to-background"
      >
        <div className="m-auto flex items-center justify-center">
          <img
            src="/favicon.svg"
            alt=""
            className="w-40 h-40 animate-logo-spin drop-shadow-[0_0_24px_hsl(var(--primary)/0.4)]"
          />
        </div>
      </aside>
    </div>
  )
}
