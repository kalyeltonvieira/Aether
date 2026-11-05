import { useEffect, useState } from 'react'
import { BrainCircuit, ChevronLeft, ChevronRight, Play, Plus, Trash2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useApiData } from '../hooks/useApiData'
import { useLiveUpdates } from '../hooks/useLiveUpdates'
import { useAuth } from '../app/AuthContext'
import { api } from '../services/apiClient'
import type { ConfigResponse, InferenceResult, QueryResult, QuerySolution, Rule, RulePattern } from '../types/api'
import { parseTypedValue, displayValue, valueTypes, type ValueType } from '../features/knowledge/valueParsing'
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
  const [result, setResult] = useState<QueryResult | null>(null)
  const [inference, setInference] = useState<InferenceResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [queryOffset, setQueryOffset] = useState(0)
  const [rulesRevision, setRulesRevision] = useState(0)
  const config = useApiData(() => api.get<ConfigResponse>('/config'), [live.revision])
  const rules = useApiData(() => api.get<{ items: Rule[] }>('/rules'), [live.revision, rulesRevision])

  useEffect(() => {
    if (config.data?.default_strategy) setStrategy(config.data.default_strategy)
  }, [config.data])

  const queryAt = async (offset: number) => {
    const parsedObject = object.startsWith('?') ? object : parseTypedValue(object, objectType)
    return api.post<QueryResult>('/queries', { subject, predicate, object: parsedObject, object_type: valueTypeToObjectType(objectType), strategy, offset, limit: 100 })
  }
  const runQuery = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setInference(null)
    try { setQueryOffset(0); setResult(await queryAt(0)) } catch (reason) { setError(reason instanceof Error ? reason.message : 'Falha na consulta.') } finally { setBusy(false) }
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
          <div className="query-actions"><button className="button button--primary" type="submit" disabled={busy}><Play size={15} />{busy ? 'Executando…' : 'Executar consulta'}</button></div>
        </form>
      </Panel>
      <Panel title="Resultado da consulta" description={result ? `${result.solutions.length} solução(ões) · ${result.strategy} · ${result.execution_ns} ns` : 'A execução real aparecerá aqui.'}>
        {busy && !result ? <LoadingBlock /> : result ? <QueryResultView result={result} offset={queryOffset} onPage={changePage} /> : <EmptyState title="Nenhuma consulta executada" description="Preencha o padrão e execute contra o engine." />}
      </Panel>
    </div>
    {inference && <Panel title="Snapshot da inferência" description="Payload canônico retornado por /inference; nenhum tempo ou prova foi inventado."><InferenceView result={inference} /></Panel>}
    <RulePanel rules={rules.data?.items ?? []} loading={rules.loading} error={rules.error} canWrite={canWrite} onChanged={() => setRulesRevision((value) => value + 1)} onRetry={rules.reload} />
  </div>
}

function QueryResultView({ result, offset, onPage }: { result: QueryResult; offset: number; onPage: (offset: number) => void }) {
  return <div className="result-stack">
    <div className="result-summary"><StatusBadge status={result.complete ? 'complete' : 'incomplete'} label={result.complete ? 'completo' : 'incompleto'} /><span>{result.proven ? 'há conclusão' : 'sem conclusão'}</span><span>{result.operations} operações</span>{result.stop_reason && <span className="warning-text">{result.stop_reason}</span>}</div>
    {result.solutions.length ? <div className="solution-list">{result.solutions.map((solution, index) => <SolutionCard key={`${solution.fact_id ?? 'derived'}-${index}`} solution={solution} />)}</div> : <EmptyState title="Nenhuma solução" description="O engine não encontrou uma solução para este padrão." />}
    <div className="pagination-row"><button className="button button--ghost" disabled={offset === 0} onClick={() => onPage(Math.max(0, offset - 100))}><ChevronLeft size={14} /> Anterior</button><span className="muted">offset {offset}</span><button className="button button--ghost" disabled={result.next_offset === null} onClick={() => result.next_offset !== null && onPage(result.next_offset)}>Próxima <ChevronRight size={14} /></button></div>
  </div>
}

function SolutionCard({ solution }: { solution: QuerySolution }) {
  const href = proofHrefForSolution(solution)
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
