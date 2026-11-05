import type { ReactNode } from 'react'
import { AlertCircle, CheckCircle2, CircleDashed, Info, LoaderCircle, RefreshCw, ShieldAlert } from 'lucide-react'
import { useAuth } from '../app/AuthContext'

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description?: string; actions?: ReactNode }) {
  return <header className="page-header"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1>{description && <p>{description}</p>}</div>{actions && <div className="page-actions">{actions}</div>}</header>
}
export function Panel({ children, title, description, action, className = '' }: { children: ReactNode; title?: string; description?: string; action?: ReactNode; className?: string }) {
  return <section className={`panel ${className}`}><div className="panel-heading">{title && <div><h2>{title}</h2>{description && <p>{description}</p>}</div>}{action && <div className="panel-action">{action}</div>}</div>{children}</section>
}
export function StatCard({ label, value, detail, tone = 'default', icon }: { label: string; value: ReactNode; detail?: ReactNode; tone?: 'default' | 'good' | 'warning' | 'danger' | 'cyan'; icon?: ReactNode }) {
  return <div className={`stat-card stat-card--${tone}`}><div className="stat-card-top"><span>{label}</span>{icon && <span className="stat-icon">{icon}</span>}</div><strong>{value}</strong>{detail && <small>{detail}</small>}</div>
}
export function StatusBadge({ status, label }: { status: string | boolean | null | undefined; label?: string }) {
  const normalized = String(status ?? 'indisponível').toLowerCase()
  const tone = normalized === 'ok' || normalized === 'ready' || normalized === 'available' || normalized === 'true' || normalized === 'processed' ? 'good' : normalized.includes('error') || normalized.includes('fail') || normalized === 'false' ? 'danger' : normalized.includes('warn') || normalized.includes('pending') || normalized === 'indisponível' ? 'warning' : 'default'
  return <span className={`status-badge status-badge--${tone}`}><span className="status-dot" />{label ?? String(status ?? 'indisponível')}</span>
}
export function LoadingBlock({ label = 'Carregando dados reais…' }: { label?: string }) { return <div className="state-block state-block--loading" role="status"><LoaderCircle className="spin" size={22} /><span>{label}</span></div> }
export function EmptyState({ title, description, action }: { title: string; description: string; action?: ReactNode }) { return <div className="state-block"><CircleDashed size={26} /><strong>{title}</strong><span>{description}</span>{action}</div> }
export function ErrorState({ error, retry }: { error: Error | null; retry?: () => void }) { return <div className="state-block state-block--error" role="alert"><AlertCircle size={24} /><strong>Não foi possível carregar</strong><span>{error?.message ?? 'A API não retornou dados.'}</span>{retry && <button className="button button--ghost" onClick={retry}><RefreshCw size={14} /> Tentar novamente</button>}</div> }
export function InfoCallout({ children, tone = 'info' }: { children: ReactNode; tone?: 'info' | 'warning' | 'error' }) { const Icon = tone === 'error' ? AlertCircle : tone === 'warning' ? ShieldAlert : Info; return <div className={`callout callout--${tone}`}><Icon size={16} /> <span>{children}</span></div> }
export function PermissionNotice() { const { canWrite, session } = useAuth(); if (canWrite) return null; const identity = session?.open_id ?? session?.openId ?? session?.subject; return <InfoCallout tone="warning">Sessão somente leitura{identity ? <> · identidade verificada: <code>{identity}</code></> : ''}. O servidor não concedeu <code>operator</code>; criações, processamento e configurações ficam desabilitados.</InfoCallout> }
export function JsonPreview({ value }: { value: unknown }) { return <pre className="json-preview">{JSON.stringify(value, null, 2)}</pre> }
export function BooleanIcon({ value }: { value: boolean | null | undefined }) { return value ? <CheckCircle2 className="icon-good" size={16} /> : <span className="muted">—</span> }
