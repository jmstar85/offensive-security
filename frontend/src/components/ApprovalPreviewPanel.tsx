import { useState } from 'react'

// The three tier flags the backend actually enforces (exploit_allowlist.py
// TIER_REQUIRED_FLAG). The former mitm_proxy/headless_browser/interactsh toggles
// were cosmetic — buildFlagsForPost OR'd them into approved_mid_active and the
// backend never read them individually, so they are removed in favour of one
// honest per-tier control.
export interface ApprovalFlags {
  approved_active_recon?: boolean
  approved_mid_active?: boolean
  approved_active_exploit?: boolean
}

interface Props {
  preview: { is_valid: boolean; violations: string[]; step_count: number } | null
  approving: boolean
  rejecting: boolean
  onRefresh: () => void
  onApprove: (flags: ApprovalFlags) => void
  onReject: () => void
  onOpenForceApprove: () => void
  onProceedToReview: () => void
  proceeding?: boolean
  ambiguityScore?: number
  canApprove: boolean
  state: string
  ambiguityOverrideReason?: string | null
}

export default function ApprovalPreviewPanel({
  preview,
  approving,
  rejecting,
  onRefresh,
  onApprove,
  onReject,
  onOpenForceApprove,
  onProceedToReview,
  proceeding,
  ambiguityScore,
  canApprove,
  state,
  ambiguityOverrideReason,
}: Props) {
  const ready = state === 'ready_for_review'

  const [flags, setFlags] = useState<ApprovalFlags>({
    approved_active_recon: false,
    approved_mid_active: false,
    approved_active_exploit: false,
  })

  function toggle(key: keyof ApprovalFlags) {
    setFlags((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-200">Approval gate</h3>
        <span
          className={`text-xs px-2 py-0.5 rounded border ${
            ready
              ? 'border-emerald-700 text-emerald-300 bg-emerald-900/40'
              : 'border-gray-700 text-gray-400 bg-gray-800'
          }`}
        >
          {state}
        </span>
      </div>

      {ambiguityOverrideReason && (
        <div className="bg-yellow-900/30 border border-yellow-800 rounded-lg p-2 text-xs text-yellow-200">
          Force-approved: <span className="italic">{ambiguityOverrideReason}</span>
        </div>
      )}

      {ready ? (
        <>
          <div className="text-xs text-gray-400">
            <button
              type="button"
              onClick={onRefresh}
              className="underline hover:text-white"
            >
              Run whitelist preview
            </button>
            {preview && (
              <span className="ml-2">
                {preview.step_count} steps, {preview.violations.length} violations
              </span>
            )}
          </div>

          {preview && !preview.is_valid && (
            <div className="bg-red-950/40 border border-red-900 rounded-lg p-2 text-xs space-y-1">
              <div className="font-semibold text-red-300">
                {preview.violations.length} out-of-scope reference(s)
              </div>
              <ul className="list-disc list-inside text-red-200">
                {preview.violations.map((v, i) => (
                  <li key={i}>{v}</li>
                ))}
              </ul>
              <p className="text-red-300/70">
                Edit or remove these steps before approval.
              </p>
            </div>
          )}

          {/* Tier authorization — each control maps 1:1 to a flag the backend
              enforces (exploit_allowlist.TIER_REQUIRED_FLAG). A plan step whose
              tier is not authorized here is dropped before execution. Passive
              recon needs no flag. */}
          <div className="space-y-2 text-xs">
            <div className="text-gray-500 uppercase tracking-wide font-semibold">
              Authorize by tier
            </div>
            <label className="flex items-start gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={!!flags.approved_active_recon}
                onChange={() => toggle('approved_active_recon')}
                className="accent-emerald-500 mt-0.5"
              />
              <span className="text-gray-300">
                <span className="text-emerald-300 font-medium">Active recon</span> — port
                scans, directory/subdomain enumeration, OOB collaborator callbacks
              </span>
            </label>
            <label className="flex items-start gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={!!flags.approved_mid_active}
                onChange={() => toggle('approved_mid_active')}
                className="accent-yellow-400 mt-0.5"
              />
              <span className="text-gray-300">
                <span className="text-yellow-300 font-medium">Mid-active tooling</span> —
                MITM proxy, headless browser, session replay
              </span>
            </label>
            <label className="flex items-start gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={!!flags.approved_active_exploit}
                onChange={() => toggle('approved_active_exploit')}
                className="accent-red-500 mt-0.5"
              />
              <span className="text-gray-300">
                <span className="text-red-300 font-medium">Active exploit</span> —
                SQLi/XSS/command-injection, Metasploit, PyRIT
              </span>
            </label>
            <p className="text-gray-500">
              Passive recon runs without a flag. Steps whose tier you don't authorize
              are dropped before execution (not silently attempted).
            </p>
          </div>

          <div className="flex gap-2">
            <button
              type="button"
              disabled={!canApprove || approving}
              onClick={() => onApprove(flags)}
              className="bg-red-600 hover:bg-red-700 disabled:opacity-40 text-white px-3 py-1.5 rounded text-sm font-medium"
            >
              {approving ? 'Approving…' : 'Approve & execute'}
            </button>
            <button
              type="button"
              disabled={rejecting}
              onClick={onReject}
              className="bg-gray-700 hover:bg-gray-600 text-white px-3 py-1.5 rounded text-sm"
            >
              {rejecting ? 'Rejecting…' : 'Reject'}
            </button>
          </div>
        </>
      ) : (
        <>
          <p className="text-xs text-gray-500">
            The AI hasn't marked this session{' '}
            <code className="bg-gray-800 px-1 rounded">ready_for_review</code> yet
            {typeof ambiguityScore === 'number'
              ? ` (ambiguity ${ambiguityScore.toFixed(2)})`
              : ''}
            . That score is advisory — the whitelist scope check is the safety
            gate — so you can review and approve the plan now.
          </p>
          <div className="flex items-center gap-3">
            <button
              type="button"
              disabled={proceeding}
              onClick={onProceedToReview}
              className="bg-emerald-700 hover:bg-emerald-600 disabled:opacity-40 text-white px-3 py-1.5 rounded text-sm font-medium"
            >
              {proceeding ? 'Proceeding…' : 'Proceed to plan review'}
            </button>
            <button
              type="button"
              onClick={onOpenForceApprove}
              className="text-xs text-gray-400 hover:text-gray-200 underline"
            >
              Add a reason…
            </button>
          </div>
        </>
      )}
    </div>
  )
}
