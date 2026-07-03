import api from './client'

export interface OllamaModelsResponse {
  models: string[]
  reachable: boolean
}

// Live Ollama model list for the new-flow provider/model selector (newflow
// PR8). Backend proxies GET {ollama_base_url}/api/tags and fails soft:
// unreachable → { models: [settings.ollama_model], reachable: false }.
export async function getOllamaModels(): Promise<OllamaModelsResponse> {
  const { data } = await api.get<OllamaModelsResponse>('/config/ollama/models')
  return data
}
