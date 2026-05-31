import api from './client'

export interface CredentialRow {
  id: string
  provider: 'anthropic' | 'openai' | 'google'
  credential_type: 'api_key' | 'oauth_token'
  label: string | null
  created_at: string
  expires_at: string | null
  last_used_at: string | null
  revoked_at: string | null
}

export interface CreateCredentialBody {
  provider: 'anthropic' | 'openai' | 'google'
  credential_type: 'api_key'
  label: string
  api_key: string
}

export async function listCredentials(): Promise<CredentialRow[]> {
  const { data } = await api.get<CredentialRow[]>('/credentials/llm-providers')
  return data
}

export async function createCredential(body: CreateCredentialBody): Promise<CredentialRow> {
  const { data } = await api.post<CredentialRow>('/credentials/llm-providers', body)
  return data
}

export async function revokeCredential(credId: string): Promise<void> {
  await api.delete(`/credentials/llm-providers/${credId}`)
}

export async function startOAuth(provider: 'anthropic' | 'openai' | 'google'): Promise<{ auth_url: string; state: string }> {
  const { data } = await api.post<{ auth_url: string; state: string }>(
    `/auth/llm-providers/${provider}/oauth/start`
  )
  return data
}
