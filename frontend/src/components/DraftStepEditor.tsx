import { useEffect, useMemo, useState } from 'react'
import { getAgentCatalog } from '../api/client'

export interface DraftStep {
  order?: number
  agent?: string
  action?: string
  description?: string
  tier?:
    | 'passive_no_target_contact'
    | 'passive_low_touch'
    | 'active_recon'
    | 'active_exploit'
    | string
  config?: Record<string, unknown>
}

export interface DraftPlan {
  target_summary?: string
  risk_level?: 'low' | 'medium' | 'high' | string
  steps?: DraftStep[]
}

interface Props {
  draft: DraftPlan
  onChange: (next: DraftPlan) => void
  readOnly?: boolean
}

const TIER_BADGE: Record<string, string> = {
  passive_no_target_contact: 'bg-emerald-900/40 text-emerald-300 border-emerald-800/50',
  passive_low_touch: 'bg-teal-900/40 text-teal-300 border-teal-800/50',
  active_recon: 'bg-yellow-900/40 text-yellow-300 border-yellow-800/50',
  active_exploit: 'bg-red-900/50 text-red-200 border-red-700/50',
}

// The canonical tier set the <select> offers. If the LLM emits a tier outside
// this set, the select renders an extra "(unknown)" option so the real value is
// shown instead of blanking (and React does not warn about an out-of-range value).
const KNOWN_TIERS = Object.keys(TIER_BADGE)

// A real, executable tool agent from GET /agents/catalog, reduced to the fields
// the editor grounds against: its slug, the valid actions (capabilities), and
// its canonical tier.
interface CatalogTool {
  slug: string
  capabilities: string[]
  tier: string
}

