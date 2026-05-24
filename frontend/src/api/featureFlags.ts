/**
 * Feature-flag API client (v4.0 P3-main).
 *
 * Mirrors `backend/app/api/v1/feature_flags.py`. Public endpoint — no token
 * required so the login page can branch before authentication.
 */
import api from './client'

export interface FeatureFlags {
  osa_flow_ui_enabled: boolean
}

export async function getFeatureFlags(): Promise<FeatureFlags> {
  const { data } = await api.get<FeatureFlags>('/config/feature-flags')
  return data
}
