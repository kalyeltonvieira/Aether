import { api, setCsrfToken } from './apiClient'
import type { AuthInfo, SessionInfo } from '../types/api'

export async function getAuthInfo() { return api.get<AuthInfo>('/auth/info') }
export async function getSession() {
  const session = await api.get<SessionInfo>('/auth/session')
  setCsrfToken(session.csrf_token ?? null)
  return session
}
export async function getLoginUrl() { return api.get<{ url: string }>('/auth/login-url') }
export async function loginWithToken(token: string) {
  const session = await api.post<SessionInfo>('/auth/login', { token })
  setCsrfToken(session.csrf_token ?? null)
  return session
}
export async function logout() {
  await api.post('/auth/logout', {})
  setCsrfToken(null)
}
