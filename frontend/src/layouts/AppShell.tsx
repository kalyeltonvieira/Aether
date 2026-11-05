import { useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { Activity, BrainCircuit, ChevronLeft, CircleGauge, Database, FileSearch, GitBranch, HardDrive, LayoutDashboard, Menu, Network, Settings, Sparkles, X } from 'lucide-react'
import { useAuth } from '../app/AuthContext'
import { useLiveUpdates } from '../hooks/useLiveUpdates'
import { useApiData } from '../hooks/useApiData'
import { api } from '../services/apiClient'
import type { StatusResponse } from '../types/api'
import { StatusBadge } from '../components/ui'

const nav = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/knowledge', label: 'Knowledge Explorer', icon: Database },
  { to: '/graph', label: 'Knowledge Graph', icon: Network },
  { to: '/reasoning', label: 'Reasoning Console', icon: BrainCircuit },
  { to: '/proofs', label: 'Proof Explorer', icon: FileSearch },
  { to: '/memory', label: 'Memory Center', icon: HardDrive },
  { to: '/events', label: 'Event Monitor', icon: Activity },
  { to: '/performance', label: 'Performance', icon: CircleGauge },
  { to: '/settings', label: 'Settings', icon: Settings },
]

export function AppShell() {
  const [open, setOpen] = useState(false)
  const location = useLocation()
  const { session, logout } = useAuth()
  const live = useLiveUpdates()
  const status = useApiData(() => api.get<StatusResponse>('/status'), [live.revision])
  const current = nav.find((item) => item.to === location.pathname)?.label ?? 'AETHER Studio'
  return <div className="app-shell">
    <button className="mobile-menu" aria-label="Abrir menu" onClick={() => setOpen(true)}><Menu size={20} /></button>
    {open && <button className="drawer-scrim" aria-label="Fechar menu" onClick={() => setOpen(false)} />}
    <aside className={`sidebar ${open ? 'sidebar--open' : ''}`}>
      <div className="sidebar-top"><div className="brand-lockup"><span className="brand-mark" aria-hidden="true"><span /></span><span>AETHER <b>Studio</b></span></div><button className="sidebar-close" onClick={() => setOpen(false)} aria-label="Fechar menu"><X size={18} /></button></div>
      <div className="sidebar-context"><span className="context-kicker">KNOWLEDGE RUNTIME</span><span className="context-value"><span className="live-dot" /> Sessão operacional</span></div>
      <nav aria-label="Navegação principal" className="main-nav">{nav.map(({ to, label, icon: Icon, end }) => <NavLink key={to} to={to} end={end} onClick={() => setOpen(false)} className={({ isActive }) => `nav-item ${isActive ? 'nav-item--active' : ''}`}><Icon size={18} /><span>{label}</span>{to === '/events' && <span className="nav-signal" />}</NavLink>)}</nav>
      <div className="sidebar-bottom"><div className="sidebar-health"><span>API endpoint</span><StatusBadge status={status.loading ? 'checking' : status.error ? 'offline' : status.data?.api.status ?? null} /></div><button className="user-chip" onClick={() => void logout()} title="Encerrar sessão"><span className="avatar">{(session?.role ?? 'r').slice(0, 1).toUpperCase()}</span><span><b>{session?.role === 'operator' ? 'Operator' : 'Reader'}</b><small>Encerrar sessão</small></span><ChevronLeft size={15} /></button></div>
    </aside>
    <main className="workspace"><header className="topbar"><div className="topbar-title"><span className="topbar-section">AETHER / {current}</span><span className="topbar-separator">·</span><span className="topbar-subtitle">Evidence-first runtime observability</span></div><div className="topbar-meta"><span className={`connection-pill ${live.connected ? 'connection-pill--online' : live.reconnecting ? 'connection-pill--reconnecting' : ''}`}><span className="status-dot" />{live.connected ? 'Live updates' : live.reconnecting ? 'Reconnecting' : 'Polling'}</span><span className="version-pill">v1 / local</span></div></header><div className="content"><Outlet /></div></main>
  </div>
}
