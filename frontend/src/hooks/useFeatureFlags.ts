/**
 * useFeatureFlags — fetch `/api/v1/config/feature-flags` once per app
 * lifetime (v4.0 P3-main).
 *
 * Legacy pages (Monitor / PentestWorkflow / AgentCatalog / InteractionDashboard)
 * use this hook to decide whether to render the v4.0 deprecation banner.
 */
import { useEffect, useState } from 'react'

import { FeatureFlags, getFeatureFlags } from '@/api/featureFlags'

let cache: FeatureFlags | null = null
let inFlight: Promise<FeatureFlags> | null = null

export function useFeatureFlags(): FeatureFlags | null {
  const [flags, setFlags] = useState<FeatureFlags | null>(cache)

  useEffect(() => {
    if (cache) return
    if (!inFlight) {
      inFlight = getFeatureFlags()
        .then((f) => {
          cache = f
          return f
        })
        .finally(() => {
          inFlight = null
        })
    }
    inFlight
      .then((f) => setFlags(f))
      .catch(() =>
        // Safe fallback when the endpoint is unreachable — match the backend
        // defaults so the UI stays in the conservative state (legacy UI, Kali off).
        setFlags({
          osa_flow_ui_enabled: false,
          osa_kali_backend_enabled: false,
          osa_multi_provider_llm: false,
        }),
      )
  }, [])

  return flags
}
