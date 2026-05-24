/**
 * LeftPane — Automation / Assistant / Dashboard tabs (v4.0 P3-main).
 *
 * Left side of the /flow/:id shell: "what the operator says/sees as
 * conversation+overview". Three tabs:
 * - Automation: reuses existing <WorkflowChat> from v3.2.1
 * - Assistant: placeholder for the v3.4 sidechannel agent
 * - Dashboard: reuses existing <InteractionDashboard> data
 */
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@radix-ui/react-tabs'
import { AutomationTab } from './tabs/AutomationTab'
import { AssistantTab } from './tabs/AssistantTab'
import { DashboardTab } from './tabs/DashboardTab'

export function LeftPane({ sessionId }: { sessionId: string }) {
  return (
    <Tabs defaultValue="automation" className="h-full flex flex-col">
      <TabsList className="border-b flex shrink-0 bg-muted/30">
        <TabsTrigger
          value="automation"
          className="px-4 py-2 text-sm font-medium data-[state=active]:bg-background data-[state=active]:border-b-2 data-[state=active]:border-primary"
        >
          Automation
        </TabsTrigger>
        <TabsTrigger
          value="assistant"
          className="px-4 py-2 text-sm font-medium data-[state=active]:bg-background data-[state=active]:border-b-2 data-[state=active]:border-primary"
        >
          Assistant
        </TabsTrigger>
        <TabsTrigger
          value="dashboard"
          className="px-4 py-2 text-sm font-medium data-[state=active]:bg-background data-[state=active]:border-b-2 data-[state=active]:border-primary"
        >
          Dashboard
        </TabsTrigger>
      </TabsList>
      <TabsContent value="automation" className="flex-1 overflow-y-auto">
        <AutomationTab sessionId={sessionId} />
      </TabsContent>
      <TabsContent value="assistant" className="flex-1 overflow-y-auto">
        <AssistantTab />
      </TabsContent>
      <TabsContent value="dashboard" className="flex-1 overflow-y-auto">
        <DashboardTab sessionId={sessionId} />
      </TabsContent>
    </Tabs>
  )
}
