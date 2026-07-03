import { useState } from "react";
import { Button } from "../ui/button";
import { Input, Label } from "../ui/input";
import { CredentialRow, createCredential } from "../../api/credentials";

export type Provider = "anthropic" | "openai" | "google";

export interface AddCredentialModalProps {
  onClose: () => void;
  onCreated: (row: CredentialRow) => void;
  onToast: (msg: string) => void;
  /** When set, preselect/lock this provider in the dropdown. Default: unlocked, defaults to "anthropic". */
  provider?: Provider;
  /** When true, omit the Google option from the provider dropdown. Default: false (Google shown). */
  hideGoogle?: boolean;
}

export function AddCredentialModal({ onClose, onCreated, onToast, provider: lockedProvider, hideGoogle = false }: AddCredentialModalProps) {
  const [provider, setProvider] = useState<Provider>(lockedProvider ?? "anthropic");
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
              disabled={!!lockedProvider}
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              <option value="anthropic">Claude (Anthropic)</option>
              <option value="openai">OpenAI</option>
              {!hideGoogle && <option value="google">Gemini (Google)</option>}
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

export default AddCredentialModal;
