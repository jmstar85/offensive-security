/**
 * RightPane — Terminal / Tasks / Agents tabs (v4.0 P3-main).
 *
 * Right side of the /flow/:id shell: "what the agents are doing as raw
 * evidence". Three tabs adopted per the Minimal port:
 * - Terminal: xterm.js wired to `useTopicWebSocket(sessionId, 'terminal')`
 * - Tasks: SubTask tree from session.draft_plan_json + live `tasks` events
 * - Agents: per-role MsgChain status from GET /msgchains + live `agents` events
 *
 * Searches / Vector Store / Screenshots tabs are deferred to v3.4.
 */
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@radix-ui/react-tabs'
import { TerminalTab } from './tabs/TerminalTab'
import { TasksTab } from './tabs/TasksTab'
import { AgentsTab } from './tabs/AgentsTab'

export function RightPane({ sessionId }: { sessionId: string }) {
  return (
    <Tabs defaultValue="terminal" className="h-full flex flex-col">
      <TabsList className="border-b flex shrink-0 bg-muted/30 overflow-x-auto">
        <TabsTrigger
          value="terminal"
          className="px-4 py-2 text-sm font-medium data-[state=active]:bg-background data-[state=active]:border-b-2 data-[state=active]:border-primary"
        >
          Terminal
        </TabsTrigger>
        <TabsTrigger
          value="tasks"
          className="px-4 py-2 text-sm font-medium data-[state=active]:bg-background data-[state=active]:border-b-2 data-[state=active]:border-primary"
        >
          Tasks
        </TabsTrigger>
        <TabsTrigger
          value="agents"
          className="px-4 py-2 text-sm font-medium data-[state=active]:bg-background data-[state=active]:border-b-2 data-[state=active]:border-primary"
        >
          Agents
        </TabsTrigger>
      </TabsList>
      <TabsContent value="terminal" className="flex-1 overflow-hidden">
        <TerminalTab sessionId={sessionId} />
      </TabsContent>
      <TabsContent value="tasks" className="flex-1 overflow-y-auto p-2">
        <TasksTab sessionId={sessionId} />
      </TabsContent>
      <TabsContent value="agents" className="flex-1 overflow-y-auto p-2">
        <AgentsTab sessionId={sessionId} />
      </TabsContent>
    </Tabs>
  )
}
