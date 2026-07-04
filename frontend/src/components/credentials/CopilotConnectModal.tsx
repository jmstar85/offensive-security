import { useCallback, useEffect, useRef, useState } from "react";
import { Copy } from "lucide-react";
import { Button } from "../ui/button";
import { CredentialRow, startCopilotDevice, pollCopilotDevice } from "../../api/credentials";

export interface CopilotConnectModalProps {
  onClose: () => void;
  onCreated: (row: CredentialRow) => void;
  onToast: (msg: string) => void;
}

const DEFAULT_INTERVAL_SEC = 5;

type Phase = "starting" | "pending" | "error";

export function CopilotConnectModal({ onClose, onCreated, onToast }: CopilotConnectModalProps) {
  const [phase, setPhase] = useState<Phase>("starting");
  const [userCode, setUserCode] = useState<string | null>(null);
  const [verificationUri, setVerificationUri] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  // Poll/expiry timers are tracked in refs so start()/cleanup can cancel
  // whichever generation of timers is currently live without stale closures.
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const expiryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const stateRef = useRef<string | null>(null);

  const clearTimers = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    if (expiryTimerRef.current) {
      clearTimeout(expiryTimerRef.current);
      expiryTimerRef.current = null;
    }
  }, []);

  const start = useCallback(async () => {
    clearTimers();
    setErrorMsg(null);
    setPhase("starting");
    setUserCode(null);
    setVerificationUri(null);
    try {
      const res = await startCopilotDevice();
      stateRef.current = res.state;
      setUserCode(res.user_code);
      setVerificationUri(res.verification_uri);
      setPhase("pending");

      const intervalMs = (res.interval || DEFAULT_INTERVAL_SEC) * 1000;

      const doPoll = async () => {
        const currentState = stateRef.current;
        if (!currentState) return;
        try {
          const result = await pollCopilotDevice(currentState);
          if (result.status === "complete") {
            clearTimers();
            if (result.credential) onCreated(result.credential);
            onToast("GitHub Copilot connected.");
            onClose();
          } else if (result.status === "expired" || result.status === "denied") {
            clearTimers();
            setPhase("error");
            setErrorMsg(
              result.status === "expired"
                ? "The device code expired before authorization completed."
                : "Authorization was denied."
            );
          }
          // 'pending' — keep polling.
        } catch {
          clearTimers();
          setPhase("error");
          setErrorMsg("Failed to check authorization status.");
        }
      };

      pollTimerRef.current = setInterval(doPoll, intervalMs);
      expiryTimerRef.current = setTimeout(() => {
        clearTimers();
        setPhase((p) => {
          if (p === "pending") {
            setErrorMsg("The device code expired before authorization completed.");
            return "error";
          }
          return p;
        });
      }, (res.expires_in || 900) * 1000);
    } catch {
      setPhase("error");
      setErrorMsg("Failed to start GitHub device authorization.");
    }
  }, [clearTimers, onClose, onCreated, onToast]);

  useEffect(() => {
    start();
    return () => clearTimers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleCopy = async () => {
    if (!userCode) return;
    try {
      await navigator.clipboard.writeText(userCode);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard unavailable — no-op */
    }
  };

  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md bg-card border border-border rounded-xl shadow-2xl p-6 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold text-foreground">Connect GitHub Copilot</h2>

        {phase === "starting" && (
          <p className="text-sm text-muted-foreground">Requesting a device code from GitHub…</p>
        )}

        {phase === "pending" && userCode && verificationUri && (
          <div className="space-y-4">
            <ol className="space-y-3 text-sm text-foreground list-decimal list-inside">
              <li>
                Go to{" "}
                <a
                  href={verificationUri}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary underline underline-offset-4 hover:no-underline"
                >
                  {verificationUri}
                </a>
              </li>
              <li>Enter this code:</li>
            </ol>
            <div className="flex items-center gap-2">
              <div className="flex-1 rounded-md border border-input bg-secondary px-4 py-3 text-center text-xl font-mono tracking-[0.3em] text-foreground">
                {userCode}
              </div>
              <Button type="button" variant="outline" size="icon" onClick={handleCopy} title="Copy code">
                <Copy className="w-4 h-4" />
              </Button>
            </div>
            {copied && <p className="text-xs text-muted-foreground">Copied.</p>}
            <p className="text-xs text-muted-foreground">
              Waiting for authorization… this will complete automatically once you approve the
              device in GitHub.
            </p>
          </div>
        )}

        {phase === "error" && (
          <div className="space-y-3">
            <p className="text-xs text-destructive">{errorMsg}</p>
            <Button type="button" size="sm" onClick={start}>
              Try again
            </Button>
          </div>
        )}

        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="ghost" size="sm" onClick={onClose}>
            Cancel
          </Button>
        </div>
      </div>
    </div>
  );
}

export default CopilotConnectModal;
