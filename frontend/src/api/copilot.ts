import api from './client'

export interface CopilotModelsResponse {
  models: string[]
  reachable: boolean
}

// Live GitHub Copilot model list for the new-flow provider/model selector.
// Backend resolves the user's Copilot credential and lists Copilot's own model
// catalog (the same one the editor picker uses), so the dropdown always shows
// the latest available models. Fails soft: no credential / unreachable →
// { models: <curated modern fallback>, reachable: false }. Ids are namespaced
// `copilot/<model>`.
export async function getCopilotModels(): Promise<CopilotModelsResponse> {
  const { data } = await api.get<CopilotModelsResponse>('/config/copilot/models')
  return data
}
