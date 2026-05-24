/**
 * DeprecationBanner — shown on legacy pages when `osa_flow_ui_enabled=true`
 * (v4.0 P3-main).
 *
 * Mounted at the top of Monitor / PentestWorkflow / AgentCatalog /
 * InteractionDashboard pages while the flag is ON so operators see a clear
 * call-to-action to migrate to /flow/:id. Removed by P5 alongside the
 * page deletions.
 */
import { Link } from 'react-router-dom'
import { AlertTriangle } from 'lucide-react'

export function DeprecationBanner({
  newPath = '/flow',
  pageName,
  removalRelease = 'v3.4',
}: {
  newPath?: string
  pageName: string
  removalRelease?: string
}) {
  return (
    <div className="bg-amber-500/10 border border-amber-500/40 text-amber-900 dark:text-amber-200 rounded p-3 mb-4 flex items-start gap-3">
      <AlertTriangle className="h-5 w-5 mt-0.5 shrink-0 text-amber-600" />
      <div className="text-sm flex-1 min-w-0">
        <p className="font-medium">
          {pageName} is moving to the new /flow shell.
        </p>
        <p className="mt-0.5">
          This page will be removed in <strong>{removalRelease}</strong>. Switch to{' '}
          <Link className="underline font-medium" to={newPath}>
            {newPath}
          </Link>{' '}
          for the integrated 2-pane experience (Terminal · Tasks · Agents).
        </p>
      </div>
    </div>
  )
}
