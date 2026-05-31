/**
 * FlowPage — entry route /flow/:id (v4.0 P3-main).
 *
 * The new unified flow shell. Reads the session_id from the route param and
 * renders the 2-pane resizable layout (LeftPane + RightPane) on desktop,
 * with a stacked single-pane fallback on mobile.
 *
 * Gated by `settings.osa_flow_ui_enabled`. With the flag OFF (default), the
 * route is still mounted but App.tsx redirects to the legacy /workflows/:id
 * route so v3.2.1 operators land on the familiar page.
 */
import { useParams } from 'react-router-dom'

import { FlowConsoleHeader } from '@/components/coordinator/FlowConsoleHeader'
import { LeftPane } from '@/components/flow/LeftPane'
import { RightPane } from '@/components/flow/RightPane'
import {
  MobileSinglePane,
  TwoPaneShell,
} from '@/components/flow/TwoPaneShell'

export default function FlowPage() {
  const { id } = useParams<{ id: string }>()

  if (!id) {
    return (
      <div className="p-4 text-sm text-rose-600">
        Missing session ID in route param.
      </div>
    )
  }

  return (
    <div className="flex flex-col h-dvh">
      <FlowConsoleHeader sessionId={id} />
      <div className="flex-1 min-h-0">
        <TwoPaneShell
          left={<LeftPane sessionId={id} />}
          right={<RightPane sessionId={id} />}
        />
        <MobileSinglePane left={<LeftPane sessionId={id} />} />
      </div>
    </div>
  )
}
