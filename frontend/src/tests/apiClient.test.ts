import { describe, expect, it, beforeEach, vi } from 'vitest'
import { api, ApiError, setCsrfToken } from '../services/apiClient'
import { parseTypedValue } from '../features/knowledge/valueParsing'

describe('api client', () => {
  beforeEach(() => { setCsrfToken('csrf-test'); vi.restoreAllMocks() })
  it('sends relative requests with session credentials and CSRF for mutations', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ fact_id: 7 }), { status: 200, headers: { 'content-type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    await api.post('/facts', { subject: 'a', predicate: 'p', object: 1, object_type: 'integer' })
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/facts', expect.objectContaining({ method: 'POST', credentials: 'include' }))
    const calls = fetchMock.mock.calls as unknown as Array<[RequestInfo | URL, RequestInit?]>
    const init = calls[0]?.[1] ?? {}
    expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('csrf-test')
    expect(new Headers(init.headers).get('Content-Type')).toBe('application/json')
  })
  it('surfaces contract error detail and status', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'predicate inválido' }), { status: 422, headers: { 'content-type': 'application/json' } })))
    await expect(api.get('/facts')).rejects.toMatchObject({ status: 422, message: 'predicate inválido' })
  })
  it('preserves integer, float, boolean, null and JSON values without eval', () => {
    expect(parseTypedValue('42', 'int')).toBe(42)
    expect(parseTypedValue('4.2', 'float')).toBe(4.2)
    expect(parseTypedValue('true', 'bool')).toBe(true)
    expect(parseTypedValue('', 'null')).toBeNull()
    expect(parseTypedValue('?x', 'str')).toBe('?x')
  })
})
