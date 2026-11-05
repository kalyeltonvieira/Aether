import { useState } from 'react'
import { ArrowRight, KeyRound, LockKeyhole, ShieldCheck } from 'lucide-react'
import { useAuth } from '../app/AuthContext'

export function LoginPage() {
  const { authInfo, error, loading, startOAuth, loginToken } = useAuth()
  const [token, setToken] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)
  const tokenMode = authInfo?.mode === 'token'
  const submitToken = async (event: React.FormEvent) => {
    event.preventDefault(); setSubmitting(true); setLocalError(null)
    try { await loginToken(token); setToken('') } catch (reason) { setLocalError(reason instanceof Error ? reason.message : 'Falha no login.') } finally { setSubmitting(false) }
  }
  return <main className="login-shell">
    <section className="login-card" aria-labelledby="login-title">
      <div className="brand-lockup brand-lockup--large"><span className="brand-mark" aria-hidden="true"><span /></span><span>AETHER <b>Studio</b></span></div>
      <div className="eyebrow">OPERATOR CONSOLE / SECURE SESSION</div>
      <h1 id="login-title">Inspecione o motor<br /><em>sem perder a prova.</em></h1>
      <p className="login-copy">Uma superfície operacional para conhecimento, raciocínio e sinais de execução — sem dados de demonstração.</p>
      {(error || localError) && <div className="callout callout--error" role="alert">{localError ?? error?.message}</div>}
      {authInfo && !authInfo.login_available && <div className="callout" role="status">O servidor não disponibilizou um método de login nesta instalação.</div>}
      {tokenMode ? <form onSubmit={submitToken} className="login-form">
        <label htmlFor="access-token">Token da instalação</label>
        <div className="input-with-icon"><KeyRound size={16} aria-hidden="true" /><input id="access-token" type="password" autoComplete="off" value={token} onChange={(event) => setToken(event.target.value)} placeholder="Cole o token privado" required /></div>
        <button className="button button--primary button--wide" type="submit" disabled={submitting || !token}>{submitting ? 'Validando…' : 'Abrir sessão'} <ArrowRight size={16} /></button>
        <small>O token é enviado apenas para a troca de sessão e limpo após o login. Ele não é salvo no navegador.</small>
      </form> : <button className="button button--primary button--wide" onClick={() => void startOAuth()} disabled={loading || authInfo?.login_available === false}>{loading ? 'Verificando…' : 'Entrar com Manus OAuth'} <ArrowRight size={16} /></button>}
      <div className="login-assurance"><ShieldCheck size={17} /><span>Sessões HttpOnly · CSRF por mutação · origem validada</span></div>
      <div className="login-footer"><LockKeyhole size={14} /> AETHER Studio só expõe operações autorizadas pelo servidor.</div>
    </section>
  </main>
}
