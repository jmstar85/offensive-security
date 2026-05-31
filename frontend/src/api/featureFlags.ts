/**
 * Feature-flag API client.
 *
 * Mirrors `backend/app/api/v1/feature_flags.py`. Public endpoint — no token
 * required so the login page can branch before authentication.
 */
import api from './client'

export interface FeatureFlags {
  osa_flow_ui_enabled: boolean
  /**
   * Gates the Kali coexistence tool surface (kali_gobuster, kali_sqlmap,
   * kali_nikto). Default false. When false the backend hides kali_* from
   * /agents/catalog and refuses get_adapter; the UI uses this to render
   * a "Kali disabled" notice if a workflow still references those slugs.
   */
  osa_kali_backend_enabled: boolean
  /** Gates multi-LLM credential management UI and provider routing. Default false. */
  osa_multi_provider_llm?: boolean
  /** Gates the Coordinator split-pane UI (understanding + plan-of-work + conversation). Default false. */
  osa_coordinator_enabled?: boolean
  /** Gates AgentFamilyTree UI and family-spawning API surface. Default false. */
  osa_xbow_families_enabled?: boolean
}

export async function getFeatureFlags(): Promise<FeatureFlags> {
  const { data } = await api.get<FeatureFlags>('/config/feature-flags')
  return data
}
