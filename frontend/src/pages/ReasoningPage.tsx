import { useEffect, useState } from 'react'
import { BrainCircuit, ChevronLeft, ChevronRight, Play, Plus, Trash2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useApiData } from '../hooks/useApiData'
import { useLiveUpdates } from '../hooks/useLiveUpdates'
import { useAuth } from '../app/AuthContext'
import { api } from '../services/apiClient'
import type { ConfigResponse, ConflictResolution, InferenceResult, KnowledgeAssessment, QueryResult, QuerySolution, Rule, RulePattern } from '../types/api'

const KNOWLEDGE_STATUS_LABELS: Record<KnowledgeAssessment['status'], string> = {
  explicit: 'Explícito', derived: 'Derivado', unknown: 'Desconhecido',
  contradicted: 'Contradito', insufficient_evidence: 'Evidência insuficiente',
}
import { parseContextMap, parseTypedValue, displayValue, valueTypes, type ValueType } from '../features/knowledge/valueParsing'
import { proofHrefForSolution, valueTypeToObjectType } from '../features/reasoning/proofLinks'
import { ExplanationTree } from '../components/ExplanationTree'
import { EmptyState, ErrorState, InfoCallout, JsonPreview, LoadingBlock, PageHeader, Panel, PermissionNotice, StatusBadge } from '../components/ui'

