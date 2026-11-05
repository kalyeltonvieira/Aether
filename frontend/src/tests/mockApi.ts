import type { StatusResponse } from '../types/api'

export const testStatus: StatusResponse = {
  core: { status: 'ready', version: 'test', entities: 0, facts: 0, conclusions: 0, complete: true, stale_reason: null },
  api: { status: 'ok', version: 'test', uptime_seconds: 1 },
  rust: { status: 'unavailable', available: false, operations: null, last_error: null },
  queries_executed: 0, events_processed: 0, last_query_latency_ms: null, cpu_percent: null, memory: {}, activity: [], alerts: [],
}

export function installApiMock(overrides: Record<string, unknown> = {}) {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    const path = url.replace(/^.*\/api\/v1/, '')
    const routes: Record<string, unknown> = {
      '/auth/info': { mode: 'manus', login_available: true },
      '/auth/session': { authenticated: true, role: 'reader', auth_mode: 'manus', csrf_token: 'test-csrf', open_id: 'openid:test' },
      '/status': testStatus,
      '/config': { memory_max_bytes: 8388608, max_depth: 8, max_operations: 10000, max_conclusions: 1000, default_strategy: 'forward', join_planner: 'input', persistence_enabled: true, rust_enabled: false, event_batch_size: 100 },
      '/entities?search=&offset=0&limit=50': { items: [], total: 0, offset: 0, limit: 50, next_offset: null },
      '/facts?subject=&predicate=&offset=0&limit=50': { items: [], total: 0, offset: 0, limit: 50, next_offset: null },
      '/history?offset=0&limit=50': { items: [], total: 0, offset: 0, limit: 50, next_offset: null },
      ...overrides,
    }
    const body = routes[path]
    if (body === undefined) return new Response(JSON.stringify({ detail: `Unmocked route: ${path}` }), { status: 500, headers: { 'content-type': 'application/json' } })
    return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } })
  }))
}
