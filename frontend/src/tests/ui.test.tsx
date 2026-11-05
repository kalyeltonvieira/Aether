import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ErrorState, LoadingBlock } from '../components/ui'

describe('shared UI states', () => {
  it('renders an accessible loading status', () => { render(<LoadingBlock label="Carregando contrato…" />); expect(screen.getByRole('status')).toHaveTextContent('Carregando contrato…') })
  it('renders an actionable error state', () => { const retry = vi.fn(); render(<ErrorState error={new Error('API offline')} retry={retry} />); expect(screen.getByRole('alert')).toHaveTextContent('API offline'); expect(screen.getByRole('button', { name: /tentar novamente/i })).toBeInTheDocument() })
})
