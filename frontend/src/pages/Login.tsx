/**
 * Login page — v4.0 PentAGI-style 2-pane shell.
 *
 * Left: 350px credential form. Right: animated AuthHero brand panel.
 * Top-right corner carries a light/dark theme toggle so the choice can be
 * made before any other navigation happens.
 */
import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { Loader2, Moon, Sun } from 'lucide-react'

import { login } from '../api/client'
import { useTheme } from '../lib/theme'
import AuthHero from '../components/auth/AuthHero'

export default function Login() {
  const navigate = useNavigate()
  const location = useLocation()
  const { theme, toggleTheme } = useTheme()
  const isDark = theme === 'dark'

  // Optional one-shot notice passed via navigation state (e.g. after sign-up
  // when auto-login could not complete).
  const notice = (location.state as { notice?: string } | null)?.notice

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await login(email, password)
      localStorage.setItem('token', res.data.access_token)
      navigate('/')
    } catch {
      setError('Invalid login or password')
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
        data-testid="login-theme-toggle"
      >
        {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
      </button>

      {/* ── Left column — credential form (centered card, 350px wide) ── */}
      <div className="flex items-center justify-center p-6">
        <div className="mx-auto grid w-[350px] gap-8">
          <header className="space-y-1 text-center">
            <h1 className="text-3xl font-bold tracking-tight">OSA Platform</h1>
            <p className="text-sm text-muted-foreground">
              Offensive Security Agent — sign in to continue
            </p>
          </header>

          {notice && (
            <p
              role="status"
              className="rounded-md border border-primary/30 bg-primary/10 px-3 py-2 text-sm text-foreground text-center"
              data-testid="login-notice"
            >
              {notice}
            </p>
          )}

          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="space-y-1.5">
              <label
                htmlFor="login-email"
                className="text-sm font-medium leading-none"
              >
                Login
              </label>
              <input
                id="login-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="Enter your email"
                autoFocus
                required
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
              />
            </div>

            <div className="space-y-1.5">
              <label
                htmlFor="login-password"
                className="text-sm font-medium leading-none"
              >
                Password
              </label>
              <input
                id="login-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter your password"
                required
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="inline-flex items-center justify-center gap-2 h-9 w-full rounded-md bg-primary text-primary-foreground text-sm font-medium shadow-sm transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50"
              data-testid="login-submit"
            >
              {loading && <Loader2 className="h-4 w-4 animate-spin" />}
              <span>{loading ? 'Signing in…' : 'Sign in'}</span>
            </button>

            {error && (
              <p
                role="alert"
                className="text-sm text-destructive font-medium text-center"
              >
                {error}
              </p>
            )}

            <div className="flex flex-col gap-2 text-center">
              <p className="text-sm text-muted-foreground">
                계정이 없으신가요?{' '}
                <Link
                  to="/register"
                  className="text-foreground font-medium hover:underline"
                  data-testid="login-register-link"
                >
                  회원가입
                </Link>
              </p>
              <Link
                to="/reset-password"
                className="text-sm text-muted-foreground hover:text-foreground transition-colors"
                data-testid="login-reset-link"
              >
                비밀번호 재설정
              </Link>
            </div>
          </form>
        </div>
      </div>

      {/* ── Right column — animated brand panel ── */}
      <aside
        aria-hidden="true"
        className="hidden lg:flex relative overflow-hidden bg-gradient-to-br from-primary/20 via-primary/10 to-background"
      >
        <AuthHero
          headline="Machines that hack before attackers do."
          subcopy="OSA thinks like an adversary and moves like one — full-spectrum offensive engagements run entirely by AI, at machine speed."
          features={[
            'Autonomous. Adversarial. Relentless.',
            'No script. No supervision. No mercy.',
            'Every engagement, machine-speed.',
          ]}
        />
      </aside>
    </div>
  )
}
