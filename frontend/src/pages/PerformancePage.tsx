import { useState } from 'react'
import { BarChart3, Clock3, Cpu, Gauge, MemoryStick } from 'lucide-react'
import { useLiveUpdates } from '../hooks/useLiveUpdates'
import { useApiData } from '../hooks/useApiData'
import { api } from '../services/apiClient'
import type { MetricsResponse } from '../types/api'
import { EmptyState, ErrorState, LoadingBlock, PageHeader, Panel, StatCard, StatusBadge } from '../components/ui'

export function PerformancePage() {
  const live = useLiveUpdates()
  const [period, setPeriod] = useState('60')
  const metrics = useApiData(() => api.get<MetricsResponse>(`/metrics?period=${period}`), [live.revision, period])
  if (metrics.loading && !metrics.data) return <><PageHeader eyebrow="AETHER / PERFORMANCE" title="Performance Monitor" /><LoadingBlock /></>
  if (metrics.error && !metrics.data) return <><PageHeader eyebrow="AETHER / PERFORMANCE" title="Performance Monitor" /><ErrorState error={metrics.error} retry={metrics.reload} /></>
  const data = metrics.data
  if (!data) return <EmptyState title="Métricas indisponíveis" description="A API não retornou amostras observadas." />
  const latest = data.samples[data.samples.length - 1]
  return <div className="page-stack">
    <PageHeader eyebrow="AETHER / PERFORMANCE" title="Performance Monitor" description="Sinais observados no ring buffer — vazio significa vazio, não uma curva inventada." actions={<label className="period-select">Período<select value={period} onChange={(e) => setPeriod(e.target.value)}><option value="60">60 s</option><option value="300">5 min</option><option value="900">15 min</option><option value="3600">1 h</option></select></label>} />
    <div className="metric-grid metric-grid--four"><StatCard label="CPU atual" value={latest?.cpu_percent ?? 'indisponível'} detail="percentual observado" icon={<Cpu size={17} />} /><StatCard label="RSS atual" value={latest?.rss_bytes ?? 'indisponível'} detail="bytes observados" icon={<MemoryStick size={17} />} /><StatCard label="Latência" value={latest?.last_query_latency_ms ?? 'indisponível'} detail="ms da última query" icon={<Clock3 size={17} />} /><StatCard label="Throughput" value={latest?.throughput_queries_per_second ?? 'indisponível'} detail="queries / segundo" icon={<Gauge size={17} />} /></div>
    <Panel title="Sinais por amostra" description={`${data.samples.length} amostra(s) / retenção ${data.retention_limit}`} action={<StatusBadge status={data.samples.length ? 'observed' : 'empty'} label={data.samples.length ? 'observado' : 'sem dados'} />}>{data.samples.length ? <div className="chart-grid"><MetricChart title="CPU %" values={data.samples.map((sample) => sample.cpu_percent)} color="#3dd9d0" suffix="%" /><MetricChart title="Latência (ms)" values={data.samples.map((sample) => sample.last_query_latency_ms)} color="#6d8dff" suffix=" ms" /><MetricChart title="Throughput" values={data.samples.map((sample) => sample.throughput_queries_per_second)} color="#f6bd60" suffix=" q/s" /><MetricChart title="Operações Rust" values={data.samples.map((sample) => sample.rust_operations)} color="#b38cff" suffix="" /></div> : <EmptyState title="Sem amostras no período" description="O servidor ainda não observou métricas nessa janela." />}</Panel>
    <Panel title="Comparação de estratégias" description="P50/P95 e custos só aparecem quando medidos.">{data.strategies.length ? <div className="table-wrap"><table><thead><tr><th>Estratégia</th><th>Consultas</th><th>P50</th><th>P95</th><th>Decisão</th><th>Manutenção</th></tr></thead><tbody>{data.strategies.map((item) => <tr key={item.strategy}><td className="mono">{item.strategy}</td><td>{item.queries}</td><td>{item.p50_ms ?? 'indisponível'}</td><td>{item.p95_ms ?? 'indisponível'}</td><td>{item.decision_ns ?? 'indisponível'}</td><td>{item.maintenance_ns ?? 'indisponível'}</td></tr>)}</tbody></table></div> : <EmptyState title="Sem comparação registrada" description="Nenhuma estratégia foi observada neste período." />}</Panel>
  </div>
}

export function MetricChart({ title, values, color, suffix }: { title: string; values: Array<number | null>; color: string; suffix: string }) {
  const valid = values.filter((value): value is number => value !== null && Number.isFinite(value))
  const max = valid.length ? Math.max(...valid, 1) : 1
  const points = values.map((value, index) => value === null || !Number.isFinite(value) ? null : `${(index / Math.max(values.length - 1, 1)) * 100},${100 - (value / max) * 82 - 9}`).filter((point): point is string => point !== null).join(' ')
  return <div className="chart-card"><div className="chart-heading"><span>{title}</span><b>{valid.length ? `${valid[valid.length - 1]}${suffix}` : 'indisponível'}</b></div>{valid.length ? <svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label={`${title} com ${values.length} amostras`}><line x1="0" x2="100" y1="90" y2="90" stroke="#26394e" /><polyline fill="none" stroke={color} strokeWidth="2.4" points={points} vectorEffect="non-scaling-stroke" /></svg> : <div className="chart-unavailable">sem medição</div>}</div>
}
