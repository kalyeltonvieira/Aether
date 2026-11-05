import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { getAuthInfo, getLoginUrl, getSession, loginWithToken, logout as logoutRequest } from '../services/auth'
import { ApiError } from '../services/apiClient'
import type { AuthInfo, SessionInfo } from '../types/api'

interface AuthContextValue {
  authInfo: AuthInfo | null
  session: SessionInfo | null
  loading: boolean
  error: Error | null
  canWrite: boolean
  refresh: () => Promise<void>
  startOAuth: () => Promise<void>
  loginToken: (token: string) => Promise<void>
  logout: () => Promise<void>
}
const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [authInfo, setAuthInfo] = useState<AuthInfo | null>(null)
  const [session, setSession] = useState<SessionInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<Error | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const info = await getAuthInfo()
      setAuthInfo(info)
      try { setSession(await getSession()) } catch (reason) {
        if (!(reason instanceof ApiError && reason.status === 401)) throw reason
        setSession({ authenticated: false })
      }
    } catch (reason) { setError(reason instanceof Error ? reason : new Error('Não foi possível verificar a sessão.')) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { void refresh() }, [refresh])

  const value = useMemo<AuthContextValue>(() => ({
    authInfo, session, loading, error, canWrite: session?.authenticated === true && session.role === 'operator', refresh,
    startOAuth: async () => {
      setLoading(true); setError(null)
      try { const { url } = await getLoginUrl(); window.location.assign(url) }
      catch (reason) { setError(reason instanceof Error ? reason : new Error('Falha ao iniciar o login Manus OAuth.')) }
      finally { setLoading(false) }
    },
    loginToken: async (token) => { setLoading(true); setError(null); try { setSession(await loginWithToken(token)) } catch (reason) { const next = reason instanceof Error ? reason : new Error('Falha no login.'); setError(next); throw next } finally { setLoading(false) } },
    logout: async () => { await logoutRequest(); setSession({ authenticated: false }) },
  }), [authInfo, session, loading, error, refresh])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth precisa estar dentro de AuthProvider')
  return value
}
