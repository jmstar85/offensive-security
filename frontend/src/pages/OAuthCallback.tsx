import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import api from "../api/client";

export default function OAuthCallback() {
  const [searchParams] = useSearchParams();
  const [status, setStatus] = useState<"pending" | "done" | "error">("pending");

  useEffect(() => {
    const code = searchParams.get("code");
    const state = searchParams.get("state");
    if (!code || !state) {
      setStatus("done");
      return;
    }
    api
      .get("/auth/llm-providers/oauth/callback", { params: { code, state } })
      .then(() => setStatus("done"))
      .catch(() => setStatus("error"));
  }, [searchParams]);

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-6">
      <div className="text-center space-y-3 max-w-sm">
        {status === "pending" && (
          <p className="text-muted-foreground text-sm">Completing OAuth flow...</p>
        )}
        {status === "done" && (
          <>
            <p className="text-foreground font-medium">OAuth callback received.</p>
            <p className="text-muted-foreground text-sm">You can close this tab and return to the Credentials page.</p>
          </>
        )}
        {status === "error" && (
          <>
            <p className="text-destructive font-medium">OAuth callback failed.</p>
            <p className="text-muted-foreground text-sm">Close this tab and try connecting again from the Credentials page.</p>
          </>
        )}
      </div>
    </div>
  );
}
