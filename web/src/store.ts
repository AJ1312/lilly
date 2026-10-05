import { create } from 'zustand'

export type ThemePref = 'system' | 'light' | 'dark'
export type Toast = { id: number; text: string; tone: 'ok' | 'bad' }

const THEME_KEY = 'lilly-theme'

function readTheme(): ThemePref {
  try {
    const v = localStorage.getItem(THEME_KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch {
    return 'system'
  }
}

export function applyTheme(pref: ThemePref): void {
  const root = document.documentElement
  if (pref === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', pref)
}

interface State {
  auth: 'loading' | 'out' | 'in'
  theme: ThemePref
  tick: number // bumps (at most every few hundred ms) whenever the server reports something changed
  live: boolean
  pending: number
  toasts: Toast[]
  streams: Record<string, string> // text being written right now, by task; never more than the running tasks
  setStream: (taskId: string, text: string) => void
  clearStream: (taskId: string) => void
  setAuth: (a: State['auth']) => void
  setTheme: (t: ThemePref) => void
  bump: () => void
  setLive: (v: boolean) => void
  setPending: (n: number) => void
  toast: (text: string, tone?: Toast['tone']) => void
  dismiss: (id: number) => void
}

let nextToast = 1
let bumpTimer: ReturnType<typeof setTimeout> | undefined
const BUMP_MS = 300 // a burst of server events reloads each live view once, not once per event

export const useApp = create<State>((set, get) => ({
  auth: 'loading',
  theme: readTheme(),
  tick: 0,
  live: false,
  pending: 0,
  toasts: [],
  streams: {},
  setStream: (taskId, text) => set((s) => ({ streams: { ...s.streams, [taskId]: text } })),
  clearStream: (taskId) => set((s) => {
    if (!(taskId in s.streams)) return s
    const { [taskId]: _gone, ...rest } = s.streams
    return { streams: rest }
  }),
  setAuth: (auth) => set({ auth }),
  setTheme: (theme) => {
    try {
      if (theme === 'system') localStorage.removeItem(THEME_KEY)
      else localStorage.setItem(THEME_KEY, theme)
    } catch {
      /* private mode: the choice just lasts for this visit */
    }
    applyTheme(theme)
    set({ theme })
  },
  bump: () => {
    if (bumpTimer !== undefined) return
    bumpTimer = setTimeout(() => {
      bumpTimer = undefined
      set((s) => ({ tick: s.tick + 1 }))
    }, BUMP_MS)
  },
  setLive: (live) => set({ live }),
  setPending: (pending) => set({ pending }),
  toast: (text, tone = 'ok') => {
    const id = nextToast++
    set((s) => ({ toasts: [...s.toasts, { id, text, tone }] }))
    setTimeout(() => get().dismiss(id), 5000)
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}))
