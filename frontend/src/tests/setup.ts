import '@testing-library/jest-dom/vitest'

class MockWebSocket {
  static OPEN = 1
  onopen: (() => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null
  onclose: (() => void) | null = null
  constructor(_url: string) { queueMicrotask(() => this.onopen?.()) }
  close() { this.onclose?.() }
}
vi.stubGlobal('WebSocket', MockWebSocket)
