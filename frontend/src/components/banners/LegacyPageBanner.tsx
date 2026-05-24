/**
 * LegacyPageBanner — flag-gated wrapper around DeprecationBanner (v4.0 P3-main).
 *
 * Each legacy page (Monitor / PentestWorkflow / AgentCatalog) renders
 * `<LegacyPageBanner pageName="Monitor" />` at the top of its component
 * tree. When `osa_flow_ui_enabled=false` the banner stays hidden. When
 * `true` it renders the `<DeprecationBanner>`.
 */
import { useFeatureFlags } from '@/hooks/useFeatureFlags'

import { DeprecationBanner } from './DeprecationBanner'

export function LegacyPageBanner({ pageName }: { pageName: string }) {
  const flags = useFeatureFlags()
  if (!flags?.osa_flow_ui_enabled) return null
  return <DeprecationBanner pageName={pageName} />
}
