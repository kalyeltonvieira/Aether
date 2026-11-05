import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useAuth } from '../app/AuthContext'

interface LiveContextValue { revision: number; connected: boolean; reconnecting: boolean }
const LiveContext = createContext<LiveContextValue>({ revision: 0, connected: false, reconnecting: false })

export function LiveUpdatesProvider({ children }: { children: ReactNode }) {
  const { session } = useAuth()
  const [revision, setRevision] = useState(0)
  const [connected, setConnected] = useState(false)
  const [reconnecting, setReconnecting] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  const socket = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (!session?.authenticated) return
    let disposed = false
    let attempt = 0
    const connect = () => {
      if (disposed) return
      setReconnecting(attempt > 0)
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const ws = new WebSocket(`${protocol}//${window.location.host}/ws`)
      socket.current = ws
      ws.onopen = () => { attempt = 0; setConnected(true); setReconnecting(false) }
      ws.onmessage = () => setRevision((value) => value + 1)
      ws.onerror = () => ws.close()
      ws.onclose = () => {
        setConnected(false)
        if (!disposed) { attempt += 1; timer.current = window.setTimeout(connect, Math.min(15000, 1000 * 2 ** Math.min(attempt, 4))) }
      }
    }
    connect()
    return () => { disposed = true; if (timer.current) window.clearTimeout(timer.current); socket.current?.close(); socket.current = null; setConnected(false) }
  }, [session?.authenticated])

  const value = useMemo(() => ({ revision, connected, reconnecting }), [revision, connected, reconnecting])
  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>
}
export function useLiveUpdates() { return useContext(LiveContext) }
