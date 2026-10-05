import { useCallback, useEffect, useState } from 'react'
import { api, errorText } from './api'
import { useApp } from './store'

export interface Loaded<T> {
  data: T | null
  error: string | null
  loading: boolean
  reload: () => void
  /** Show `data` now, for a path whose fresh copy the caller already holds (such as a save's response). */
  replace: (data: T) => void
}

/**
 * Load `path` from the server, and again whenever Lilly reports a change (when `live`).
 * A null path loads nothing. The request is identified by its path alone, so a new path is a new request
 * and never shows what an earlier path returned.
 */
export function useLoad<T>(path: string | null, live = false): Loaded<T> {
  const [state, setState] = useState<{ path: string | null; data: T | null; error: string | null }>({ path: null, data: null, error: null })
  const [manual, setManual] = useState(0)
  const tick = useApp((s) => s.tick)
  const liveTick = live ? tick : 0
  const mine = state.path === path ? state : null

  useEffect(() => {
    if (path === null) return
    let stale = false
    api
      .get<T>(path)
      .then((data) => { if (!stale) setState({ path, data, error: null }) })
      .catch((e: unknown) => { if (!stale) setState((s) => ({ path, data: s.path === path ? s.data : null, error: errorText(e) })) })
    return () => { stale = true }
    // liveTick and manual are deliberate re-run triggers: the effect must run again without `path` changing.
    // oxlint-disable-next-line react/exhaustive-effect-dependencies
  }, [path, liveTick, manual])

  const reload = useCallback(() => setManual((n) => n + 1), [])
  const replace = useCallback((data: T) => setState({ path, data, error: null }), [path])
  return { data: mine?.data ?? null, error: mine?.error ?? null, loading: path !== null && mine === null, reload, replace }
}

export function useHash(): [string, (h: string) => void] {
  const [hash, setHash] = useState(() => window.location.hash.slice(1) || '/talk')
  useEffect(() => {
    const on = () => setHash(window.location.hash.slice(1) || '/talk')
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return [hash, (h) => { window.location.hash = h }]
}

export function useEscape(onEscape: () => void): void {
  useEffect(() => {
    const on = (e: KeyboardEvent) => { if (e.key === 'Escape') onEscape() }
    window.addEventListener('keydown', on)
    return () => window.removeEventListener('keydown', on)
  }, [onEscape])
}

/** Run `fn` every `ms` while the component is mounted and the tab is visible. */
export function useInterval(fn: () => void, ms: number): void {
  useEffect(() => {
    const id = setInterval(() => { if (!document.hidden) fn() }, ms)
    return () => clearInterval(id)
  }, [fn, ms])
}
