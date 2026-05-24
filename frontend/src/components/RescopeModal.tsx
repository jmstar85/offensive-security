import { useEffect, useState } from 'react'

interface RescopeRow {
  id: string
  requested_at: string
  requesting_step_id: string
  discovered_targets: {
    rejected?: string[]
    accepted_at_classify?: string[]
    blocked_by_wildcard?: string[]
    tier_map?: Record<string, string>
  }
}

interface Props {
  open: boolean
  pending: RescopeRow[]
  onClose: () => void
  onDecide: (
    rescope_id: string,
    accept: string[],
    reject: string[],
    reason: string | undefined
  ) => Promise<void>
}

export default function RescopeModal({ open, pending, onClose, onDecide }: Props) {
  const [active, setActive] = useState<RescopeRow | null>(null)
  const [decisions, setDecisions] = useState<Record<string, 'accept' | 'reject'>>({})
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!active && pending.length > 0) {
      setActive(pending[0])
      setDecisions({})
      setReason('')
    }
  }, [pending, active])

  if (!open || !active) return null

  const rejected = active.discovered_targets.rejected ?? []
  const tierMap = active.discovered_targets.tier_map ?? {}
  const decidedCount = Object.keys(decisions).length
  const ready = decidedCount === rejected.length

  const flip = (host: string, val: 'accept' | 'reject') =>
    setDecisions((d) => ({ ...d, [host]: val }))

  const submit = async () => {
    if (!ready || busy) return
    setBusy(true)
    try {
      const accept: string[] = []
      const reject: string[] = []
      for (const h of rejected) {
        if (decisions[h] === 'accept') accept.push(h)
        else reject.push(h)
      }
      await onDecide(active.id, accept, reject, reason.trim() || undefined)
      // pop the row; close if last
      const remaining = pending.filter((r) => r.id !== active.id)
      setActive(remaining[0] ?? null)
      setDecisions({})
      setReason('')
      if (remaining.length === 0) onClose()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4">
      <div className="bg-gray-900 border border-red-800 rounded-xl p-6 max-w-2xl w-full space-y-4 max-h-[90vh] overflow-y-auto">
        <div>
          <h3 className="text-lg font-semibold text-red-200">
            Rescope request — step <code>{active.requesting_step_id}</code>
          </h3>
          <p className="text-xs text-gray-400 mt-1">
            The orchestrator paused this session because the step discovered hosts outside
            the project's tier-specific allowlist. Decide each one. Any rejected host is
            permanently dropped for the rest of this session.
          </p>
          {pending.length > 1 && (
            <p className="text-xs text-yellow-300 mt-1">
              {pending.length - 1} more rescope request{pending.length - 1 === 1 ? '' : 's'} pending after this.
            </p>
          )}
        </div>

        <div className="space-y-2">
          {rejected.map((host) => (
            <div
              key={host}
              className="flex items-center gap-3 border border-gray-800 rounded-lg p-2"
            >
              <div className="flex-1">
                <div className="font-mono text-sm text-gray-100">{host}</div>
                <div className="text-[11px] text-gray-500">
                  required tier: {tierMap[host] ?? 'unknown'}
                </div>
              </div>
              <div className="flex gap-1 text-xs">
                <button
                  type="button"
                  className={`px-2 py-1 rounded border ${
                    decisions[host] === 'accept'
                      ? 'bg-emerald-700 border-emerald-500 text-white'
                      : 'border-gray-700 text-gray-400 hover:text-white'
                  }`}
                  onClick={() => flip(host, 'accept')}
                >
                  Accept
                </button>
                <button
                  type="button"
                  className={`px-2 py-1 rounded border ${
                    decisions[host] === 'reject'
                      ? 'bg-red-700 border-red-500 text-white'
                      : 'border-gray-700 text-gray-400 hover:text-white'
                  }`}
                  onClick={() => flip(host, 'reject')}
                >
                  Reject
                </button>
              </div>
            </div>
          ))}
        </div>

        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Optional reason (audit log)"
          className="w-full bg-gray-800 border border-gray-700 rounded p-2 text-xs text-white h-16 resize-none"
        />

        <div className="flex items-center justify-between">
          <div className="text-xs text-gray-500">
            {decidedCount} / {rejected.length} decided
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 rounded text-gray-300 hover:bg-gray-800 text-sm"
            >
              Close
            </button>
            <button
              type="button"
              disabled={!ready || busy}
              onClick={submit}
              className="bg-red-600 hover:bg-red-700 disabled:opacity-40 text-white px-3 py-1.5 rounded text-sm font-medium"
            >
              {busy ? 'Saving…' : 'Submit decision'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
