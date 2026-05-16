import { useState } from 'react'

interface Props {
  open: boolean
  minChars: number
  onClose: () => void
  onSubmit: (reason: string) => void | Promise<void>
}

export default function ForceApproveModal({ open, minChars, onClose, onSubmit }: Props) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  if (!open) return null

  const tooShort = reason.trim().length < minChars

  const submit = async () => {
    if (tooShort || busy) return
    setBusy(true)
    try {
      await onSubmit(reason.trim())
      setReason('')
      onClose()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4">
      <div className="bg-gray-900 border border-yellow-800 rounded-xl p-6 max-w-lg w-full space-y-4">
        <div>
          <h3 className="text-lg font-semibold text-yellow-200">Force ready for review</h3>
          <p className="text-xs text-gray-400 mt-1">
            This bypasses the AI's ambiguity gate. The safety chain still runs at approval —
            override is logged with reason ({minChars}+ chars) as an{' '}
            <code className="bg-gray-800 px-1 rounded">ambiguity_override</code> audit action.
          </p>
        </div>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder={`Explain why the draft is complete despite high model ambiguity (${minChars}+ chars)…`}
          className="w-full bg-gray-800 border border-gray-700 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-yellow-500 h-32 resize-none"
        />
        <div className="flex items-center justify-between text-xs">
          <span className={tooShort ? 'text-red-400' : 'text-emerald-400'}>
            {reason.trim().length} / {minChars}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 rounded text-gray-300 hover:bg-gray-800"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={tooShort || busy}
              onClick={submit}
              className="bg-yellow-600 hover:bg-yellow-700 disabled:opacity-40 text-white px-3 py-1.5 rounded font-medium"
            >
              {busy ? 'Submitting…' : 'Force ready'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
