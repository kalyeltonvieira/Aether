import type { ApiErrorBody, JsonValue } from '../types/api'

const API_BASE = '/api/v1'
let csrfToken: string | null = null

export class ApiError extends Error {
  status: number
  body: ApiErrorBody | null
  constructor(message: string, status: number, body: ApiErrorBody | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

export function setCsrfToken(token: string | null) { csrfToken = token }
export function getCsrfToken() { return csrfToken }

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const method = (init.method ?? 'GET').toUpperCase()
  if (method !== 'GET' && method !== 'HEAD' && csrfToken) headers.set('X-CSRF-Token', csrfToken)

  const response = await fetch(`${API_BASE}${path}`, { ...init, headers, credentials: 'include' })
  let body: unknown = null
  const contentType = response.headers.get('content-type') ?? ''
  if (contentType.includes('application/json')) {
    try { body = await response.json() } catch { body = null }
  } else if (!response.ok) {
    body = { detail: (await response.text()) || response.statusText }
  }
  if (!response.ok) {
    const errorBody = (body && typeof body === 'object' ? body : null) as ApiErrorBody | null
    const detail = typeof errorBody?.detail === 'string' ? errorBody.detail : `A API respondeu com ${response.status}.`
    if (response.status === 401) setCsrfToken(null)
    throw new ApiError(detail, response.status, errorBody)
  }
  return body as T
}

function jsonBody(value: unknown): RequestInit { return { body: JSON.stringify(value) } }

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) => request<T>(path, { method: 'POST', ...jsonBody(body) }),
  put: <T>(path: string, body: unknown) => request<T>(path, { method: 'PUT', ...jsonBody(body) }),
  patch: <T>(path: string, body: unknown) => request<T>(path, { method: 'PATCH', ...jsonBody(body) }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}

export function toJsonString(value: unknown): string { return JSON.stringify(value, null, 2) }
export function isJsonValue(value: unknown): value is JsonValue {
  if (value === null || typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return true
  if (Array.isArray(value)) return value.every(isJsonValue)
  return typeof value === 'object' && Object.values(value as Record<string, unknown>).every(isJsonValue)
}
