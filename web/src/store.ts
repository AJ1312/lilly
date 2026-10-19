import { create } from 'zustand'
import type { ThemePref } from './types'

export type NavSection =
  | 'talk'
  | 'workspace'
  | 'agents'
  | 'memory'
  | 'skills'
  | 'routines'
  | 'approvals'
  | 'activity'
  | 'models'
  | 'settings'
  | 'resources'

export interface ToastItem {
  id: string
  text: string
  kind?: 'normal' | 'good' | 'bad' | 'warn'
  timeout?: number
}

interface AppState {
  section: NavSection
  subSection: string | null
  theme: ThemePref
  commandPaletteOpen: boolean
  sidebarCollapsed: boolean
  pendingApprovalsCount: number
  runningTasksCount: number
  liveConnected: boolean
  tick: number
  toasts: ToastItem[]
  selectedTaskId: string | null
  selectedThreadId: string | null

  setSection: (section: NavSection, subSection?: string | null) => void
  setTheme: (theme: ThemePref) => void
  setCommandPalette: (open: boolean) => void
  toggleSidebar: () => void
  setPendingApprovals: (count: number) => void
  setRunningTasks: (count: number) => void
  setLiveConnected: (connected: boolean) => void
  bump: () => void
  toast: (text: string, kind?: 'normal' | 'good' | 'bad' | 'warn') => void
  removeToast: (id: string) => void
  selectTask: (taskId: string | null) => void
  selectThread: (threadId: string | null) => void
}

const THEME_KEY = 'lilly-theme-pref'

function loadSavedTheme(): ThemePref {
  try {
    const val = localStorage.getItem(THEME_KEY)
    if (val === 'light' || val === 'dark' || val === 'system') return val
  } catch {
    // fallback
  }
  return 'system'
}

function applyThemeToDom(theme: ThemePref) {
  const root = document.documentElement
  if (theme === 'system') {
    const isDark = window.matchMedia('(prefers-color-scheme: dark)').matches
    root.setAttribute('data-theme', isDark ? 'dark' : 'light')
  } else {
    root.setAttribute('data-theme', theme)
  }
}

export const useAppStore = create<AppState>((set, get) => {
  const initialTheme = loadSavedTheme()
  applyThemeToDom(initialTheme)

  // System theme change listener
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (get().theme === 'system') {
      applyThemeToDom('system')
    }
  })

  return {
    section: 'talk',
    subSection: null,
    theme: initialTheme,
    commandPaletteOpen: false,
    sidebarCollapsed: false,
    pendingApprovalsCount: 0,
    runningTasksCount: 0,
    liveConnected: false,
    tick: 0,
    toasts: [],
    selectedTaskId: null,
    selectedThreadId: null,

    setSection: (section, subSection = null) => {
      set({ section, subSection })
      window.location.hash = subSection ? `/${section}/${subSection}` : `/${section}`
    },

    setTheme: (theme) => {
      try {
        localStorage.setItem(THEME_KEY, theme)
      } catch {
        // no-op
      }
      applyThemeToDom(theme)
      set({ theme })
    },

    setCommandPalette: (open) => set({ commandPaletteOpen: open }),
    toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
    setPendingApprovals: (count) => set({ pendingApprovalsCount: count }),
    setRunningTasks: (count) => set({ runningTasksCount: count }),
    setLiveConnected: (connected) => set({ liveConnected: connected }),
    bump: () => set((s) => ({ tick: s.tick + 1 })),

    toast: (text, kind = 'normal') => {
      const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
      const item: ToastItem = { id, text, kind }
      set((s) => ({ toasts: [...s.toasts.slice(-4), item] }))
      setTimeout(() => {
        get().removeToast(id)
      }, 4000)
    },

    removeToast: (id) => {
      set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }))
    },

    selectTask: (taskId) => set({ selectedTaskId: taskId }),
    selectThread: (threadId) => set({ selectedThreadId: threadId }),
  }
})
