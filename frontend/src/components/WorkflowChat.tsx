import { useEffect, useRef, useState } from 'react'

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  ambiguity?: number | null
  blockers?: string[]
  reasoning?: string
}

/**
 * v4.0 P4 ask-tool prompt. Surfaced inline at the end of the chat history
 * when a role (typically Pentester or Generator) emits `ask_pending` via
 * the WebSocket `tasks` topic. The user replies by clicking an option
 * chip (or typing in the chat input).
 */
export interface AskPrompt {
  id: string
  role: string
  question: string
  options: string[]
}

interface Props {
  messages: ChatMessage[]
  disabled?: boolean
  ambiguityScore?: number
  /** Group B: the ambiguity ceiling the interview must reach before
   * ready_for_review (0.20 when autoblock is on, else 0.35). Drives the header
   * colour + the "target ≤ X.XX" hint. */
  ambiguityTarget?: number
  turnCount?: number
  maxTurns?: number
  onSend: (text: string) => void | Promise<void>
  askPrompts?: AskPrompt[]
  onAskReply?: (promptId: string, reply: string) => void | Promise<void>
  /** Panel heading. Defaults to "Interview" (Coordinator flow); the Assistant
   * mode chat surface (newflow PR8) passes "Assistant" to reuse this panel. */
  title?: string
  /** Placeholder for the input box when not disabled. */
  placeholder?: string
}

export default function WorkflowChat({
  messages,
  disabled,
  ambiguityScore,
  ambiguityTarget = 0.35,
  turnCount,
  maxTurns,
  onSend,
  askPrompts,
  onAskReply,
  title = 'Interview',
  placeholder = 'Reply to the AI…',
}: Props) {
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [messages.length])

  // Group B ask-cards: only the MOST RECENT assistant turn's blockers are still
  // actionable (older ones are stale history). Clicking one seeds a targeted
  // answer stub into the input so the operator resolves that specific ambiguity,
  // driving the score toward the target.
  const latestBlockers = (() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === 'assistant') return messages[i].blockers ?? []
    }
    return []
  })()

  const askAbout = (blocker: string) => {
    const stub = `Re: "${blocker}" — `
    setInput((prev) => (prev.includes(stub) ? prev : prev ? `${prev}\n${stub}` : stub))
    textareaRef.current?.focus()
  }

  const send = async () => {
    if (!input.trim() || busy || disabled) return
    setBusy(true)
    try {
      await onSend(input.trim())
      setInput('')
    } finally {
      setBusy(false)
    }
  }

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    void send()
  }

  const turnBadge = turnCount !== undefined && maxTurns !== undefined
    ? `${turnCount}/${maxTurns} turns`
    : ''

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 flex flex-col h-full">
      <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-200">{title}</h2>
        <div className="text-xs text-gray-500 flex gap-3">
          {ambiguityScore !== undefined && (
            <span title={`Interview target ≤ ${ambiguityTarget.toFixed(2)}`}>
              ambiguity{' '}
              <span
                className={
                  ambiguityScore <= ambiguityTarget ? 'text-green-400' : 'text-yellow-400'
                }
              >
                {ambiguityScore.toFixed(2)}
              </span>
              <span className="text-gray-600"> / ≤{ambiguityTarget.toFixed(2)}</span>
            </span>
          )}
          {turnBadge && <span>{turnBadge}</span>}
        </div>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {messages.length === 0 && (
          <p className="text-sm text-gray-500">
            {title === 'Assistant'
              ? 'Send a message to start driving the engagement interactively.'
              : 'Start the interview by describing the target environment.'}
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

        {/* v4.0 P4 — ask-tool prompts surfaced inline */}
        {askPrompts?.map((p) => (
          <div
            key={p.id}
            className="text-sm border border-amber-700/50 bg-amber-950/30 rounded-lg p-3"
            data-testid={`ask-prompt-${p.id}`}
          >
            <div className="text-xs uppercase tracking-wide text-amber-400 mb-1">
              {p.role} asks
            </div>
            <p className="text-gray-100 whitespace-pre-wrap">{p.question}</p>
            {p.options.length > 0 && (
              <div className="flex flex-wrap gap-2 mt-2">
                {p.options.map((opt) => (
                  <button
                    key={opt}
                    type="button"
                    onClick={() => onAskReply?.(p.id, opt)}
                    className="text-xs bg-amber-900/40 hover:bg-amber-800/60 text-amber-100 px-2.5 py-1 rounded-full border border-amber-700/40"
                  >
                    {opt}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Group B — clickable ask-cards for the latest turn's open questions.
          Each resolves a specific ambiguity; clicking seeds a targeted answer. */}
      {!disabled && latestBlockers.length > 0 && (
        <div className="border-t border-gray-800 px-3 pt-3 space-y-2" data-testid="ask-cards">
          <div className="text-xs uppercase tracking-wide text-amber-400">
            Open questions — click to answer
          </div>
          <div className="flex flex-wrap gap-2">
            {latestBlockers.map((b, i) => (
              <button
                key={i}
                type="button"
                onClick={() => askAbout(b)}
                data-testid={`ask-card-${i}`}
                title={`Answer: ${b}`}
                className="text-left text-xs bg-amber-950/40 hover:bg-amber-900/50 text-amber-100 px-2.5 py-1.5 rounded-lg border border-amber-800/40 max-w-full"
              >
                <span className="text-amber-500 mr-1">?</span>
                <span className="align-middle">{b}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <form onSubmit={submit} className="border-t border-gray-800 p-3 flex gap-2">
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            // Enter sends; Shift+Enter inserts a newline.
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              void send()
            }
          }}
          disabled={disabled || busy}
          placeholder={
            disabled
              ? 'Interview locked — review the draft on the right.'
              : placeholder
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
