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
})
