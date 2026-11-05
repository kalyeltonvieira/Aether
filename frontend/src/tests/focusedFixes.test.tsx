import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ExplanationTree } from '../components/ExplanationTree'
import { fixedStrategies } from '../pages/SettingsPage'
import { MetricChart } from '../pages/PerformancePage'
import { parseProofSelection, proofHrefForSolution } from '../features/reasoning/proofLinks'
import { parseContextMap } from '../features/knowledge/valueParsing'
import type { ExplanationNode } from '../types/api'

const recursiveExplanation: ExplanationNode = {
  key: ['alice', 'can_access', 'system'],
  kind: 'derived',
  explicit_fact_id: null,
  provenance: { source: 'rule-engine' },
  provenances: [{ source: 'rule-engine', evidence_type: 'derived' }],
  proofs: [{
    proof: { rule_id: 'access-rule', rule_revision: 3, depth: 2, alternatives: ['system', 42] },
    supports: [{
      key: ['alice', 'member_of', 'ops'],
      kind: 'explicit',
      explicit_fact_id: 17,
      provenances: [{ source: 'directory' }],
      proofs: [],
    }],
  }],
}

describe('focused frontend contract fixes', () => {
  it('preserves the canonical object type in proof links and maps none to null before loading', () => {
    const href = proofHrefForSolution({ key: ['alice', 'score', 42], object_type: 'int' })
    expect(href).toContain('object=42')
    expect(href).toContain('object_type=int')

    const selection = parseProofSelection(new URLSearchParams('subject=alice&predicate=flag&object=&object_type=none'))
    expect(selection).toEqual({ queryKey: { subject: 'alice', predicate: 'flag', object: null }, objectType: 'null' })

    const contextual = proofHrefForSolution(
      { key: ['alice', 'score', 42], object_type: 'int' },
      { domain: 'legal', period: '2026' },
    )
    expect(contextual).toContain('context_filter=')
    const contextualSelection = parseProofSelection(new URLSearchParams(contextual.split('?')[1]))
    expect(contextualSelection?.contextFilter).toEqual({ domain: 'legal', period: '2026' })
  })

  it('accepts only bounded string-to-string context maps', () => {
    expect(parseContextMap('{"domain":"legal"}')).toEqual({ domain: 'legal' })
    expect(parseContextMap('')).toBeUndefined()
    expect(() => parseContextMap('[]')).toThrow(/objeto JSON/)
    expect(() => parseContextMap('{"domain":1}')).toThrow(/strings não vazias/)
  })

  it('renders nested explicit supports as navigable fact links with proof metadata and real alternatives', () => {
    render(<MemoryRouter><ExplanationTree nodes={[recursiveExplanation]} /></MemoryRouter>)
    expect(screen.getByText('Regra access-rule')).toBeInTheDocument()
    expect(screen.getByText('revisão 3')).toBeInTheDocument()
    expect(screen.getByText('profundidade 2')).toBeInTheDocument()
    expect(screen.getByText('system')).toBeInTheDocument()
    expect(screen.getByText('42')).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: /fact #17/ })).toHaveLength(2)
    expect(screen.getAllByRole('link', { name: /fact #17/ })[0]).toHaveAttribute('href', '/knowledge?fact=17')
  })

  it('offers only fixed strategies in Settings', () => {
    expect(fixedStrategies).toEqual(['forward', 'backward', 'hybrid'])
    expect(fixedStrategies).not.toContain('adaptive')
  })

  it('leaves null Rust samples out of chart points instead of plotting zero', () => {
    render(<MetricChart title="Operações Rust" values={[0, null, 2]} color="#b38cff" suffix="" />)
    const points = screen.getByRole('img').querySelector('polyline')?.getAttribute('points') ?? ''
    expect(points).not.toContain('50,')
    expect(screen.getByText('2')).toBeInTheDocument()
  })
})
