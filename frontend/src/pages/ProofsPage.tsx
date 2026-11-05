import { useState } from 'react'
import { ArrowUpRight, GitBranch, Search } from 'lucide-react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useLiveUpdates } from '../hooks/useLiveUpdates'
import { useApiData } from '../hooks/useApiData'
import { api } from '../services/apiClient'
import type { JsonScalar, ProofItem, ProofResponse } from '../types/api'
import { displayValue, parseTypedValue, valueTypes, type ValueType } from '../features/knowledge/valueParsing'
import { objectTypeToValueType, parseProofSelection, proofHrefForKey, valueTypeToObjectType, type ProofSelection } from '../features/reasoning/proofLinks'
import { ExplanationTree, TypedValues } from '../components/ExplanationTree'
import { EmptyState, ErrorState, InfoCallout, JsonPreview, LoadingBlock, PageHeader, Panel, StatusBadge } from '../components/ui'

export function ProofsPage() {
  const live = useLiveUpdates()
  const navigate = useNavigate()
  const [queryParams] = useSearchParams()
  const [initialSelection] = useState<ProofSelection | null>(() => { try { return parseProofSelection(queryParams) } catch { return null } })
  const [subject, setSubject] = useState(initialSelection?.queryKey.subject ?? queryParams.get('subject') ?? '')
  const [predicate, setPredicate] = useState(initialSelection?.queryKey.predicate ?? queryParams.get('predicate') ?? '')
  const [object, setObject] = useState(queryParams.get('object') ?? '')
  const [objectType, setObjectType] = useState<ValueType>(initialSelection?.objectType ?? objectTypeToValueType(queryParams.get('object_type')) ?? 'str')
  const [queryKey, setQueryKey] = useState<{ subject: string; predicate: string; object: JsonScalar } | null>(initialSelection?.queryKey ?? null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const proof = useApiData<ProofResponse | null>(() => queryKey ? api.post<ProofResponse>('/explanations', { ...queryKey, object_type: valueTypeToObjectType(objectType) }) : Promise.resolve(null), [live.revision, queryKey?.subject, queryKey?.predicate, queryKey?.object, objectType])

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const parsed = object.startsWith('?') ? object : parseTypedValue(object, objectType)
      setQueryKey({ subject, predicate, object: parsed })
      navigate(proofHrefForKey([subject, predicate, parsed], objectType), { replace: true })
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Padrão inválido.') } finally { setBusy(false) }
  }

  return <div className="page-stack">
    <PageHeader eyebrow="AETHER / EVIDENCE" title="Proof Explorer" description="Navegue da conclusão às provas alternativas, suportes originais e dependências." />
    <Panel title="Conclusão a explicar" description="Links de conclusões preservam o tipo canônico; o servidor recebe o valor já convertido antes de explicar.">
      <form className="query-form query-form--proof" onSubmit={submit}>
        <label>Sujeito<input value={subject} onChange={(e) => setSubject(e.target.value)} required placeholder="entity:alice" /></label>
        <label>Predicado<input value={predicate} onChange={(e) => setPredicate(e.target.value)} required placeholder="can_access" /></label>
        <label>Objeto<input value={object} onChange={(e) => setObject(e.target.value)} required={objectType !== 'null'} placeholder="entity:system" /></label>
        <label>Tipo<select value={objectType} onChange={(e) => setObjectType(e.target.value as ValueType)}>{valueTypes.map((type) => <option key={type.value} value={type.value}>{type.label}</option>)}</select></label>
        <button className="button button--primary" disabled={busy} type="submit"><Search size={15} />{busy ? 'Buscando…' : 'Explicar conclusão'}</button>
      </form>
    </Panel>
    {error && <InfoCallout tone="error">{error}</InfoCallout>}
    {proof.loading && queryKey && <LoadingBlock />}
    {proof.error && <ErrorState error={proof.error} retry={proof.reload} />}
    {proof.data && <ProofView data={proof.data} />}
    {!proof.data && !proof.loading && !proof.error && <EmptyState title="Nenhuma conclusão selecionada" description="Informe uma chave relacional para carregar provas e dependências." />}
  </div>
}

function ProofView({ data }: { data: ProofResponse }) {
  return <div className="proof-layout">
    <Panel title="Conclusão" action={<StatusBadge status={data.complete ? 'complete' : 'incomplete'} label={data.complete ? 'completa' : 'incompleta'} />}>
      <div className="conclusion-key"><span className="node-ring" />{data.key.map(displayValue).join(' · ')}</div>
      {data.stop_reason && <div className="warning-text">{data.stop_reason}</div>}
      <h3>Explicação recursiva</h3>
      {data.explanation.length ? <ExplanationTree nodes={data.explanation} /> : <EmptyState title="Sem explicação textual" description="O servidor não retornou explicação para esta conclusão." />}
      <details className="explanation-raw"><summary>Payload suplementar</summary><JsonPreview value={data.explanation} /></details>
    </Panel>
    <Panel title="Provas alternativas" description={`${data.proofs.length} prova(s) retornada(s).`}>
      {data.proofs.length ? <div className="proof-list">{data.proofs.map((item, index) => <ProofCard key={String(item.proof_id ?? index)} proof={item} index={index} />)}</div> : <EmptyState title="Sem provas" description="A conclusão não possui provas válidas no snapshot atual." />}
    </Panel>
  </div>
}

function ProofCard({ proof, index }: { proof: ProofItem; index: number }) {
  const [open, setOpen] = useState(index === 0)
  const supportIds = proof.support_ids ?? (proof.supports ?? []).filter((support): support is number => typeof support === 'number')
  const nonLinkSupports = (proof.supports ?? []).filter((support) => typeof support !== 'number')
  const revision = proof.rule_revision ?? proof.revision
  return <article className={`proof-card ${open ? 'proof-card--open' : ''}`}>
    <button className="proof-card-header" onClick={() => setOpen((value) => !value)}>
      <span className="proof-index">P{index + 1}</span><span><b>{proof.rule_id ? `Regra ${proof.rule_id}` : proof.proof_id ? `Prova ${proof.proof_id}` : 'Prova derivada'}</b><small>{revision === undefined || revision === null ? 'revisão indisponível' : `revisão ${revision}`} · profundidade {proof.depth ?? 'indisponível'} · {supportIds.length} suporte(s)</small></span><GitBranch size={16} />
    </button>
    {open && <div className="proof-card-body">
      {proof.provenance && <div className="proof-meta"><span>Proveniência</span><JsonPreview value={proof.provenance} /></div>}
      <div className="proof-meta"><span>Dependências / suportes</span>{supportIds.length || nonLinkSupports.length ? <div className="support-list">{supportIds.map((id) => <Link key={id} className="support-link" to={`/knowledge?fact=${encodeURIComponent(String(id))}`}>fact #{id} <ArrowUpRight size={13} /></Link>)}{nonLinkSupports.map((support, supportIndex) => <span className="support-link" key={supportIndex}>{displayValue(support)}</span>)}</div> : <span className="muted">Sem suporte registrado.</span>}</div>
      {proof.alternatives && <div className="proof-meta"><span>Alternativas tipadas</span><TypedValues values={proof.alternatives} /></div>}
      <details className="explanation-raw"><summary>Payload da prova</summary><JsonPreview value={proof} /></details>
    </div>}
  </article>
}
