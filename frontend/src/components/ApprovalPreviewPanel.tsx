interface Props {
  preview: { is_valid: boolean; violations: string[]; step_count: number } | null
  approving: boolean
  rejecting: boolean
  onRefresh: () => void
  onApprove: () => void
  onReject: () => void
  onOpenForceApprove: () => void
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
  canApprove,
  state,
  ambiguityOverrideReason,
}: Props) {
  const ready = state === 'ready_for_review'
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

          <div className="flex gap-2">
            <button
              type="button"
              disabled={!canApprove || approving}
              onClick={onApprove}
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
            Session must reach <code className="bg-gray-800 px-1 rounded">ready_for_review</code>{' '}
            before approval. Use the interview, or force-ready with a written reason.
          </p>
          <button
            type="button"
            onClick={onOpenForceApprove}
            className="text-xs text-red-400 hover:text-red-300 underline"
          >
            Force ready for review →
          </button>
        </>
      )}
    </div>
  )
}
