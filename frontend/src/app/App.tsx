import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './AuthContext'
import { LiveUpdatesProvider } from '../hooks/useLiveUpdates'
import { AppShell } from '../layouts/AppShell'
import { LoginPage } from '../pages/LoginPage'
import { LoadingBlock, ErrorState } from '../components/ui'

const DashboardPage = lazy(() => import('../pages/DashboardPage').then((page) => ({ default: page.DashboardPage })))
const KnowledgePage = lazy(() => import('../pages/KnowledgePage').then((page) => ({ default: page.KnowledgePage })))
const GraphPage = lazy(() => import('../pages/GraphPage').then((page) => ({ default: page.GraphPage })))
const ReasoningPage = lazy(() => import('../pages/ReasoningPage').then((page) => ({ default: page.ReasoningPage })))
const ProofsPage = lazy(() => import('../pages/ProofsPage').then((page) => ({ default: page.ProofsPage })))
const MemoryPage = lazy(() => import('../pages/MemoryPage').then((page) => ({ default: page.MemoryPage })))
const EventsPage = lazy(() => import('../pages/EventsPage').then((page) => ({ default: page.EventsPage })))
const PerformancePage = lazy(() => import('../pages/PerformancePage').then((page) => ({ default: page.PerformancePage })))
const SettingsPage = lazy(() => import('../pages/SettingsPage').then((page) => ({ default: page.SettingsPage })))

export function App() {
  const { loading, error, session } = useAuth()
  if (loading) return <main className="centered-state"><LoadingBlock label="Verificando sessão segura…" /></main>
  if (error && !session) return <main className="centered-state"><ErrorState error={error} /></main>
  if (!session?.authenticated) return <LoginPage />
  return <LiveUpdatesProvider><Suspense fallback={<main className="centered-state"><LoadingBlock label="Carregando módulo…" /></main>}><Routes><Route element={<AppShell />}><Route path="/" element={<DashboardPage />} /><Route path="/knowledge" element={<KnowledgePage />} /><Route path="/graph" element={<GraphPage />} /><Route path="/reasoning" element={<ReasoningPage />} /><Route path="/proofs" element={<ProofsPage />} /><Route path="/memory" element={<MemoryPage />} /><Route path="/events" element={<EventsPage />} /><Route path="/performance" element={<PerformancePage />} /><Route path="/settings" element={<SettingsPage />} /><Route path="*" element={<Navigate to="/" replace />} /></Route></Routes></Suspense></LiveUpdatesProvider>
}
