import { useEffect, useRef, useState, useCallback } from 'react'
import { api, errorText } from './api'
import { useAppStore } from './store'

export interface LoadResult<T> {
  data: T | null
  loading: boolean
  error: string | null
  reload: () => Promise<void>
  replace: (data: T) => void
}

export function useLoad<T>(url: string | null, pollIntervalMs?: number): LoadResult<T> {
  const tick = useAppStore((s) => s.tick)
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState<boolean>(Boolean(url))
  const [error, setError] = useState<string | null>(null)
  const activeRef = useRef(true)

  const fetcher = useCallback(async () => {
    if (!url) return
    try {
      const res = await api.get<T>(url)
      if (activeRef.current) {
        setData(res)
        setError(null)
      }
    } catch (err) {
      if (activeRef.current) {
        setError(errorText(err))
      }
    } finally {
      if (activeRef.current) {
        setLoading(false)
      }
    }
  }, [url])

  useEffect(() => {
    activeRef.current = true
    setLoading(true)
    if (tick >= 0) {
      void fetcher()
    }

    let intervalId: number | undefined
    if (pollIntervalMs && pollIntervalMs > 0) {
      intervalId = window.setInterval(fetcher, pollIntervalMs)
    }

    return () => {
      activeRef.current = false
      if (intervalId) clearInterval(intervalId)
    }
  }, [fetcher, tick, pollIntervalMs])

  const replace = useCallback((newData: T) => {
    setData(newData)
  }, [])

  return { data, loading, error, reload: fetcher, replace }
}

export function useDebounce<T>(value: T, delayMs: number): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value)

  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedValue(value)
    }, delayMs)

    return () => {
      clearTimeout(handler)
    }
  }, [value, delayMs])

  return debouncedValue
}

export function useKeyCombo(key: string, meta: boolean, callback: () => void) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === key.toLowerCase() && (!meta || e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        callback()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [key, meta, callback])
}