export default function DraftStepEditor({ draft, onChange, readOnly }: Props) {
  const steps = useMemo(() => draft.steps ?? [], [draft.steps])

  // Fetch the tool-agent catalog once so agent/action/tier become dropdowns of
  // tools that actually exist. On any fetch failure `tools` stays empty, which
  // degrades every field back to the original free-text inputs (never breaks).
  const [tools, setTools] = useState<CatalogTool[]>([])

  useEffect(() => {
    let alive = true
    getAgentCatalog()
      .then((res) => {
        if (!alive) return
        const toolAgents = (res.data?.tool_agents ?? []) as Array<{
          agent_type: string
          capabilities?: string[]
          tier?: string
        }>
        setTools(
          toolAgents.map((a) => ({
            slug: a.agent_type,
            capabilities: a.capabilities ?? [],
            tier: a.tier ?? '',
          }))
        )
      })
      .catch(() => {
        /* graceful fallback — free-text inputs remain usable */
      })
    return () => {
      alive = false
    }
  }, [])

  const toolSlugs = useMemo(
    () => tools.map((t) => t.slug).sort((a, b) => a.localeCompare(b)),
    [tools]
  )
  const toolBySlug = useMemo(() => {
    const m = new Map<string, CatalogTool>()
    tools.forEach((t) => m.set(t.slug, t))
    return m
  }, [tools])

  const updateStep = (idx: number, patch: Partial<DraftStep>) => {
    if (readOnly) return
    const next = steps.map((s, i) => (i === idx ? { ...s, ...patch } : s))
    onChange({ ...draft, steps: next })
  }

  const removeStep = (idx: number) => {
    if (readOnly) return
    onChange({ ...draft, steps: steps.filter((_, i) => i !== idx).map((s, i) => ({ ...s, order: i + 1 })) })
  }

  const moveStep = (idx: number, dir: -1 | 1) => {
    if (readOnly) return
    const j = idx + dir
    if (j < 0 || j >= steps.length) return
    const copy = steps.slice()
    ;[copy[idx], copy[j]] = [copy[j], copy[idx]]
    onChange({ ...draft, steps: copy.map((s, i) => ({ ...s, order: i + 1 })) })
  }

  const addStep = () => {
    if (readOnly) return
    const next = [
      ...steps,
      {
        order: steps.length + 1,
        agent: '',
        action: '',
        description: '',
        tier: 'passive_low_touch',
        config: {},
      },
    ]
    onChange({ ...draft, steps: next })
  }

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 flex flex-col h-full">
      <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-200">Draft plan</h2>
        <div className="text-xs text-gray-500">
          {readOnly ? 'read-only after approval' : `${steps.length} steps`}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
        {/* Summary + risk_level */}
        <section className="space-y-2">
          <label className="block text-xs uppercase tracking-wide text-gray-500">
            Target summary
          </label>
          <textarea
            value={draft.target_summary ?? ''}
            onChange={(e) =>
              !readOnly && onChange({ ...draft, target_summary: e.target.value })
            }
            disabled={readOnly}
            className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-white focus:outline-none focus:border-red-500 disabled:opacity-60 h-16 resize-none"
            placeholder="What the AI understood about the target."
          />
          <div className="flex gap-3 items-center">
            <label className="text-xs uppercase tracking-wide text-gray-500">
              Risk level
            </label>
            <select
              value={draft.risk_level ?? 'low'}
              disabled={readOnly}
              onChange={(e) =>
                onChange({ ...draft, risk_level: e.target.value })
              }
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-white"
            >
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
            </select>
          </div>
        </section>

        {/* Steps */}
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <label className="text-xs uppercase tracking-wide text-gray-500">Steps</label>
            {!readOnly && (
              <button
                type="button"
                onClick={addStep}
                className="text-xs text-red-400 hover:text-red-300"
              >
                + add
              </button>
            )}
          </div>

          {steps.length === 0 && (
            <p className="text-xs text-gray-500">
              The AI will populate steps as the interview progresses.
            </p>
          )}

          {steps.map((s, i) => {
            const selectedTool = s.agent ? toolBySlug.get(s.agent) : undefined
            return (
            <div
              key={i}
              className="border border-gray-800 rounded-lg p-3 space-y-2"
            >
              <div className="flex items-center gap-2 text-xs text-gray-400">
                <span className="text-gray-500">#{s.order ?? i + 1}</span>
                <span
                  className={`px-2 py-0.5 rounded border text-[11px] uppercase ${
                    TIER_BADGE[s.tier ?? ''] ?? 'bg-gray-800 text-gray-300 border-gray-700'
                  }`}
                >
                  {s.tier ?? 'unspecified'}
                </span>
                <div className="flex-1" />
                {!readOnly && (
                  <>
                    <button
                      type="button"
                      className="text-gray-500 hover:text-white"
                      onClick={() => moveStep(i, -1)}
                      disabled={i === 0}
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      className="text-gray-500 hover:text-white"
                      onClick={() => moveStep(i, 1)}
                      disabled={i === steps.length - 1}
                    >
                      ↓
                    </button>
                    <button
                      type="button"
                      className="text-red-500 hover:text-red-300"
                      onClick={() => removeStep(i)}
                    >
                      ✕
                    </button>
                  </>
                )}
              </div>

              <div className="grid grid-cols-2 gap-2 text-xs">
                <label className="text-gray-500">agent</label>
                {toolSlugs.length > 0 ? (
                  <select
                    value={s.agent ?? ''}
                    disabled={readOnly}
                    onChange={(e) => {
                      const slug = e.target.value
                      const tool = toolBySlug.get(slug)
                      const patch: Partial<DraftStep> = { agent: slug }
                      if (tool) {
                        // Ground the tier to the tool's canonical tier, and drop
                        // an action that the newly-selected tool can't perform.
                        if (tool.tier) patch.tier = tool.tier
                        if (s.action && !tool.capabilities.includes(s.action)) {
                          patch.action = ''
                        }
                      }
                      updateStep(i, patch)
                    }}
                    className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-white"
                  >
                    <option value="">— select agent —</option>
                    {toolSlugs.map((slug) => (
                      <option key={slug} value={slug}>
                        {slug}
                      </option>
                    ))}
                    {s.agent && !toolBySlug.has(s.agent) && (
                      <option value={s.agent}>{s.agent} (unknown)</option>
                    )}
                  </select>
                ) : (
                  <input
                    value={s.agent ?? ''}
                    disabled={readOnly}
                    onChange={(e) => updateStep(i, { agent: e.target.value })}
                    className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-white"
                    placeholder="passive_recon"
                  />
                )}
                <label className="text-gray-500">action</label>
                {selectedTool ? (
                  <select
                    value={s.action ?? ''}
                    disabled={readOnly}
                    onChange={(e) => updateStep(i, { action: e.target.value })}
                    className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-white"
                  >
                    <option value="">— select action —</option>
                    {selectedTool.capabilities.map((cap) => (
                      <option key={cap} value={cap}>
                        {cap}
                      </option>
                    ))}
                    {s.action &&
                      !selectedTool.capabilities.includes(s.action) && (
                        <option value={s.action}>{s.action} (unknown)</option>
                      )}
                  </select>
                ) : (
                  <input
                    value={s.action ?? ''}
                    disabled={readOnly}
                    onChange={(e) => updateStep(i, { action: e.target.value })}
                    className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-white"
                    placeholder="passive_dns_recon"
                  />
                )}
                <label className="text-gray-500">tier</label>
                <select
                  value={s.tier ?? 'passive_low_touch'}
                  disabled={readOnly}
                  onChange={(e) => updateStep(i, { tier: e.target.value })}
                  className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-white"
                >
                  <option value="passive_no_target_contact">
                    passive_no_target_contact
                  </option>
                  <option value="passive_low_touch">passive_low_touch</option>
                  <option value="active_recon">active_recon</option>
                  <option value="active_exploit">active_exploit</option>
                  {s.tier && !KNOWN_TIERS.includes(s.tier) && (
                    <option value={s.tier}>{s.tier} (unknown)</option>
                  )}
                </select>
                <label className="text-gray-500">description</label>
                <input
                  value={s.description ?? ''}
                  disabled={readOnly}
                  onChange={(e) => updateStep(i, { description: e.target.value })}
                  className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-white"
                />
                <label className="text-gray-500 self-start mt-1">config (json)</label>
                <textarea
                  value={JSON.stringify(s.config ?? {}, null, 2)}
                  disabled={readOnly}
                  onChange={(e) => {
                    try {
                      updateStep(i, { config: JSON.parse(e.target.value) })
                    } catch {
                      // ignore invalid JSON while user is typing
                    }
                  }}
                  className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-white font-mono text-[11px] h-20 resize-none"
                />
              </div>
            </div>
            )
          })}
        </section>
      </div>
    </div>
  )
}
