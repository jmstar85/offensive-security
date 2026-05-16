import { useEffect, useRef, useState } from 'react'

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  ambiguity?: number | null
  blockers?: string[]
  reasoning?: string
}

interface Props {
  messages: ChatMessage[]
  disabled?: boolean
  ambiguityScore?: number
  turnCount?: number
  maxTurns?: number
  onSend: (text: string) => void | Promise<void>
}

export default function WorkflowChat({
  messages,
  disabled,
  ambiguityScore,
  turnCount,
  maxTurns,
  onSend,
}: Props) {
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const scrollRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [messages.length])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim() || busy) return
    setBusy(true)
    try {
      await onSend(input.trim())
      setInput('')
    } finally {
      setBusy(false)
    }
  }

  const turnBadge = turnCount !== undefined && maxTurns !== undefined
    ? `${turnCount}/${maxTurns} turns`
    : ''

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 flex flex-col h-full">
      <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-200">Interview</h2>
        <div className="text-xs text-gray-500 flex gap-3">
          {ambiguityScore !== undefined && (
            <span>
              ambiguity{' '}
              <span className={ambiguityScore <= 0.35 ? 'text-green-400' : 'text-yellow-400'}>
                {ambiguityScore.toFixed(2)}
              </span>
            </span>
          )}
          {turnBadge && <span>{turnBadge}</span>}
        </div>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {messages.length === 0 && (
          <p className="text-sm text-gray-500">
            Start the interview by describing the target environment.
          </p>
        )}
        {messages.map((m, i) => (
          <div key={i} className="text-sm">
            <div className="text-xs uppercase tracking-wide text-gray-500 mb-0.5">
              {m.role}
            </div>
            <div
              className={
                m.role === 'user'
                  ? 'bg-gray-800 rounded-lg px-3 py-2 text-gray-100 whitespace-pre-wrap'
                  : 'bg-red-950/40 border border-red-900/30 rounded-lg px-3 py-2 text-gray-100 whitespace-pre-wrap'
              }
            >
              {m.role === 'assistant' ? (
                <>
                  {m.reasoning && (
                    <p className="text-gray-300 mb-2">{m.reasoning}</p>
                  )}
                  {m.blockers && m.blockers.length > 0 && (
                    <>
                      <div className="text-xs text-gray-400 mt-1">unresolved:</div>
                      <ul className="list-disc list-inside text-yellow-300 text-xs">
                        {m.blockers.map((b, j) => (
                          <li key={j}>{b}</li>
                        ))}
                      </ul>
                    </>
                  )}
                  {!m.reasoning && !m.blockers?.length && <span>{m.content}</span>}
                </>
              ) : (
                m.content
              )}
            </div>
          </div>
        ))}
      </div>

      <form onSubmit={submit} className="border-t border-gray-800 p-3 flex gap-2">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={disabled || busy}
          placeholder={
            disabled
              ? 'Interview locked — review the draft on the right.'
              : 'Reply to the AI…'
          }
          className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-red-500 resize-none h-14 disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={disabled || busy || !input.trim()}
          className="bg-red-600 hover:bg-red-700 disabled:opacity-40 text-white px-4 rounded-lg font-medium self-end h-10"
        >
          {busy ? 'Sending…' : 'Send'}
        </button>
      </form>
    </div>
  )
}
