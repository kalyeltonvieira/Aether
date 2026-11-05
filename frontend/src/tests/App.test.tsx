import { describe, expect, it, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
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
})
