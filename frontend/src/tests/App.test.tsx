import { describe, expect, it, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BrowserRouter } from 'react-router-dom'
import { AuthProvider } from '../app/AuthContext'
import { App } from '../app/App'
import { installApiMock } from './mockApi'

function renderApp() { return render(<BrowserRouter><AuthProvider><App /></AuthProvider></BrowserRouter>) }

describe('Studio shell', () => {
  beforeEach(() => { window.history.pushState({}, '', '/'); installApiMock() })
  it('shows dashboard and navigates to Knowledge Explorer through the sidebar', async () => {
    renderApp()
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('link', { name: /knowledge explorer/i }))
    expect(await screen.findByRole('heading', { name: 'Knowledge Explorer' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Fatos' })).toHaveAttribute('aria-selected', 'true')
  })
  it('makes reader mutation controls unavailable and explains why', async () => {
    renderApp()
    await screen.findByRole('heading', { name: 'Dashboard' })
    await userEvent.click(screen.getByRole('link', { name: /knowledge explorer/i }))
    expect(await screen.findByText(/sessão somente leitura/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /novo fato/i })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('link', { name: /settings/i }))
    await waitFor(() => expect(screen.getByText(/somente operadores podem alterar configuração/i)).toBeInTheDocument())
  })

  it('shows persistence as startup-only and disables its runtime toggle for operators', async () => {
    installApiMock({ '/auth/session': { authenticated: true, role: 'operator', auth_mode: 'manus', csrf_token: 'operator-csrf', open_id: 'openid:operator' } })
    renderApp()
    await screen.findByRole('heading', { name: 'Dashboard' })
    await userEvent.click(screen.getByRole('link', { name: /settings/i }))
    expect(await screen.findByText(/persistência é definida na inicialização/i)).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: /persistência \(startup\)/i })).toBeDisabled()
  })

  it('lets operators attach context to a fact in Knowledge Explorer', async () => {
    installApiMock({
      '/auth/session': { authenticated: true, role: 'operator', auth_mode: 'manus', csrf_token: 'operator-csrf', open_id: 'openid:operator' },
      '/facts': { fact_id: 1, evidence_records: [{ context: { domain: 'legal' } }] },
    })
    renderApp()
    await screen.findByRole('heading', { name: 'Dashboard' })
    await userEvent.click(screen.getByRole('link', { name: /knowledge explorer/i }))
    await userEvent.click(await screen.findByRole('button', { name: /novo fato/i }))
    await userEvent.type(screen.getByLabelText('Fato sujeito'), 'alice')
    await userEvent.type(screen.getByLabelText('Fato predicado'), 'role')
    await userEvent.type(screen.getByLabelText('Fato objeto'), 'analyst')
    fireEvent.change(screen.getByLabelText('Contexto da evidência JSON'), { target: { value: '{"domain":"legal"}' } })
    await userEvent.click(screen.getByRole('button', { name: /criar fato/i }))

    await waitFor(() => {
      const factCall = vi.mocked(fetch).mock.calls.find(([input, init]) => String(input).endsWith('/api/v1/facts') && init?.method === 'POST')
      expect(JSON.parse(String(factCall?.[1]?.body))).toMatchObject({ context: { domain: 'legal' } })
    })
  })

  it('sends a context filter with queries and carries it into proof navigation', async () => {
    installApiMock({
      '/queries': {
        solutions: [{ key: ['alice', 'can_access', 'system'], object_type: 'str', bindings: {}, explicit: true, fact_id: 4, proofs: [], explanation: [] }],
        proven: true, complete: true, stop_reason: null, next_offset: null, operations: 1,
        facts_examined: 1, conclusions_produced: 1, strategy: 'forward', decision_ns: 0,
        execution_ns: 10, rationale: null, context_filter: { domain: 'legal' }, context_fact_count: 1,
      },
    })
    renderApp()
    await screen.findByRole('heading', { name: 'Dashboard' })
    await userEvent.click(screen.getByRole('link', { name: /reasoning console/i }))
    await screen.findByRole('heading', { name: 'Reasoning Console' })
    await userEvent.type(screen.getByLabelText('Predicado da consulta'), 'can_access')
    fireEvent.change(screen.getByLabelText('Filtro contextual JSON'), { target: { value: '{"domain":"legal"}' } })
    await userEvent.click(screen.getByRole('button', { name: /executar consulta/i }))

    const proofLink = await screen.findByRole('link', { name: /abrir prova/i })
    expect(decodeURIComponent(proofLink.getAttribute('href') ?? '')).toContain('context_filter={"domain":"legal"}')
    const queryCall = vi.mocked(fetch).mock.calls.find(([input]) => String(input).includes('/api/v1/queries'))
    expect(JSON.parse(String(queryCall?.[1]?.body))).toMatchObject({ context_filter: { domain: 'legal' } })
  })

  it('lets operators withdraw one evidence record by its stable ID', async () => {
    const evidenceId = `ev_${'a'.repeat(64)}`
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    installApiMock({
      '/auth/session': { authenticated: true, role: 'operator', auth_mode: 'manus', csrf_token: 'operator-csrf', open_id: 'openid:operator' },
      '/facts?subject=&predicate=&offset=0&limit=50': {
        items: [{ fact_id: 1, subject: 'alice', predicate: 'role', object: 'analyst', object_type: 'str', properties: {}, confidence: null, provenances: [], evidence_records: [{ evidence_id: evidenceId, provenance: { source: 'record-a' }, confidence: null, context: { domain: 'hr' } }] }],
        total: 1, offset: 0, limit: 50, next_offset: null,
      },
      [`DELETE /facts/1/evidence/${evidenceId}`]: { removed: true, fact_id: 1, evidence_id: evidenceId, fact_deleted: false, fact: null, inference_complete: true, invalidation: null },
    })
    renderApp()
    await screen.findByRole('heading', { name: 'Dashboard' })
    await userEvent.click(screen.getByRole('link', { name: /knowledge explorer/i }))
    await userEvent.click(await screen.findByText('1 registro(s)'))
    await userEvent.click(screen.getByRole('button', { name: `Retirar evidência ${evidenceId}` }))
    expect(await screen.findByText(/outras fontes continuam sustentando o fato/i)).toBeInTheDocument()
    const deleteCall = vi.mocked(fetch).mock.calls.find(([input, init]) => String(input).endsWith(`/api/v1/facts/1/evidence/${evidenceId}`) && init?.method === 'DELETE')
    expect(deleteCall).toBeDefined()
    expect(confirm).toHaveBeenCalledOnce()
    confirm.mockRestore()
  })

  it('assesses a claim and submits a human conflict review with selected fact IDs', async () => {
    const assessment = {
      claim: ['alice', 'alive', 'present'], status: 'contradicted', explicit_fact_ids: [1], derived_proofs: [],
      conflicting_fact_ids: [2], evidence_sufficient: true, complete: true, resolution: null,
      note: 'Conflicting records are preserved; no source or confidence is selected automatically.',
    }
    const reviewed = { ...assessment, resolution: { fact_ids: [1, 2], selected_fact_ids: [1], reason: 'Reviewed witness records.', resolved_by: 'openid:operator', evidence_fingerprint: 'b'.repeat(64), recorded_at_ns: 10, invalidated_at_ns: null, active: true } }
    installApiMock({
      '/auth/session': { authenticated: true, role: 'operator', auth_mode: 'manus', csrf_token: 'operator-csrf', open_id: 'openid:operator' },
      '/consistency/assessments': assessment,
      'POST /consistency/resolutions': { resolution: reviewed.resolution, assessment: reviewed },
    })
    renderApp()
    await screen.findByRole('heading', { name: 'Dashboard' })
    await userEvent.click(screen.getByRole('link', { name: /reasoning console/i }))
    fireEvent.change(await screen.findByLabelText('Sujeito da consulta'), { target: { value: 'alice' } })
    fireEvent.change(screen.getByLabelText('Predicado da consulta'), { target: { value: 'alive' } })
    fireEvent.change(screen.getByLabelText('Objeto da consulta'), { target: { value: 'present' } })
    await userEvent.type(screen.getByLabelText('Predicado incompatível'), 'dead')
    await userEvent.click(screen.getByRole('button', { name: 'Avaliar consistência' }))
    expect(await screen.findByText(/conflicting records are preserved/i)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('checkbox', { name: 'Selecionar fato #1' }))
    await userEvent.type(screen.getByLabelText('Justificativa da revisão'), 'Reviewed witness records.')
    await userEvent.click(screen.getByRole('button', { name: 'Registrar revisão auditável' }))
    await waitFor(() => {
      const call = vi.mocked(fetch).mock.calls.find(([input, init]) => String(input).endsWith('/api/v1/consistency/resolutions') && init?.method === 'POST')
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
        subject: 'alice', predicate: 'alive', object: 'present',
        incompatibilities: [{ predicate_a: 'alive', predicate_b: 'dead' }],
        selected_fact_ids: [1], reason: 'Reviewed witness records.',
      })
    })
    expect(await screen.findByText(/revisão registrada por openid:operator/i)).toBeInTheDocument()
  })
})
