import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { getMe } from "../api/client";
import { useFeatureFlags } from "../hooks/useFeatureFlags";
import { UnderstandingPanel } from "../components/coordinator/UnderstandingPanel";
import { PlanOfWorkPanel } from "../components/coordinator/PlanOfWorkPanel";
import { AgentFamilyTree } from "../components/coordinator/AgentFamilyTree";
import { ConversationTab } from "../components/coordinator/ConversationTab";
import { RawConversationTab } from "../components/coordinator/RawConversationTab";

type Tab = "conversation" | "raw";

export default function CoordinatorPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const flags = useFeatureFlags();
  const [activeTab, setActiveTab] = useState<Tab>("conversation");
  const [userRole, setUserRole] = useState<string | null>(null);

  useEffect(() => {
    getMe()
      .then((res) => setUserRole(res.data.role))
      .catch(() => setUserRole(null));
  }, []);

  if (!sessionId) {
    return (
      <div className="p-4 text-sm text-rose-600">
        Missing session ID in route param.
      </div>
    );
  }

  if (flags !== null && !flags.osa_coordinator_enabled) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        Coordinator feature not enabled
      </div>
    );
  }

  const canSeeRaw = userRole === "team_admin" || userRole === "admin";

  return (
    <div className="flex flex-col h-screen bg-background">
      {/* Breadcrumb */}
      <div className="px-6 py-3 border-b border-border text-xs text-muted-foreground flex items-center gap-1.5">
        <span className="hover:text-foreground cursor-default">Sessions</span>
        <span>/</span>
        <span className="font-mono">{sessionId}</span>
        <span>/</span>
        <span className="text-foreground font-medium">Coordinator</span>
      </div>

      {/* Body: split pane */}
      <div className="flex flex-1 min-h-0">
        {/* Left pane */}
        <div className="w-80 flex-shrink-0 border-r border-border overflow-y-auto p-4 space-y-4">
          <UnderstandingPanel sessionId={sessionId} />
          <PlanOfWorkPanel sessionId={sessionId} />
          <AgentFamilyTree sessionId={sessionId} />
        </div>

        {/* Right pane */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Tab bar */}
          <div className="flex items-center gap-0 border-b border-border px-4">
            <button
              onClick={() => setActiveTab("conversation")}
              className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                activeTab === "conversation"
                  ? "border-primary text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              Conversation
            </button>
            {canSeeRaw && (
              <button
                onClick={() => setActiveTab("raw")}
                className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                  activeTab === "raw"
                    ? "border-primary text-foreground"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                }`}
              >
                Raw
              </button>
            )}
          </div>

          {/* Tab content */}
          <div className="flex-1 min-h-0">
            {activeTab === "conversation" && (
              <ConversationTab sessionId={sessionId} />
            )}
            {activeTab === "raw" && canSeeRaw && (
              <RawConversationTab sessionId={sessionId} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
