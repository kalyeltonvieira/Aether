import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../services/apiClient'

export interface ApiDataState<T> { data: T | null; loading: boolean; error: ApiError | Error | null; reload: () => void }

export function useApiData<T>(loader: () => Promise<T>, deps: unknown[] = []): ApiDataState<T> {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiError | Error | null>(null)
  const reloadKey = deps.map(String).join('|')
  const loaderRef = useRef(loader)
  loaderRef.current = loader
  const [revision, setRevision] = useState(0)
  const reload = useCallback(() => setRevision((value) => value + 1), [])

  useEffect(() => {
    let active = true
    setLoading(true)
    setError(null)
    loaderRef.current().then((result) => { if (active) setData(result) }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason : new Error('Falha inesperada ao carregar dados.'))
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [reloadKey, revision])

  return { data, loading, error, reload }
}
