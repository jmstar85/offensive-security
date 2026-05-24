/**
 * AssistantTab — sidechannel agent placeholder (v4.0 P3-main).
 *
 * PentAGI exposes an Assistant role as a separate concurrent chain the
 * operator can use to inject mid-flow instructions. v4.0's Minimal 6 roles
 * intentionally excludes Assistant (it lands in v3.4 with its own role,
 * msgchains type, and `assistantLogAdded` subscription topic).
 *
 * v4.0 ships the tab shell so the left-pane layout matches PentAGI's
 * structure, but the body is a placeholder pointing to the v3.4 backlog
 * item.
 */
import { MessageSquare } from 'lucide-react'

export function AssistantTab() {
  return (
    <div className="p-4 text-sm text-muted-foreground">
      <div className="flex items-center gap-2 mb-2 text-foreground">
        <MessageSquare className="h-4 w-4" />
        <span className="font-semibold">Assistant — v3.4 backlog</span>
      </div>
      <p>
        The sidechannel Assistant agent lets you inject mid-flow instructions
        without interrupting the autonomous role loop. It is intentionally
        deferred from v4.0 (Minimal 6 roles) and lands in v3.4 alongside
        Searches / Vector Store / Screenshots tabs.
      </p>
      <p className="mt-2">
        For now, mid-flow guidance goes through the Automation tab's chat or
        the rescope-approval flow if a new target is discovered.
      </p>
    </div>
  )
}