export function ReasoningPage() {
  const live = useLiveUpdates()
  const { canWrite } = useAuth()
  const [subject, setSubject] = useState('?x')
  const [predicate, setPredicate] = useState('')
  const [object, setObject] = useState('?y')
  const [strategy, setStrategy] = useState<'forward' | 'backward' | 'hybrid' | 'adaptive'>('forward')
  const [objectType, setObjectType] = useState<ValueType>('str')
  const [contextJson, setContextJson] = useState('')
  const [contextFilter, setContextFilter] = useState<Record<string, string> | undefined>()
  const [result, setResult] = useState<QueryResult | null>(null)
  const [inference, setInference] = useState<InferenceResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [queryOffset, setQueryOffset] = useState(0)
  const [rulesRevision, setRulesRevision] = useState(0)
  const [consistencyRevision, setConsistencyRevision] = useState(0)
  const config = useApiData(() => api.get<ConfigResponse>('/config'), [live.revision])
  const rules = useApiData(() => api.get<{ items: Rule[] }>('/rules'), [live.revision, rulesRevision])
  const resolutions = useApiData(() => api.get<{ items: ConflictResolution[] }>('/consistency/resolutions'), [live.revision, consistencyRevision])

  useEffect(() => {
    if (config.data?.default_strategy) setStrategy(config.data.default_strategy)
  }, [config.data])

  const queryAt = async (offset: number, selectedContext = contextFilter) => {
    const parsedObject = object.startsWith('?') ? object : parseTypedValue(object, objectType)
    return api.post<QueryResult>('/queries', { subject, predicate, object: parsedObject, object_type: valueTypeToObjectType(objectType), strategy, offset, limit: 100, context_filter: selectedContext })
  }
  const runQuery = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setInference(null)
    try { const parsedContext = parseContextMap(contextJson); setContextFilter(parsedContext); setQueryOffset(0); setResult(await queryAt(0, parsedContext)) } catch (reason) { setError(reason instanceof Error ? reason.message : 'Falha na consulta.') } finally { setBusy(false) }
  }
  const changePage = async (offset: number) => {
    setBusy(true)
    setError(null)
    try { setQueryOffset(offset); setResult(await queryAt(offset)) } catch (reason) { setError(reason instanceof Error ? reason.message : 'Falha ao paginar consulta.') } finally { setBusy(false) }
  }
  const infer = async () => {
    setBusy(true)
    setError(null)
    try { setInference(await api.post<InferenceResult>('/inference', {})) } catch (reason) { setError(reason instanceof Error ? reason.message : 'Falha na inferência.') } finally { setBusy(false) }
  }

  return <div className="page-stack">
    <PageHeader eyebrow="AETHER / REASONING" title="Reasoning Console" description="Consultas relacionais sem avaliação arbitrária de código; estratégia e completude vêm do engine." actions={canWrite ? <button className="button button--secondary" onClick={() => void infer()} disabled={busy}><BrainCircuit size={16} /> Recomputar inferência</button> : undefined} />
    {!canWrite && <PermissionNotice />}
    {error && <InfoCallout tone="error">{error}</InfoCallout>}
    <div className="reasoning-layout">
      <Panel title="Consulta relacional" description={`Use ?variavel para padrões abertos. Valores tipados preservam a identidade int/float. Padrão da API: ${config.data?.default_strategy ?? 'carregando…'}.`}>
        <form className="query-form" onSubmit={runQuery}>
          <label>Sujeito<input value={subject} onChange={(e) => setSubject(e.target.value)} aria-label="Sujeito da consulta" /></label>
          <label>Predicado<input value={predicate} onChange={(e) => setPredicate(e.target.value)} aria-label="Predicado da consulta" required /></label>
          <label>Objeto<input value={object} onChange={(e) => setObject(e.target.value)} aria-label="Objeto da consulta" /></label>
          <label>Tipo do objeto<select value={objectType} onChange={(e) => setObjectType(e.target.value as ValueType)}>{valueTypes.map((type) => <option value={type.value} key={type.value}>{type.label}</option>)}</select></label>
          <label>Estratégia<select value={strategy} onChange={(e) => setStrategy(e.target.value as typeof strategy)}>{['forward', 'backward', 'hybrid', 'adaptive'].map((option) => <option value={option} key={option}>{option}</option>)}</select></label>
          <label>Filtro contextual <span className="muted">(JSON; ex. domínio/período)</span><textarea aria-label="Filtro contextual JSON" rows={2} value={contextJson} onChange={(e) => setContextJson(e.target.value)} placeholder={'{"domain":"legal","period":"2026"}'} /></label>
          <div className="query-actions"><button className="button button--primary" type="submit" disabled={busy}><Play size={15} />{busy ? 'Executando…' : 'Executar consulta'}</button></div>
        </form>
      </Panel>
      <Panel title="Resultado da consulta" description={result ? `${result.solutions.length} solução(ões) · ${result.strategy} · ${result.execution_ns} ns${result.context_filter ? ` · ${result.context_fact_count ?? 0} fatos elegíveis no contexto` : ''}` : 'A execução real aparecerá aqui.'}>
        {busy && !result ? <LoadingBlock /> : result ? <QueryResultView result={result} offset={queryOffset} onPage={changePage} /> : <EmptyState title="Nenhuma consulta executada" description="Preencha o padrão e execute contra o engine." />}
      </Panel>
    </div>
    <ConsistencyPanel subject={subject} predicate={predicate} object={object} objectType={objectType} canWrite={canWrite} resolutions={resolutions.data?.items ?? []} onReviewed={() => setConsistencyRevision((value) => value + 1)} />
    {inference && <Panel title="Snapshot da inferência" description="Payload canônico retornado por /inference; nenhum tempo ou prova foi inventado."><InferenceView result={inference} /></Panel>}
    <RulePanel rules={rules.data?.items ?? []} loading={rules.loading} error={rules.error} canWrite={canWrite} onChanged={() => setRulesRevision((value) => value + 1)} onRetry={rules.reload} />
  </div>
}

