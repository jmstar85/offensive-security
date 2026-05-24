/**
 * AutomationTab — reuses existing PentestWorkflow page logic (v4.0 P3-main).
 *
 * PentestWorkflow already implements the ambiguity loop + approval flow +
 * force-approve + rescope modal + draft-step editor. v4.0 P3-main mounts the
 * page component inside the /flow/:id left pane verbatim — both routes use
 * `:id` as the route param, so PentestWorkflow's internal `useParams()`
 * resolves correctly when nested here.
 *
 * Once the new flow shell is the default (P5), the legacy /workflows/:id
 * route is removed but this component still uses the same PentestWorkflow
 * source. P5 then renames PentestWorkflow to AutomationWorkflow to match.
 */
import PentestWorkflow from '@/pages/PentestWorkflow'

export function AutomationTab({ sessionId: _sessionId }: { sessionId: string }) {
  // sessionId is informational only; PentestWorkflow reads it from useParams.
  return (
    <div className="h-full p-2">
      <PentestWorkflow />
    </div>
  )
}
