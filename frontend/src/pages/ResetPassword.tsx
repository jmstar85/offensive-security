/**
 * Password reset page — mirrors the Login 2-pane shell.
 *
 * No email/SMTP infrastructure exists on the platform, so ownership is proven
 * by requiring the *current* password (rather than an emailed reset token).
 * Reachable from the login page via the "비밀번호 재설정" link. On success the
 * user is bounced back to /login to sign in with the new credentials.
 */
import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { AxiosError } from 'axios'
import { CheckCircle2, Loader2, Moon, Sun } from 'lucide-react'

import { resetPassword } from '../api/client'
import { useTheme } from '../lib/theme'

const inputClass =
  'flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50'

export default function ResetPassword() {
  const navigate = useNavigate()
  const { theme, toggleTheme } = useTheme()
  const isDark = theme === 'dark'

  const [email, setEmail] = useState('')
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    if (newPassword.length < 8) {
      setError('New password must be at least 8 characters')
      return
    }
    if (newPassword !== confirmPassword) {
      setError('New passwords do not match')
      return
    }

    setLoading(true)
    try {
      await resetPassword(email, currentPassword, newPassword)
      setDone(true)
      setTimeout(() => navigate('/login'), 1800)
    } catch (err) {
      const detail = (err as AxiosError<{ detail?: string }>)?.response?.data?.detail
      setError(detail ?? 'Could not reset password')
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
        data-testid="reset-theme-toggle"
      >
        {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
      </button>

      {/* ── Left column — reset form (centered card, 350px wide) ── */}
      <div className="flex items-center justify-center p-6">
        <div className="mx-auto grid w-[350px] gap-8">
          <header className="space-y-1 text-center">
            <h1 className="text-3xl font-bold tracking-tight">비밀번호 재설정</h1>
            <p className="text-sm text-muted-foreground">
              현재 비밀번호를 확인한 뒤 새 비밀번호로 변경합니다
            </p>
          </header>

          {done ? (
            <div
              role="status"
              className="flex flex-col items-center gap-3 text-center"
              data-testid="reset-success"
            >
              <CheckCircle2 className="h-10 w-10 text-primary" />
              <p className="text-sm font-medium">
                비밀번호가 변경되었습니다. 로그인 페이지로 이동합니다…
              </p>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="flex flex-col gap-4">
              <div className="space-y-1.5">
                <label htmlFor="reset-email" className="text-sm font-medium leading-none">
                  Login (email)
                </label>
                <input
                  id="reset-email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="admin@kt.com"
                  autoFocus
                  required
                  className={inputClass}
                />
              </div>

              <div className="space-y-1.5">
                <label htmlFor="reset-current" className="text-sm font-medium leading-none">
                  현재 비밀번호
                </label>
                <input
                  id="reset-current"
                  type="password"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  placeholder="현재 비밀번호"
                  required
                  className={inputClass}
                />
              </div>

              <div className="space-y-1.5">
                <label htmlFor="reset-new" className="text-sm font-medium leading-none">
                  새 비밀번호
                </label>
                <input
                  id="reset-new"
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="8자 이상"
                  minLength={8}
                  required
                  className={inputClass}
                />
              </div>

              <div className="space-y-1.5">
                <label htmlFor="reset-confirm" className="text-sm font-medium leading-none">
                  새 비밀번호 확인
                </label>
                <input
                  id="reset-confirm"
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="새 비밀번호 재입력"
                  minLength={8}
                  required
                  className={inputClass}
                />
              </div>

              <button
                type="submit"
                disabled={loading}
                className="inline-flex items-center justify-center gap-2 h-9 w-full rounded-md bg-primary text-primary-foreground text-sm font-medium shadow-sm transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50"
                data-testid="reset-submit"
              >
                {loading && <Loader2 className="h-4 w-4 animate-spin" />}
                <span>{loading ? '변경 중…' : '비밀번호 변경'}</span>
              </button>

              {error && (
                <p role="alert" className="text-sm text-destructive font-medium text-center">
                  {error}
                </p>
              )}

              <Link
                to="/login"
                className="text-sm text-muted-foreground hover:text-foreground text-center transition-colors"
              >
                ← 로그인으로 돌아가기
              </Link>
            </form>
          )}
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
