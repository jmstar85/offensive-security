/**
 * TwoPaneShell — horizontal resizable 2-pane wrapper (v4.0 P3-main).
 *
 * PentAGI port of `frontend/src/pages/flows/flow.tsx`. Default 50/50 split,
 * 30% minimum each pane, ~100dvh height (subtract sidebar). A draggable
 * handle separates the panes; on mobile (< md breakpoint) the layout
 * collapses to a single stacked card via a Tailwind responsive class.
 */
import { ReactNode } from 'react'
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels'
import { GripVertical } from 'lucide-react'

export function TwoPaneShell({
  left,
  right,
}: {
  left: ReactNode
  right: ReactNode
}) {
  return (
    <div className="hidden md:block h-[calc(100dvh-3rem)] w-full">
      <PanelGroup direction="horizontal" autoSaveId="osa-flow-shell">
        <Panel defaultSize={50} minSize={30} className="overflow-hidden border-r">
          {left}
        </Panel>
        <PanelResizeHandle className="w-1.5 bg-border hover:bg-muted-foreground/30 transition-colors flex items-center justify-center">
          <GripVertical className="h-4 w-4 text-muted-foreground/60" />
        </PanelResizeHandle>
        <Panel defaultSize={50} minSize={30} className="overflow-hidden">
          {right}
        </Panel>
      </PanelGroup>
    </div>
  )
}

// Mobile fallback: render only the left pane stacked (Automation tab is the
// most operator-relevant single-pane view). Right pane content is reachable
// via a "View evidence" link that opens a sheet — implemented in v3.4.
export function MobileSinglePane({ left }: { left: ReactNode }) {
  return <div className="block md:hidden h-[calc(100dvh-3rem)] w-full p-2">{left}</div>
}