function ConsistencyPanel({ subject, predicate, object, objectType, canWrite, resolutions, onReviewed }: { subject: string; predicate: string; object: string; objectType: ValueType; canWrite: boolean; resolutions: ConflictResolution[]; onReviewed: () => void }) {
  const [otherPredicate, setOtherPredicate] = useState('')
  const [assessment, setAssessment] = useState<KnowledgeAssessment | null>(null)
  const [selectedFactIds, setSelectedFactIds] = useState<number[]>([])
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [payload, setPayload] = useState<Record<string, unknown> | null>(null)
  const assess = async (event: React.FormEvent) => {
    event.preventDefault(); setBusy(true); setError(null); setAssessment(null)
    try {
      if (!subject.trim() || subject.startsWith('?') || !predicate.trim() || predicate.startsWith('?') || object.startsWith('?')) throw new Error('A avaliação exige sujeito, predicado e objeto concretos; variáveis ?x não são afirmações.')
      const claim = { subject, predicate, object: parseTypedValue(object, objectType), object_type: valueTypeToObjectType(objectType), incompatibilities: otherPredicate.trim() ? [{ predicate_a: predicate, predicate_b: otherPredicate.trim() }] : [] }
      setPayload(claim)
      const result = await api.post<KnowledgeAssessment>('/consistency/assessments', claim)
      setAssessment(result); setSelectedFactIds([])
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Falha ao avaliar consistência.') } finally { setBusy(false) }
  }
  const review = async (event: React.FormEvent) => {
    event.preventDefault(); if (!payload || !selectedFactIds.length) return
    setBusy(true); setError(null)
    try {
      const response = await api.post<{ assessment: KnowledgeAssessment }>('/consistency/resolutions', { ...payload, selected_fact_ids: selectedFactIds, reason })
      setAssessment(response.assessment); setReason(''); onReviewed()
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Falha ao registrar revisão.') } finally { setBusy(false) }
  }
  const candidates = assessment ? [...new Set([...assessment.explicit_fact_ids, ...assessment.conflicting_fact_ids])] : []
  return <Panel title="Consistência e suficiência" description="Avalie uma afirmação concreta. Incompatibilidades são declaradas explicitamente; o AETHER não escolhe automaticamente qual fonte é verdadeira.">
    {error && <InfoCallout tone="error">{error}</InfoCallout>}
    <form className="query-form" onSubmit={assess}>
      <label>Predicado incompatível <span className="muted">(opcional; mesmo sujeito, qualquer par de valores)</span><input aria-label="Predicado incompatível" value={otherPredicate} onChange={(event) => setOtherPredicate(event.target.value)} placeholder="ex. falecido" /></label>
      <div className="query-actions"><button className="button button--primary" type="submit" disabled={busy}>{busy ? 'Avaliando…' : 'Avaliar consistência'}</button></div>
    </form>
    {assessment && <div className="result-stack" aria-live="polite">
      <div className="result-summary"><StatusBadge status={assessment.status} label={KNOWLEDGE_STATUS_LABELS[assessment.status]} /><span>{assessment.evidence_sufficient ? 'proveniência suficiente' : 'proveniência insuficiente'}</span><span>{assessment.complete === null ? 'completude desconhecida' : assessment.complete ? 'inferência completa' : 'inferência incompleta'}</span></div>
      <p>{assessment.note}</p>
      <p className="muted">Afirmação: <code className="mono">{JSON.stringify(assessment.claim)}</code></p>
      {assessment.resolution && <InfoCallout tone="info">Revisão registrada por {assessment.resolution.resolved_by}; conflito preservado. Seleção: {assessment.resolution.selected_fact_ids.map((id) => `#${id}`).join(', ')}.</InfoCallout>}
      {assessment.status === 'contradicted' && !assessment.resolution && <form className="rule-form" onSubmit={review}>
        <h3>Registrar revisão humana</h3>
        {!assessment.evidence_sufficient && <InfoCallout tone="error">A revisão está bloqueada porque a evidência ainda é insuficiente.</InfoCallout>}
        {candidates.map((id) => <label key={id}><input type="checkbox" aria-label={`Selecionar fato #${id}`} checked={selectedFactIds.includes(id)} onChange={(event) => setSelectedFactIds((current) => event.target.checked ? [...current, id] : current.filter((value) => value !== id))} /> Aceitar o registro #<b>{id}</b> como seleção desta revisão</label>)}
        <label>Justificativa da revisão<textarea aria-label="Justificativa da revisão" value={reason} onChange={(event) => setReason(event.target.value)} rows={3} /></label>
        {canWrite ? <button className="button button--primary" type="submit" disabled={busy || !assessment.evidence_sufficient || !selectedFactIds.length || !reason.trim()}>{busy ? 'Registrando…' : 'Registrar revisão auditável'}</button> : <PermissionNotice />}
      </form>}
    </div>}
    {resolutions.length > 0 && <details><summary>Histórico de revisões ({resolutions.length})</summary><div className="result-stack">{[...resolutions].reverse().map((item, index) => <div className="rule-row" key={`${item.recorded_at_ns}-${index}`}><div><b>{item.active ? 'Ativa' : 'Invalidada'}</b><span>{item.reason}</span><span className="muted">Fatos {item.fact_ids.map((id) => `#${id}`).join(', ')} · {item.resolved_by}</span></div><StatusBadge status={item.active ? 'active' : 'invalidated'} /></div>)}</div></details>}
  </Panel>
}

function QueryResultView({ result, offset, onPage }: { result: QueryResult; offset: number; onPage: (offset: number) => void }) {
  return <div className="result-stack">
    <div className="result-summary"><StatusBadge status={result.complete ? 'complete' : 'incomplete'} label={result.complete ? 'completo' : 'incompleto'} /><span>{result.proven ? 'há conclusão' : 'sem conclusão'}</span><span>{result.operations} operações</span>{result.stop_reason && <span className="warning-text">{result.stop_reason}</span>}</div>
    {result.solutions.length ? <div className="solution-list">{result.solutions.map((solution, index) => <SolutionCard key={`${solution.fact_id ?? 'derived'}-${index}`} solution={solution} contextFilter={result.context_filter} />)}</div> : <EmptyState title="Nenhuma solução" description={result.context_filter ? 'Nenhuma solução foi encontrada entre os fatos elegíveis para este filtro contextual.' : 'O engine não encontrou uma solução para este padrão.'} />}
    <div className="pagination-row"><button className="button button--ghost" disabled={offset === 0} onClick={() => onPage(Math.max(0, offset - 100))}><ChevronLeft size={14} /> Anterior</button><span className="muted">offset {offset}</span><button className="button button--ghost" disabled={result.next_offset === null} onClick={() => result.next_offset !== null && onPage(result.next_offset)}>Próxima <ChevronRight size={14} /></button></div>
  </div>
}

function SolutionCard({ solution, contextFilter }: { solution: QuerySolution; contextFilter?: Record<string, string> }) {
  const href = proofHrefForSolution(solution, contextFilter)
  return <details open>
    <summary><span className="mono">{solution.key.map(displayValue).join(' · ')}</span><span className="solution-summary-actions"><StatusBadge status={solution.explicit ? 'explicit' : 'derived'} /><Link className="support-link" to={href} onClick={(event) => event.stopPropagation()}>Abrir prova</Link></span></summary>
    <div className="solution-details">
      <div className="solution-meta"><span>Tipo do objeto</span><b className="mono">{solution.object_type ?? 'indisponível'}</b></div>
      {solution.explanation.length ? <><h3>Explicação navegável</h3><ExplanationTree nodes={solution.explanation} /></> : <span className="muted">Sem árvore de explicação para esta solução.</span>}
      <details className="explanation-raw"><summary>Payload suplementar</summary><JsonPreview value={{ bindings: solution.bindings, proofs: solution.proofs, explanation: solution.explanation, fact_id: solution.fact_id }} /></details>
    </div>
  </details>
}

function InferenceView({ result }: { result: InferenceResult }) {
  return <div className="result-stack"><div className="result-summary"><StatusBadge status={result.complete ? 'complete' : 'incomplete'} label={result.complete ? 'completa' : 'incompleta'} /><span>{result.operations} operações</span><span>{result.facts_examined ?? 'indisponível'} fatos examinados</span>{result.stop_reason && <span className="warning-text">{result.stop_reason}</span>}</div>{result.conclusions.length ? <JsonPreview value={result.conclusions} /> : <EmptyState title="Nenhuma conclusão derivada" description="A recomputação real não retornou conclusões." />}</div>
}

function RulePanel({ rules, loading, error, canWrite, onChanged, onRetry }: { rules: Rule[]; loading: boolean; error: Error | null; canWrite: boolean; onChanged: () => void; onRetry: () => void }) {
  const [open, setOpen] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [ruleId, setRuleId] = useState('')
  const [antecedents, setAntecedents] = useState<RulePattern[]>([{ subject: '?x', predicate: '', object: '?y' }])
  const [consequent, setConsequent] = useState<RulePattern>({ subject: '?x', predicate: '', object: '?y' })
  const save = async (event: React.FormEvent) => { event.preventDefault(); try { await api.post('/rules', { rule_id: ruleId, antecedents, consequent }); setOpen(false); setRuleId(''); setAntecedents([{ subject: '?x', predicate: '', object: '?y' }]); onChanged() } catch (reason) { setErrorMessage(reason instanceof Error ? reason.message : 'Falha na regra.') } }
  const remove = async (id: string) => { if (!window.confirm(`Remover a regra ${id}?`)) return; try { await api.delete(`/rules/${id}`); onChanged() } catch (reason) { setErrorMessage(reason instanceof Error ? reason.message : 'Falha ao remover regra.') } }
  const updateAntecedent = (index: number, value: RulePattern) => setAntecedents((current) => current.map((item, itemIndex) => itemIndex === index ? value : item))
  return <Panel title="Regras declaradas" description="Regras são enviadas ao servidor; não há eval ou DSL executado no browser." action={canWrite ? <button className="button button--ghost" onClick={() => setOpen((value) => !value)}><Plus size={15} /> Nova regra</button> : undefined}>
    {error && <ErrorState error={error} retry={onRetry} />}{errorMessage && <InfoCallout tone="error">{errorMessage}</InfoCallout>}
    {loading ? <LoadingBlock /> : !rules.length ? <EmptyState title="Nenhuma regra" description="Crie uma regra para permitir conclusões derivadas reais." /> : <div className="rule-list">{rules.map((rule) => <div className="rule-row" key={rule.rule_id}><div><b>{rule.rule_id}</b><span className="mono">{JSON.stringify(rule.antecedents)} → {JSON.stringify(rule.consequent)}</span></div><div><StatusBadge status={rule.enabled ? 'enabled' : 'disabled'} />{canWrite && <button className="icon-button icon-button--danger" aria-label={`Remover regra ${rule.rule_id}`} onClick={() => void remove(rule.rule_id)}><Trash2 size={15} /></button>}</div></div>)}</div>}
    {open && canWrite && <form className="rule-form" onSubmit={save}><h3>Regra declarada</h3><label>Rule ID<input aria-label="Rule ID" value={ruleId} onChange={(event) => setRuleId(event.target.value)} required placeholder="email-implies-contact" /></label>{antecedents.map((pattern, index) => <div className="antecedent-editor" key={index}><PatternInputs label={`Se ${index + 1}`} pattern={pattern} setPattern={(value) => updateAntecedent(index, value)} />{antecedents.length > 1 && <button type="button" className="button button--ghost" onClick={() => setAntecedents((current) => current.filter((_, itemIndex) => itemIndex !== index))}>Remover antecedente</button>}</div>)}<button type="button" className="button button--ghost" onClick={() => setAntecedents((current) => [...current, { subject: '?x', predicate: '', object: '?y' }])}><Plus size={14} /> Adicionar antecedente</button><PatternInputs label="Então" pattern={consequent} setPattern={setConsequent} /><button className="button button--primary" type="submit">Persistir regra</button></form>}
  </Panel>
}

function PatternInputs({ label, pattern, setPattern }: { label: string; pattern: RulePattern; setPattern: (value: RulePattern) => void }) {
  return <fieldset><legend>{label}</legend><input aria-label={`${label} sujeito`} value={String(pattern.subject)} onChange={(e) => setPattern({ ...pattern, subject: e.target.value })} placeholder="?x" /><input aria-label={`${label} predicado`} value={pattern.predicate} onChange={(e) => setPattern({ ...pattern, predicate: e.target.value })} placeholder="predicado" required /><input aria-label={`${label} objeto`} value={String(pattern.object)} onChange={(e) => setPattern({ ...pattern, object: e.target.value })} placeholder="?y" /></fieldset>
}
