import { useState } from 'react'
import { Activity, Play, Plus, RotateCcw } from 'lucide-react'
import { useAuth } from '../app/AuthContext'
import { useLiveUpdates } from '../hooks/useLiveUpdates'
import { useApiData } from '../hooks/useApiData'
import { api } from '../services/apiClient'
import type { ConfigResponse, EventRecord, EventsResponse } from '../types/api'
import { EmptyState, ErrorState, InfoCallout, JsonPreview, LoadingBlock, PageHeader, Panel, PermissionNotice, StatusBadge } from '../components/ui'

export function EventsPage() {
  const live = useLiveUpdates()
  const { canWrite } = useAuth()
  const [eventType, setEventType] = useState('')
  const [status, setStatus] = useState('')
  const [notice, setNotice] = useState<string | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const events = useApiData(() => api.get<EventsResponse>(`/events?event_type=${encodeURIComponent(eventType)}&status=${encodeURIComponent(status)}&after=0&limit=100`), [live.revision, eventType, status])
  const config = useApiData(() => api.get<ConfigResponse>('/config'), [live.revision])
  const effectiveBatchSize = config.data?.event_batch_size
  const process = async () => {
    if (!canWrite) return
    try {
      const result = await api.post('/events/process', {})
      setNotice(`Lote enviado ao Event Engine${effectiveBatchSize ? ` (limite efetivo ${effectiveBatchSize})` : ''}: ${JSON.stringify(result)}`)
      events.reload()
    } catch (reason) { setNotice(reason instanceof Error ? reason.message : 'Falha ao processar lote.') }
  }
  const retry = async (id: string) => {
    if (!canWrite) return
    try { await api.post(`/events/${encodeURIComponent(id)}/retry`, {}); setNotice(`Evento ${id} reenfileirado.`); events.reload() } catch (reason) { setNotice(reason instanceof Error ? reason.message : 'Falha ao reprocessar evento.') }
  }

  return <div className="page-stack">
    <PageHeader eyebrow="AETHER / EVENTS" title="Event Monitor" description={`At-least-once, estados e tentativas do Event Engine — acompanhados em tempo real.${effectiveBatchSize ? ` O processamento usa o lote configurado de até ${effectiveBatchSize} evento(s).` : ''}`} actions={<div className="page-actions">{canWrite && <><button className="button button--ghost" onClick={() => setFormOpen(true)}><Plus size={15} /> Enfileirar evento</button><button className="button button--primary" onClick={() => void process()}><Play size={15} /> Processar lote{effectiveBatchSize ? ` · ${effectiveBatchSize}` : ''}</button></>}</div>} />
    {!canWrite && <PermissionNotice />}
    {notice && <InfoCallout>{notice}</InfoCallout>}
    <Panel title="Fila e histórico" action={<div className="filter-row"><select aria-label="Filtrar tipo de evento" value={eventType} onChange={(e) => setEventType(e.target.value)}><option value="">Todos os tipos</option><option value="entity.add">entity.add</option><option value="fact.add">fact.add</option><option value="fact.remove">fact.remove</option></select><select aria-label="Filtrar status" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">Todos os estados</option><option value="pending">pending</option><option value="processed">processed</option><option value="failed">failed</option></select></div>}>
      {events.loading && !events.data ? <LoadingBlock /> : events.error && !events.data ? <ErrorState error={events.error} retry={events.reload} /> : events.data && !events.data.items.length ? <EmptyState title="Nenhum evento" description="A API retornou uma fila vazia para estes filtros." /> : events.data && <><div className="queue-strip"><div><span>Fila</span><b>{String(events.data.queue.pending ?? 'indisponível')}</b></div><div><span>Processados</span><b>{String(events.data.queue.processed ?? 'indisponível')}</b></div><div><span>Falhas</span><b>{String(events.data.queue.failed ?? 'indisponível')}</b></div><StatusBadge status={events.data.complete ? 'complete' : 'incomplete'} /></div><EventTable items={events.data.items} canWrite={canWrite} onRetry={retry} /></>}
    </Panel>
    {formOpen && <EventForm onClose={() => setFormOpen(false)} onCreated={() => { setFormOpen(false); events.reload(); setNotice('Evento enfileirado pelo servidor.') }} />}
  </div>
}

function EventTable({ items, canWrite, onRetry }: { items: EventRecord[]; canWrite: boolean; onRetry: (id: string) => void }) {
  return <div className="table-wrap"><table><thead><tr><th>Seq.</th><th>Tipo</th><th>Estado</th><th>Tentativas</th><th>Origem</th><th>Último erro</th><th /></tr></thead><tbody>{items.map((item) => <tr key={item.event_id}><td className="mono">{item.sequence}</td><td><span className="predicate-chip">{item.event_type}</span></td><td><StatusBadge status={item.status} /></td><td>{item.attempts}</td><td>{item.source}</td><td className="error-cell">{item.last_error ?? '—'}</td><td><details><summary>payload</summary><JsonPreview value={item.payload} /></details>{canWrite && item.status === 'failed' && <button className="icon-button" aria-label={`Reprocessar evento ${item.event_id}`} onClick={() => void onRetry(item.event_id)}><RotateCcw size={15} /></button>}</td></tr>)}</tbody></table></div>
}

function EventForm({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [eventType, setEventType] = useState('fact.add')
  const [payload, setPayload] = useState('{\n  "subject": "",\n  "predicate": "",\n  "object": ""\n}')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const submit = async (event: React.FormEvent) => { event.preventDefault(); setSaving(true); try { const parsed = JSON.parse(payload); await api.post('/events', { event_type: eventType, source: 'studio', payload: parsed }); onCreated() } catch (reason) { setError(reason instanceof Error ? reason.message : 'Payload JSON inválido ou evento rejeitado.') } finally { setSaving(false) } }
  return <div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-labelledby="event-form-title"><div className="modal-header"><div><div className="eyebrow">WRITE / EVENT ENGINE</div><h2 id="event-form-title">Enfileirar evento</h2></div><button className="icon-button" onClick={onClose} aria-label="Fechar">×</button></div>{error && <InfoCallout tone="error">{error}</InfoCallout>}<form onSubmit={submit} className="form-grid"><label>Tipo<select value={eventType} onChange={(e) => setEventType(e.target.value)}><option value="entity.add">entity.add</option><option value="fact.add">fact.add</option><option value="fact.remove">fact.remove</option></select></label><label className="form-span-2">Payload JSON<textarea rows={9} value={payload} onChange={(e) => setPayload(e.target.value)} required /></label><div className="modal-actions form-span-2"><button className="button button--ghost" type="button" onClick={onClose}>Cancelar</button><button className="button button--primary" type="submit" disabled={saving}>{saving ? 'Enfileirando…' : 'Enviar ao servidor'}</button></div></form></section></div>
}
