import { useEffect, useState } from "react";
import { Key, Plus, Trash2, ExternalLink } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Input, Label } from "../components/ui/input";
import { useFeatureFlags } from "../hooks/useFeatureFlags";
import {
  CredentialRow,
  listCredentials,
  createCredential,
  revokeCredential,
  startOAuth,
} from "../api/credentials";

type Provider = "anthropic" | "openai" | "google";

const PROVIDER_LABELS: Record<Provider, string> = {
  anthropic: "Claude (Anthropic)",
  openai: "OpenAI",
  google: "Gemini (Google)",
};

function credStatus(row: CredentialRow): { label: string; variant: "success" | "destructive" | "secondary" } {
  if (row.revoked_at) return { label: "Revoked", variant: "destructive" };
  if (row.expires_at && new Date(row.expires_at) < new Date()) return { label: "Expired", variant: "secondary" };
  return { label: "Active", variant: "success" };
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

interface AddCredentialModalProps {
  onClose: () => void;
  onCreated: (row: CredentialRow) => void;
  onToast: (msg: string) => void;
}

function AddCredentialModal({ onClose, onCreated, onToast }: AddCredentialModalProps) {
  const [provider, setProvider] = useState<Provider>("anthropic");
  const [label, setLabel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!label.trim() || !apiKey.trim()) {
      setError("Label and API key are required.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const row = await createCredential({ provider, credential_type: "api_key", label: label.trim(), api_key: apiKey });
      setApiKey("");
      onCreated(row);
      onToast("Credential saved. The secret is encrypted at rest and never displayed again.");
      onClose();
    } catch {
      setError("Failed to save credential. Check that the key is valid.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md bg-card border border-border rounded-xl shadow-2xl p-6 space-y-4"
        onClick={e => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold text-foreground">Add Credential</h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="cred-provider">Provider</Label>
            <select
              id="cred-provider"
              value={provider}
              onChange={e => setProvider(e.target.value as Provider)}
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              <option value="anthropic">Claude (Anthropic)</option>
              <option value="openai">OpenAI</option>
              <option value="google">Gemini (Google)</option>
            </select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cred-label">Label</Label>
            <Input
              id="cred-label"
              placeholder="e.g. prod-anthropic-key"
              value={label}
              onChange={e => setLabel(e.target.value)}
              autoComplete="off"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cred-key">API Key</Label>
            <Input
              id="cred-key"
              type="password"
              placeholder="sk-..."
              value={apiKey}
              onChange={e => setApiKey(e.target.value)}
              autoComplete="new-password"
            />
            <p className="text-xs text-muted-foreground">Written once, never displayed again.</p>
          </div>
          {error && <p className="text-xs text-destructive">{error}</p>}
          <div className="flex justify-end gap-2 pt-1">
            <Button type="button" variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
            <Button type="submit" size="sm" disabled={submitting}>
              {submitting ? "Saving..." : "Save"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

interface RevokeDialogProps {
  row: CredentialRow;
  onClose: () => void;
  onRevoked: (id: string) => void;
}

function RevokeDialog({ row, onClose, onRevoked }: RevokeDialogProps) {
  const [submitting, setSubmitting] = useState(false);

  const handleRevoke = async () => {
    setSubmitting(true);
    try {
      await revokeCredential(row.id);
      onRevoked(row.id);
      onClose();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-sm bg-card border border-border rounded-xl shadow-2xl p-6 space-y-4"
        onClick={e => e.stopPropagation()}
      >
        <h2 className="text-base font-semibold text-foreground">Revoke credential?</h2>
        <p className="text-sm text-muted-foreground">
          This will permanently revoke <span className="font-medium text-foreground">{row.label ?? row.id}</span>. Any active sessions using this credential will fail.
        </p>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
          <Button variant="destructive" size="sm" disabled={submitting} onClick={handleRevoke}>
            {submitting ? "Revoking..." : "Revoke"}
          </Button>
        </div>
      </div>
    </div>
  );
}

export default function CredentialsPage() {
  const flags = useFeatureFlags();
  const [credentials, setCredentials] = useState<CredentialRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [revokeTarget, setRevokeTarget] = useState<CredentialRow | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [oauthError, setOauthError] = useState<string | null>(null);

  useEffect(() => {
    listCredentials()
      .then(rows => { setCredentials(rows); setLoading(false); })
      .catch(() => { setError("Failed to load credentials."); setLoading(false); });
  }, []);

  const handleCreated = (row: CredentialRow) => {
    setCredentials(prev => [row, ...prev]);
  };

  const handleRevoked = (id: string) => {
    setCredentials(prev =>
      prev.map(r => r.id === id ? { ...r, revoked_at: new Date().toISOString() } : r)
    );
  };

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 5000);
  };

  const handleOAuth = async (provider: Provider) => {
    setOauthError(null);
    try {
      const { auth_url } = await startOAuth(provider);
      window.location.href = auth_url;
    } catch {
      setOauthError(`Failed to start OAuth for ${PROVIDER_LABELS[provider]}.`);
    }
  };

  return (
    <div className="p-6 space-y-6">
      {toast && (
        <div className="fixed top-4 right-4 z-50 max-w-sm rounded-md border border-green-700/40 bg-green-900/20 px-4 py-3 text-sm text-green-200 shadow-lg">
          {toast}
        </div>
      )}

      {showAdd && (
        <AddCredentialModal
          onClose={() => setShowAdd(false)}
          onCreated={handleCreated}
          onToast={showToast}
        />
      )}

      {revokeTarget && (
        <RevokeDialog
          row={revokeTarget}
          onClose={() => setRevokeTarget(null)}
          onRevoked={handleRevoked}
        />
      )}

      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <Key className="w-6 h-6" />
            LLM Credentials
          </h1>
          <p className="text-muted-foreground text-sm mt-1 max-w-2xl">
            Per-user API keys and OAuth connections for Claude, OpenAI, Gemini providers. Never decrypted in the UI — values are written once and revoked when no longer needed.
          </p>
        </div>
        <Button onClick={() => setShowAdd(true)} className="flex-shrink-0">
          <Plus className="w-4 h-4" />
          Add Credential
        </Button>
      </div>

      {flags !== null && !flags.osa_multi_provider_llm && (
        <div className="rounded-md border border-amber-700/40 bg-amber-900/20 px-4 py-3 text-sm text-amber-200" role="note">
          Multi-LLM disabled by flag. Credentials cannot be used yet — configure them now to be ready when flag flips.
        </div>
      )}

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">OAuth Connections</CardTitle>
          <CardDescription className="text-xs">Connect provider accounts via OAuth to issue tokens automatically.</CardDescription>
        </CardHeader>
        <CardContent>
          {oauthError && <p className="text-xs text-destructive mb-3">{oauthError}</p>}
          <div className="flex flex-wrap gap-2">
            {(["anthropic", "openai", "google"] as Provider[]).map(p => (
              <Button key={p} variant="outline" size="sm" onClick={() => handleOAuth(p)}>
                <ExternalLink className="w-3.5 h-3.5" />
                Connect {PROVIDER_LABELS[p]}
              </Button>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">API Keys</CardTitle>
          <CardDescription className="text-xs">Saved API keys. Secrets are never returned by the API after creation.</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {loading && (
            <p className="text-center py-10 text-muted-foreground text-sm">Loading...</p>
          )}
          {error && (
            <p className="text-center py-10 text-destructive text-sm">{error}</p>
          )}
          {!loading && !error && credentials.length === 0 && (
            <p className="text-center py-10 text-muted-foreground text-sm">
              No credentials configured. Add one above to start using multi-LLM.
            </p>
          )}
          {!loading && !error && credentials.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th className="px-4 py-2.5 font-medium">Provider</th>
                    <th className="px-4 py-2.5 font-medium">Label</th>
                    <th className="px-4 py-2.5 font-medium">Type</th>
                    <th className="px-4 py-2.5 font-medium">Created</th>
                    <th className="px-4 py-2.5 font-medium">Last used</th>
                    <th className="px-4 py-2.5 font-medium">Status</th>
                    <th className="px-4 py-2.5 font-medium" />
                  </tr>
                </thead>
                <tbody>
                  {credentials.map(row => {
                    const status = credStatus(row);
                    return (
                      <tr key={row.id} className="border-b border-border last:border-0 hover:bg-accent/30 transition-colors">
                        <td className="px-4 py-3 font-medium capitalize">{PROVIDER_LABELS[row.provider]}</td>
                        <td className="px-4 py-3 text-muted-foreground">{row.label ?? <span className="italic">—</span>}</td>
                        <td className="px-4 py-3">
                          <Badge variant="secondary" className="text-xs">
                            {row.credential_type === "api_key" ? "API key" : "OAuth"}
                          </Badge>
                        </td>
                        <td className="px-4 py-3 text-muted-foreground">{formatDate(row.created_at)}</td>
                        <td className="px-4 py-3 text-muted-foreground">{formatDate(row.last_used_at)}</td>
                        <td className="px-4 py-3">
                          <Badge variant={status.variant} className="text-xs">{status.label}</Badge>
                        </td>
                        <td className="px-4 py-3">
                          {!row.revoked_at && (
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7 text-muted-foreground hover:text-destructive"
                              onClick={() => setRevokeTarget(row)}
                              title="Revoke credential"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </Button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
