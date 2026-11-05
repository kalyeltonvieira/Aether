import { Activity, Cpu, Database, Gauge, Layers3, ShieldAlert, Zap } from 'lucide-react'
import { useApiData } from '../hooks/useApiData'
import { useLiveUpdates } from '../hooks/useLiveUpdates'
import { api } from '../services/apiClient'
import type { StatusResponse } from '../types/api'
import { EmptyState, ErrorState, InfoCallout, JsonPreview, LoadingBlock, PageHeader, Panel, StatCard, StatusBadge } from '../components/ui'

const unavailable = <span className="unavailable">indisponível</span>
const format = (value: number | null | undefined, suffix = '') => value === null || value === undefined ? unavailable : `${value.toLocaleString('pt-BR')}${suffix}`

export function DashboardPage() {
  const live = useLiveUpdates()
  const state = useApiData(() => api.get<StatusResponse>('/status'), [live.revision])
  if (state.loading && !state.data) return <><PageHeader eyebrow="AETHER / OPERATIONS" title="Dashboard" description="Observabilidade do runtime, sem estimativas silenciosas." /><LoadingBlock /></>
  if (state.error && !state.data) return <><PageHeader eyebrow="AETHER / OPERATIONS" title="Dashboard" /><ErrorState error={state.error} retry={state.reload} /></>
  const status = state.data
  if (!status) return <EmptyState title="Status indisponível" description="O endpoint /status não retornou um snapshot real." />
  const coreIncomplete = status.core.complete === false
  return <div className="page-stack">
    <PageHeader eyebrow="AETHER / OPERATIONS" title="Dashboard" description="O estado do processo real, observado nesta sessão." actions={<span className="last-observed"><span className="live-dot" /> atualização via {live.connected ? 'WebSocket' : 'polling'}</span>} />
    <div className="metric-grid metric-grid--six">
      <StatCard label="Core" value={<StatusBadge status={coreIncomplete ? 'incomplete' : status.core.status} label={coreIncomplete ? 'incompleto' : status.core.status} />} detail={<>{format(status.core.entities)} entidades · {format(status.core.facts)} fatos · {format(status.core.conclusions)} conclusões</>} icon={<Database size={17} />} tone={coreIncomplete ? 'warning' : status.core.status === 'ready' ? 'good' : 'warning'} />
      <StatCard label="API" value={<StatusBadge status={status.api.status} />} detail={status.api.version ?? 'versão indisponível'} icon={<Zap size={17} />} tone={status.api.status === 'ok' || status.api.status === 'ready' ? 'good' : 'warning'} />
      <StatCard label="Rust Engine" value={<StatusBadge status={status.rust.available} label={status.rust.available ? 'available' : 'unavailable'} />} detail={<>{format(status.rust.operations)} operações observadas</>} icon={<Layers3 size={17} />} tone={status.rust.available ? 'cyan' : 'default'} />
      <StatCard label="Memória residente" value={format(status.memory.resident_bytes as number | null | undefined)} detail={status.memory.budget_bytes ? <>orçamento {format(status.memory.budget_bytes as number)}</> : 'orçamento indisponível'} icon={<Gauge size={17} />} tone="cyan" />
      <StatCard label="CPU" value={format(status.cpu_percent, '%')} detail="medição do processo / host" icon={<Cpu size={17} />} />
      <StatCard label="Latência última query" value={format(status.last_query_latency_ms, ' ms')} detail={<>{format(status.queries_executed)} consultas executadas</>} icon={<Activity size={17} />} />
    </div>
    {coreIncomplete && <InfoCallout tone="warning">O fechamento do core está incompleto: {status.core.stale_reason ?? 'motivo não informado pelo runtime'}</InfoCallout>}
    <div className="dashboard-columns"><Panel title="Atividade recente" description="Eventos e operações efetivamente observados."><ActivityList items={status.activity} /></Panel><Panel title="Alertas" description="Sinais reportados pelo runtime." action={status.alerts.length > 0 ? <span className="alert-count">{status.alerts.length}</span> : undefined}><AlertList items={status.alerts} /></Panel></div>
    {status.rust.last_error && <Panel title="Último erro do Rust"><div className="callout callout--error"><ShieldAlert size={16} />{status.rust.last_error}</div></Panel>}
    <Panel title="Snapshot bruto" description="Payload canônico de /status, para auditoria da interface."><details><summary>Mostrar JSON</summary><JsonPreview value={status} /></details></Panel>
  </div>
}

function ActivityList({ items }: { items: StatusResponse['activity'] }) { if (!items.length) return <EmptyState title="Sem atividade registrada" description="O runtime ainda não reportou atividade nesta janela." />; return <div className="activity-list">{items.slice(0, 8).map((item, index) => <div className="activity-row" key={`${item.timestamp_ns}-${index}`}><span className="activity-marker" /><div><b>{item.operation ?? item.type ?? 'operação'}</b><span>{item.message ?? 'Registro recebido do runtime.'}</span></div><time>{item.status ?? 'observado'}</time></div>)}</div> }
function AlertList({ items }: { items: StatusResponse['alerts'] }) { if (!items.length) return <EmptyState title="Nenhum alerta" description="O servidor não reportou alertas ativos." />; return <div className="alert-list">{items.map((item, index) => <div className="alert-row" key={`${item.code ?? 'alert'}-${index}`}><ShieldAlert size={16} /><div><b>{item.severity ?? 'alerta'}</b><span>{item.message}</span></div></div>)}</div> }
