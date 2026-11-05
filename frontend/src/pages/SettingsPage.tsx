import { useEffect, useState } from 'react'
import { Save, Settings2 } from 'lucide-react'
import { useAuth } from '../app/AuthContext'
import { useLiveUpdates } from '../hooks/useLiveUpdates'
import { useApiData } from '../hooks/useApiData'
import { api } from '../services/apiClient'
import type { ConfigResponse } from '../types/api'
import { EmptyState, ErrorState, InfoCallout, LoadingBlock, PageHeader, Panel, PermissionNotice, StatusBadge } from '../components/ui'

export const fixedStrategies = ['forward', 'backward', 'hybrid'] as const

export function SettingsPage() {
  const live = useLiveUpdates()
  const { canWrite } = useAuth()
  const config = useApiData(() => api.get<ConfigResponse>('/config'), [live.revision])
  const [form, setForm] = useState<ConfigResponse | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  useEffect(() => { if (config.data) setForm(config.data) }, [config.data])
  const update = <K extends keyof ConfigResponse>(key: K, value: ConfigResponse[K]) => setForm((current) => current ? { ...current, [key]: value } : current)
  const save = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!canWrite || !form) return
    setSaving(true)
    try {
      const payload = form.default_strategy === 'adaptive' ? { ...form, default_strategy: 'forward' as const } : form
      await api.put('/config', payload)
      setNotice('Configuração validada e persistida pela API.')
      config.reload()
    } catch (reason) { setNotice(reason instanceof Error ? reason.message : 'A API rejeitou a configuração.') } finally { setSaving(false) }
  }

  if (config.loading && !config.data) return <><PageHeader eyebrow="AETHER / CONFIGURATION" title="Settings" /><LoadingBlock /></>
  if (config.error && !config.data) return <><PageHeader eyebrow="AETHER / CONFIGURATION" title="Settings" /><ErrorState error={config.error} retry={config.reload} /></>
  if (!form) return <EmptyState title="Configuração indisponível" description="A API não retornou os limites do runtime." />
  const adaptiveDefault = form.default_strategy === 'adaptive'
  const visibleStrategy = adaptiveDefault ? 'forward' : form.default_strategy

  return <div className="page-stack">
    <PageHeader eyebrow="AETHER / CONFIGURATION" title="Settings" description="Limites e componentes que o servidor realmente suporta." />
    {!canWrite && <PermissionNotice />}
    {adaptiveDefault && <InfoCallout tone="warning">O snapshot antigo reportou adaptive como padrão. Esta tela oferece somente estratégias fixas; adaptive continua disponível como escolha explícita no console.</InfoCallout>}
    {notice && <InfoCallout tone={notice.includes('rejeitou') ? 'error' : 'info'}>{notice}</InfoCallout>}
    <form onSubmit={save}>
      <Panel title="Consulta e inferência" description="O padrão persistido permanece fixo; adaptive requer uma escolha explícita no Reasoning Console.">
        <div className="settings-grid">
          <label>Estratégia padrão<select value={visibleStrategy} onChange={(e) => update('default_strategy', e.target.value as ConfigResponse['default_strategy'])} disabled={!canWrite}>{fixedStrategies.map((option) => <option value={option} key={option}>{option}</option>)}</select></label>
          <label>Join planner<select value={form.join_planner} onChange={(e) => update('join_planner', e.target.value as ConfigResponse['join_planner'])} disabled={!canWrite}><option value="input">input</option><option value="selective">selective</option></select></label>
          <NumberField label="Profundidade máxima" value={form.max_depth} onChange={(value) => update('max_depth', value)} disabled={!canWrite} />
          <NumberField label="Operações máximas" value={form.max_operations} onChange={(value) => update('max_operations', value)} disabled={!canWrite} />
          <NumberField label="Conclusões máximas" value={form.max_conclusions} onChange={(value) => update('max_conclusions', value)} disabled={!canWrite} />
          <NumberField label="Lote de eventos" value={form.event_batch_size} onChange={(value) => update('event_batch_size', value)} disabled={!canWrite} />
          <NumberField label="Memória máxima (bytes)" value={form.memory_max_bytes} onChange={(value) => update('memory_max_bytes', value)} disabled={!canWrite} />
        </div>
      </Panel>
      <Panel title="Componentes e persistência" description="Toggles refletem capacidades do processo, não preferências cosméticas."><div className="toggle-grid"><Toggle label="Persistência" checked={form.persistence_enabled} onChange={(value) => update('persistence_enabled', value)} disabled={!canWrite} /><Toggle label="Rust engine" checked={form.rust_enabled} onChange={(value) => update('rust_enabled', value)} disabled={!canWrite} /></div></Panel>
      {canWrite ? <button className="button button--primary" type="submit" disabled={saving}><Save size={16} />{saving ? 'Validando…' : 'Salvar configuração'}</button> : <div className="callout callout--warning"><Settings2 size={16} />Somente operadores podem alterar configuração. Snapshot atual exibido sem alterações locais.</div>}
    </form>
  </div>
}

function NumberField({ label, value, onChange, disabled }: { label: string; value: number; onChange: (value: number) => void; disabled: boolean }) { return <label>{label}<input type="number" value={value} onChange={(e) => onChange(Number(e.target.value))} disabled={disabled} min="0" /></label> }
function Toggle({ label, checked, onChange, disabled }: { label: string; checked: boolean; onChange: (value: boolean) => void; disabled: boolean }) { return <label className="toggle-row"><span><b>{label}</b><small>{checked ? 'ativo' : 'inativo'}</small></span><input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} disabled={disabled} /><span className="toggle-track" aria-hidden="true"><span /></span><StatusBadge status={checked} label={checked ? 'on' : 'off'} /></label> }
