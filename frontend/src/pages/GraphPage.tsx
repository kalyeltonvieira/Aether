import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Background, Controls, MiniMap, ReactFlow, ReactFlowProvider, useEdgesState, useNodesState, type Edge, type Node } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Network, Search } from 'lucide-react'
import { useLiveUpdates } from '../hooks/useLiveUpdates'
import { api } from '../services/apiClient'
import type { GraphResponse } from '../types/api'
import { EmptyState, ErrorState, InfoCallout, JsonPreview, LoadingBlock, PageHeader, Panel } from '../components/ui'

export function GraphPage() { return <ReactFlowProvider><GraphCanvas /></ReactFlowProvider> }

function mergeGraph(previous: GraphResponse, next: GraphResponse): GraphResponse {
  const nodes = new Map(previous.nodes.map((node) => [node.id, node]))
  for (const node of next.nodes) nodes.set(node.id, node)
  const edges = new Map(previous.edges.map((edge) => [`fact:${edge.fact_id}`, edge]))
  for (const edge of next.edges) edges.set(`fact:${edge.fact_id}`, edge)
  return { ...next, nodes: [...nodes.values()], edges: [...edges.values()], offset: previous.offset, truncated: previous.truncated || next.truncated }
}

function GraphCanvas() {
  const live = useLiveUpdates()
  const [predicate, setPredicate] = useState('')
  const [center, setCenter] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [graph, setGraph] = useState<GraphResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<Error | null>(null)
  const requestRef = useRef(0)

  const loadGraph = useCallback(async (offset: number, append: boolean) => {
    const requestId = ++requestRef.current
    setLoading(true)
    setError(null)
    try {
      const response = await api.get<GraphResponse>(`/graph?predicate=${encodeURIComponent(predicate)}&center=${encodeURIComponent(center)}&offset=${offset}&limit=250`)
      if (requestId !== requestRef.current) return
      setGraph((current) => append && current ? mergeGraph(current, response) : response)
    } catch (reason) {
      if (requestId !== requestRef.current) return
      setError(reason instanceof Error ? reason : new Error('Falha ao carregar o grafo.'))
    } finally {
      if (requestId === requestRef.current) setLoading(false)
    }
  }, [center, predicate])

  useEffect(() => {
    setSelected(null)
    setNotice(null)
    setGraph(null)
    void loadGraph(0, false)
    return () => { requestRef.current += 1 }
  }, [live.revision, loadGraph])

  const apiNodes = useMemo<Node[]>(() => graph?.nodes.map((node, index) => ({ id: node.id, data: { label: node.label, properties: node.properties }, position: { x: (index % 2) * 360, y: Math.floor(index / 2) * 200 }, type: 'default' })) ?? [], [graph])
  const apiEdges = useMemo<Edge[]>(() => graph?.edges.map((edge) => ({ id: edge.id || `fact:${edge.fact_id}`, source: edge.source, target: edge.target, label: edge.predicate, animated: false, style: { stroke: '#3dd9d0' }, labelStyle: { fill: '#a8b8cb', fontSize: 11 }, labelBgStyle: { fill: '#0b1320', fillOpacity: 0.96 }, labelBgPadding: [6, 3], labelBgBorderRadius: 4 })) ?? [], [graph])
  const [nodes, setNodes, onNodesChange] = useNodesState(apiNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(apiEdges)
  useEffect(() => { setNodes(apiNodes); setEdges(apiEdges) }, [apiEdges, apiNodes, setEdges, setNodes])

  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => { setSelected(node.id) }, [])
  const expand = () => { if (!selected) return; setCenter(selected); setNotice(`Solicitando vizinhança de ${selected} à API.`) }
  const selectedNode = graph?.nodes.find((node) => node.id === selected)
  const nextOffset = graph?.next_offset ?? null
  const total = graph?.total ?? graph?.edges.length ?? 0

  return <div className="page-stack page-stack--graph">
    <PageHeader eyebrow="AETHER / TOPOLOGY" title="Knowledge Graph" description="Nós e arestas vêm exclusivamente de /graph; nada é inferido no cliente." actions={<div className="filter-row"><label className="input-with-icon"><Search size={15} /><input aria-label="Filtrar predicado do grafo" value={predicate} onChange={(e) => setPredicate(e.target.value)} placeholder="predicado" /></label><label className="input-with-icon"><Network size={15} /><input aria-label="Centro da vizinhança" value={center} onChange={(e) => setCenter(e.target.value)} placeholder="center opcional" /></label></div>} />
    {notice && <InfoCallout>{notice}</InfoCallout>}
    {graph?.truncated && <InfoCallout tone="warning">A API truncou esta resposta; carregue a próxima página para continuar a partir do cursor fact_id estável.</InfoCallout>}
    <div className="graph-layout">
      <Panel className="graph-panel" title="Topologia retornada" description={graph ? `${graph.nodes.length} nós · ${graph.edges.length} relações · ${total} relações no filtro${graph.truncated ? ' · resposta truncada' : ''}` : undefined}>
        {loading && !graph ? <LoadingBlock /> : error && !graph ? <ErrorState error={error} retry={() => void loadGraph(0, false)} /> : graph && !graph.nodes.length ? <EmptyState title="Grafo vazio" description="Não existem nós string conectados para estes filtros." /> : <div className="flow-wrap"><ReactFlow nodes={nodes} edges={edges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onNodeClick={onNodeClick} fitView colorMode="dark" aria-label="Grafo de conhecimento"><Background color="#1d2c3d" gap={24} /><Controls /><MiniMap nodeColor="#3dd9d0" maskColor="rgba(7, 12, 19, .78)" /></ReactFlow></div>}
        {graph && <div className="pagination-row graph-pagination"><span className="muted">cursor {graph.offset} · {graph.nodes.length} nós acumulados</span><button className="button button--ghost" disabled={loading || nextOffset === null} onClick={() => nextOffset !== null && void loadGraph(nextOffset, true)}>{loading ? 'Carregando…' : nextOffset === null ? 'Fim do grafo' : 'Carregar próxima'}</button></div>}
      </Panel>
      <Panel title="Nó selecionado" description="Selecione e expanda uma vizinhança real." action={<button className="button button--ghost" disabled={!selected} onClick={expand}>Expandir vizinhança</button>}>{selectedNode ? <><div className="selected-node"><span className="node-ring" /><div><b>{selectedNode.label}</b><span className="mono">{selectedNode.id}</span></div></div><JsonPreview value={selectedNode.properties} /></> : <EmptyState title="Nenhuma seleção" description="Clique em um nó para inspecionar propriedades e buscar relações." />}</Panel>
    </div>
  </div>
}
