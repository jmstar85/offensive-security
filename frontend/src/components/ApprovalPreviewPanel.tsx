import { useState } from 'react'

export interface ApprovalFlags {
  approved_active_recon?: boolean
  approved_active_exploit?: boolean
  approved_mid_active?: boolean
  approved_mitm_proxy?: boolean
  approved_headless_browser?: boolean
  approved_interactsh?: boolean
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
    approved_active_exploit: false,
    approved_mid_active: false,
    approved_mitm_proxy: false,
    approved_headless_browser: false,
    approved_interactsh: false,
  })

  function toggle(key: keyof ApprovalFlags) {
    setFlags((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  function buildFlagsForPost(): ApprovalFlags {
    // If any slug-level mid_active toggle is on, also assert approved_mid_active
    // so the backend tier gate is satisfied.
    const midActiveAggregated =
      flags.approved_mid_active ||
      flags.approved_mitm_proxy ||
      flags.approved_headless_browser ||
      flags.approved_interactsh
    return { ...flags, approved_mid_active: midActiveAggregated }
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

          {/* Approval flag toggles */}
          <div className="space-y-3 text-xs">
            {/* Active recon */}
            <div className="space-y-1">
              <div className="text-gray-500 uppercase tracking-wide font-semibold">Active recon</div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={!!flags.approved_active_recon}
                  onChange={() => toggle('approved_active_recon')}
                  className="accent-emerald-500"
                />
                <span className="text-gray-300">Active recon approved</span>
              </label>
            </div>

            {/* Mid-active */}
            <div className="space-y-1">
              <div className="text-gray-500 uppercase tracking-wide font-semibold">Mid-active</div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={!!flags.approved_mitm_proxy}
                  onChange={() => toggle('approved_mitm_proxy')}
                  className="accent-yellow-400"
                />
                <span className="text-gray-300">MITM proxy interception</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={!!flags.approved_headless_browser}
                  onChange={() => toggle('approved_headless_browser')}
                  className="accent-yellow-400"
                />
                <span className="text-gray-300">Headless browser probes</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={!!flags.approved_interactsh}
                  onChange={() => toggle('approved_interactsh')}
                  className="accent-yellow-400"
                />
                <span className="text-gray-300">OOB Collaborator (Interactsh)</span>
              </label>
            </div>

            {/* Active exploit */}
            <div className="space-y-1">
              <div className="text-gray-500 uppercase tracking-wide font-semibold">Active exploit</div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={!!flags.approved_active_exploit}
                  onChange={() => toggle('approved_active_exploit')}
                  className="accent-red-500"
                />
                <span className="text-gray-300">Active exploit approved</span>
              </label>
            </div>
          </div>

          <div className="flex gap-2">
            <button
              type="button"
              disabled={!canApprove || approving}
              onClick={() => onApprove(buildFlagsForPost())}
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
