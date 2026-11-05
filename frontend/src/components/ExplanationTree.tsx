import { Link } from 'react-router-dom'
import type { ExplanationNode, JsonValue, ProofItem, Provenance } from '../types/api'
import { displayValue } from '../features/knowledge/valueParsing'
import { JsonPreview } from './ui'

interface ExplanationTreeProps {
  nodes: ExplanationNode[]
  onOpenFact?: (factId: number) => void
  depth?: number
}

function recordValue(value: Record<string, unknown>): string {
  return Object.entries(value).map(([key, item]) => `${key}=${displayValue(item)}`).join(' · ')
}

function FactLink({ factId, onOpenFact }: { factId: number; onOpenFact?: (factId: number) => void }) {
  return <Link className="support-link" to={`/knowledge?fact=${encodeURIComponent(String(factId))}`} onClick={() => onOpenFact?.(factId)}>fact #{factId} <span aria-hidden="true">↗</span></Link>
}

function ProofMeta({ proof }: { proof: ProofItem }) {
  const revision = proof.rule_revision ?? proof.revision
  return <div className="explanation-proof-meta">
    <span>{proof.rule_id ? `Regra ${proof.rule_id}` : 'Prova derivada'}</span>
    {revision !== null && revision !== undefined && <span>revisão {revision}</span>}
    {proof.depth !== undefined && <span>profundidade {proof.depth}</span>}
  </div>
}

function ExplanationNodeView({ node, onOpenFact, depth, path }: { node: ExplanationNode; onOpenFact?: (factId: number) => void; depth: number; path: string }) {
  const factId = node.explicit_fact_id
  const kind = node.kind ?? (factId !== null && factId !== undefined ? 'explicit' : 'derived')
  const provenances = node.provenances?.length ? node.provenances : node.provenance ? [node.provenance] : []
  return <details className={`explanation-node explanation-node--${kind}`} open={depth === 0}>
    <summary>
      <span className="explanation-node-heading"><span className="status-badge"><span className="status-dot" />{kind}</span><span className="mono">{node.key.map(displayValue).join(' · ')}</span></span>
      {factId !== null && factId !== undefined && <FactLink factId={factId} onOpenFact={onOpenFact} />}
    </summary>
    <div className="explanation-node-body">
      <div className="explanation-key-grid"><span>chave tipada</span><b className="mono">{node.key.map((value) => displayValue(value)).join(' · ')}</b></div>
      {factId !== null && factId !== undefined && <div className="explanation-key-grid"><span>fato explícito</span><FactLink factId={factId} onOpenFact={onOpenFact} /></div>}
      {provenances.length > 0 && <div className="explanation-provenance"><span>proveniência</span>{provenances.map((provenance, index) => <span className="mono" key={`${provenance.source}-${index}`}>{recordValue(provenance)}</span>)}</div>}
      {node.cycle_truncated && <div className="warning-text">Ciclo truncado pelo limite de explicação.</div>}
      {node.proofs?.length ? <div className="explanation-branches"><span className="explanation-section-label">provas e suportes</span>{node.proofs.map((branch, index) => <div className="explanation-branch" key={`${path}-proof-${index}`}><div className="explanation-branch-heading"><span>Prova {index + 1}</span><ProofMeta proof={branch.proof} /></div>{branch.proof.alternatives?.length ? <div className="explanation-alternatives"><span>alternativas</span>{branch.proof.alternatives.map((alternative, alternativeIndex) => <span className="mono" key={alternativeIndex}>{displayValue(alternative)}</span>)}</div> : null}{branch.supports?.length ? <ExplanationTree nodes={branch.supports} onOpenFact={onOpenFact} depth={depth + 1} /> : <span className="muted">Sem suporte aninhado.</span>}</div>)}</div> : <span className="muted">Sem prova derivada; o nó é sustentado diretamente pelo fato explícito ou não foi provado.</span>}
      <details className="explanation-raw"><summary>Payload canônico</summary><JsonPreview value={node} /></details>
    </div>
  </details>
}

export function ExplanationTree({ nodes, onOpenFact, depth = 0 }: ExplanationTreeProps) {
  if (!nodes.length) return null
  return <div className={`explanation-tree explanation-tree--depth-${depth}`}>{nodes.map((node, index) => <ExplanationNodeView key={`${node.explicit_fact_id ?? 'derived'}-${index}`} node={node} onOpenFact={onOpenFact} depth={depth} path={`${depth}-${index}`} />)}</div>
}

export function TypedValues({ values }: { values: JsonValue[] }) {
  return <div className="typed-values">{values.map((value, index) => <span className="mono" key={index}>{displayValue(value)}</span>)}</div>
}

export type { Provenance }
