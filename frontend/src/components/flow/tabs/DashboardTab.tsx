/**
 * DashboardTab — reuses the existing InteractionDashboard page (v4.0 P3-main).
 *
 * InteractionDashboard already renders the recharts-based metrics overview
 * (sessions over time, agent-run stats, findings-by-severity). Mounting it
 * inside the /flow/:id left pane preserves the v3.2.1 dashboard UX so
 * operators don't lose visibility when the flag flips ON.
 */
import InteractionDashboard from '@/pages/InteractionDashboard'

export function DashboardTab({ sessionId: _sessionId }: { sessionId: string }) {
  return (
    <div className="h-full p-2">
      <InteractionDashboard />
    </div>
  )
}
